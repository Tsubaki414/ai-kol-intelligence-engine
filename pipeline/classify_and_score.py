#!/usr/bin/env python3
"""
Claude-based classification + scoring for all KOL candidates.

Sources (dedupe by lowercase username):
  - pipeline/circles/virtuals_chinese_builders_step1.json
  - pipeline/circles/xhunt_web3_media_step1.json
  - pipeline/circles/chinese_crypto_analysis_step1.json
  - pipeline/raw_expansion.json (v1 Method A candidates)
  - pipeline/circle_a_step1.json (lite-format old candidates, fallback for existing usernames)

For each candidate:
  1. Pre-filter: bio present, not obvious bot/org
  2. Claude Haiku 4.5 classify + 5-dim score + cooperability
  3. HARD filter: is_real_human AND NOT is_organization_account AND is_ai_crypto_focused

Output:
  - pipeline/classified_kols.json   (real humans, full classification + scores)
  - pipeline/classified_orgs.json   (filtered out for audit)
  - pipeline/classified_skipped.json (pre-filter failures)
  - pipeline/classified_checkpoint.json (live progress)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from anthropic import AsyncAnthropic

# --- Paths ---
ROOT = Path(__file__).resolve().parent.parent
CIRCLES = ROOT / "pipeline" / "circles"
RAW_EXPANSION = ROOT / "pipeline" / "raw_expansion.json"

OUTPUT_HUMANS = ROOT / "pipeline" / "classified_kols.json"
OUTPUT_ORGS = ROOT / "pipeline" / "classified_orgs.json"
OUTPUT_SKIPPED = ROOT / "pipeline" / "classified_skipped.json"
CHECKPOINT = ROOT / "pipeline" / "classified_checkpoint.json"

# --- Config ---
load_dotenv(ROOT / ".env")
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_CONCURRENT = 12
MIN_BIO_LEN = 20
MAX_CANDIDATES = 4500
CHECKPOINT_EVERY = 50

# --- Blacklist: obvious org handles (case-insensitive substring match) ---
ORG_BLACKLIST_SUBSTRINGS = [
    # Exchanges
    "binance", "okx_", "okxchinese", "okex", "bybit", "huobi", "htx_",
    "kraken", "kucoin", "gate_io", "bitget", "upbit",
    "coinbaseassets", "cryptodotcom", "crypto_com", "mexc_global",
    # Project officials
    "virtualprotocol", "virtuals_io", "ai16zdao",
    "akashnet_", "opentensorfdn", "rendernetwork",
    "bittensor_", "bittensorx", "solanafndn",
    "ethereumfoundation", "arbitrum", "optimismfnd",
    # Media outlets
    "coindesk", "cointelegraph", "decryptmedia", "theblock_", "theblock__",
    "blockbeatsasia", "odailynews", "odaily_cn", "foresight_news",
    "chain_catcher", "panewslab", "techflowpost",
    # Aggregators / bots
    "aixbt_agent", "degencryptoinfo", "degennews",
    "_bot", "bot_", "aibot", "priceb", "ticker_",
    # Community brand accounts
    "ethpanda_org", "lxdao_official",
    "cryptoquant_com",
]


def is_probably_org(username: str, name: str, bio: str) -> bool:
    u = (username or "").lower()
    n = (name or "").lower()
    b = (bio or "").lower()
    for sub in ORG_BLACKLIST_SUBSTRINGS:
        if sub in u:
            return True
    if "official" in n[:30]:
        return True
    # "Official [project] account" pattern in bio
    if re.search(r"\bofficial\s+(account|channel|twitter|x account)\b", b[:200]):
        return True
    return False


# --- Candidate loading ---
def load_all_candidates() -> dict[str, dict]:
    pool: dict[str, dict] = {}

    def ingest(profile: dict, source: str):
        username = (profile.get("username") or "").lower()
        if not username:
            return
        if username not in pool:
            pool[username] = dict(profile)
            pool[username]["_source"] = source
        else:
            # Keep the most populated profile
            def score(p):
                s = 0
                if p.get("id"):
                    s += 1
                if p.get("name"):
                    s += 1
                if p.get("description") and len(p["description"]) > 10:
                    s += 2
                if p.get("public_metrics", {}).get("followers_count"):
                    s += 1
                return s
            if score(profile) > score(pool[username]):
                old_source = pool[username].get("_source", "")
                pool[username] = dict(profile)
                pool[username]["_source"] = f"{source}+{old_source}"

    # 1. Ground-truth circles (full profile data)
    for circle_file in [
        CIRCLES / "virtuals_chinese_builders_step1.json",
        CIRCLES / "xhunt_web3_media_step1.json",
        CIRCLES / "chinese_crypto_analysis_step1.json",
    ]:
        if not circle_file.exists():
            continue
        try:
            data = json.loads(circle_file.read_text())
            for anchor_handle, anchor_info in data.get("anchor_data", {}).items():
                # Inject the anchor itself as a candidate (needs to be classified too)
                anchor_profile = {
                    "username": anchor_handle,
                    "id": anchor_info.get("id"),
                    "name": None,
                    "description": None,
                    "public_metrics": {"following_count": anchor_info.get("count", 0)},
                }
                ingest(anchor_profile, f"anchor:{circle_file.stem}")
                # Inject everyone they follow
                for u in anchor_info.get("following", []):
                    if u.get("username"):
                        ingest(u, f"circle:{circle_file.stem}")
        except Exception as e:
            print(f"Error loading {circle_file}: {e}", file=sys.stderr)

    # 2. v1 raw_expansion.json (has bios for all 2515)
    if RAW_EXPANSION.exists():
        try:
            data = json.loads(RAW_EXPANSION.read_text())
            for c in data.get("candidates", []):
                profile = c.get("profile") or {}
                if profile.get("username"):
                    ingest(profile, "v1_raw_expansion")
        except Exception as e:
            print(f"Error loading raw_expansion: {e}", file=sys.stderr)

    return pool


def pre_filter_and_rank(pool: dict, anchor_handles: set) -> tuple[list, list]:
    candidates = []
    skipped = []
    for username, profile in pool.items():
        name = profile.get("name", "") or ""
        bio = profile.get("description", "") or ""
        metrics = profile.get("public_metrics", {}) or {}
        followers = metrics.get("followers_count", 0) or 0
        following = metrics.get("following_count", 0) or 0
        tweet_count = metrics.get("tweet_count", 0) or 0

        # Bio length check
        if len(bio.strip()) < MIN_BIO_LEN:
            # Exception: always include anchors even with thin bios
            if username not in anchor_handles:
                skipped.append({"username": username, "reason": "bio_too_short", "bio_len": len(bio)})
                continue

        # Pre-filter org accounts (but never skip our own anchors)
        if username not in anchor_handles and is_probably_org(username, name, bio):
            skipped.append({"username": username, "reason": "prefilter_org", "name": name[:60]})
            continue

        # Priority scoring
        is_anchor = username in anchor_handles
        priority = 0
        if is_anchor:
            priority += 100000
        # Sweet spot for KOLs: 1K-500K followers
        if 1000 <= followers <= 500000:
            priority += 2000
        elif 500 <= followers < 1000:
            priority += 500
        elif followers > 500000:
            priority += 800
        # Bio richness
        priority += min(1000, len(bio) * 2)
        # Activity
        if tweet_count > 500:
            priority += 300
        elif tweet_count > 100:
            priority += 100
        # Verification
        if profile.get("verified"):
            priority += 200

        candidates.append(
            {
                "username": username,
                "profile": profile,
                "priority": priority,
                "is_anchor": is_anchor,
            }
        )

    candidates.sort(key=lambda c: -c["priority"])
    return candidates, skipped


def get_anchor_handles() -> set[str]:
    anchors = set()
    for circle_file in [
        CIRCLES / "virtuals_chinese_builders_step1.json",
        CIRCLES / "xhunt_web3_media_step1.json",
        CIRCLES / "chinese_crypto_analysis_step1.json",
    ]:
        if circle_file.exists():
            try:
                data = json.loads(circle_file.read_text())
                for h in data.get("anchors", []):
                    anchors.add(h.lower())
            except Exception:
                pass
    return anchors


# --- Claude classification ---

CLAUDE_SYSTEM_PROMPT = """You are classifying crypto Twitter (X) accounts for an AI+Crypto KOL marketing outreach database.

Return a STRICT JSON object with classification, scoring, and cooperability. NO markdown, NO preamble, NO trailing prose. Only the JSON.

CRITICAL RULES:

1. is_organization_account = true for ANY account representing an org/company/project/exchange/media outlet.
   Examples that ARE orgs: @Binance, @Virtuals_io, @ai16zdao, @CoinDesk, @BiteyeCN (if explicitly a media brand), @Web3QuickBites.
   A person named "X at @SomeCompany" is STILL a person if account uses personal voice in bio.
   If bio says "official X account" or contains only product/service description with no personal identity, it IS an org.

2. is_real_human = true ONLY for personal accounts (individual creators, analysts, builders as themselves, traders).

3. is_ai_crypto_focused = true ONLY if bio OR handle suggests meaningful AI+Crypto intersection focus.
   - Pure DeFi traders without AI angle = false
   - Pure AI researchers (@openai employees, etc.) without crypto = false
   - Explicitly "AI Agent builder", "Bittensor", "ElizaOS", "AI + DeFi", "DeAI", "AI x crypto" = true
   - General crypto KOL who happens to tweet about AI sometimes = lean true if bio mentions AI or if it's their niche
   - Pure NFT / meme traders = false

4. tier: Mega≥100K, Macro 10K-100K, Micro 1K-10K, Nano<1K.

5. language: 'zh' if bio contains meaningful Chinese characters; 'en' if primarily English; otherwise best guess.

6. Scoring (all 0-100):
   - view_velocity: estimated engagement efficiency. Weigh follower count, active tweeting (tweet_count), and bio signals of engagement. 60-80 typical for Macro KOLs.
   - content_originality: bio suggests independent analysis/building vs news aggregation. Researchers/builders = 80+, news aggregators = 20-40.
   - audience_authenticity: follower/following ratio health. 2<=ratio<=300 healthy (70-90). ratio>1000 suspicious (30-50). ratio<0.3 bot-like (20-40).
   - sector_relevance: how purely AI+Crypto focused. 90-100 = exclusively AI+Crypto. 60-80 = primarily AI+Crypto with some adjacent. 40-60 = general crypto with AI as one topic.
   - growth_trend: estimated health based on follower count relative to tweet_count + tier. Active and growing = 70-90. Stale = 30-50.
   - overall_score = weighted average: 0.2 * each of the 5 scores.

7. cooperability: infer from bio signals (contact info, "DM for collabs", "#ad" history signals). Never fabricate contact info that isn't clearly in the bio."""


def build_user_prompt(profile: dict) -> str:
    m = profile.get("public_metrics", {}) or {}
    bio = (profile.get("description") or "").strip()[:450]
    return (
        f"handle: @{profile.get('username', '')}\n"
        f"name: {(profile.get('name') or '—')[:60]}\n"
        f"bio: {bio}\n"
        f"followers: {m.get('followers_count', 0)}\n"
        f"following: {m.get('following_count', 0)}\n"
        f"tweet_count: {m.get('tweet_count', 0)}\n"
        f"verified: {profile.get('verified', False)}\n"
        "\n"
        "Return JSON with these exact keys:\n"
        "is_real_human (bool), is_organization_account (bool), is_ai_crypto_focused (bool), "
        "is_active (bool), has_original_content (bool), "
        'sector (one of: "AI Agent","AI Infra","AI + DeFi","AI + Gaming","AI Dev Tools","AI Research","Broader Crypto Commentary","Other"), '
        'tier (one of: "Mega","Macro","Micro","Nano"), '
        'language (one of: "zh","en","ko","ja","other"), '
        'region (one of: "Mainland China","Taiwan","Hong Kong","Singapore","Overseas Chinese","North America","Europe","Southeast Asia","Korea","Japan","Middle East","Other"), '
        "content_type (array of strings from: Technical Analysis, Industry Commentary, Product Review, Tutorial, News, Thread Writer, Meme, Research), "
        'cooperability (object with keys: is_contactable bool, accepts_paid_promos bool, contact_method one of "twitter_dm"/"email"/"telegram"/"via_intermediary"/"none_public", public_email string|null, public_telegram string|null), '
        "outreach_angle (short string), estimated_price_tier (string like '$100-$500 per tweet' or null), "
        "scores (object with view_velocity, content_originality, audience_authenticity, sector_relevance, growth_trend — all 0-100 integers), "
        "overall_score (0-100), score_reasoning (one-sentence string)."
    )


def parse_claude_response(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def classify_one(
    client: AsyncAnthropic,
    candidate: dict,
    semaphore: asyncio.Semaphore,
) -> Optional[dict]:
    async with semaphore:
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=900,
                system=CLAUDE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": build_user_prompt(candidate["profile"])}
                ],
            )
            text = response.content[0].text
            parsed = parse_claude_response(text)
            if not parsed:
                return {
                    "username": candidate["username"],
                    "error": "parse_failed",
                    "raw": text[:200],
                }
            profile = candidate["profile"]
            metrics = profile.get("public_metrics", {}) or {}
            result = {
                "username": candidate["username"],
                "id": profile.get("id"),
                "name": profile.get("name"),
                "bio": profile.get("description"),
                "followers_count": metrics.get("followers_count"),
                "following_count": metrics.get("following_count"),
                "tweet_count": metrics.get("tweet_count"),
                "verified": profile.get("verified", False),
                "source": profile.get("_source", ""),
                "x_url": f"https://x.com/{candidate['username']}",
                "is_anchor": candidate.get("is_anchor", False),
                **parsed,
            }
            return result
        except Exception as e:
            return {"username": candidate["username"], "error": str(e)[:200]}


async def run_classification(candidates: list) -> tuple[list, list, list]:
    client = AsyncAnthropic()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    humans: list[dict] = []
    orgs: list[dict] = []
    errors: list[dict] = []
    processed = 0
    start_time = time.time()

    tasks = [classify_one(client, c, semaphore) for c in candidates]

    for coro in asyncio.as_completed(tasks):
        result = await coro
        processed += 1

        if not result or "error" in result:
            errors.append(result or {"username": "unknown", "error": "none_returned"})
        elif result.get("is_organization_account") or not result.get("is_real_human"):
            orgs.append(result)
        elif not result.get("is_ai_crypto_focused"):
            orgs.append({**result, "_filter_reason": "not_ai_crypto_focused"})
        else:
            humans.append(result)

        if processed % CHECKPOINT_EVERY == 0 or processed == len(candidates):
            elapsed = time.time() - start_time
            rate = processed / max(elapsed, 0.01)
            eta = (len(candidates) - processed) / max(rate, 0.01)
            print(
                f"  [{processed}/{len(candidates)}] humans={len(humans)} "
                f"orgs={len(orgs)} errors={len(errors)} "
                f"({rate:.1f}/s, eta {eta:.0f}s)"
            )
            CHECKPOINT.write_text(
                json.dumps(
                    {
                        "processed": processed,
                        "total": len(candidates),
                        "elapsed_sec": round(elapsed, 1),
                        "humans_count": len(humans),
                        "orgs_count": len(orgs),
                        "errors_count": len(errors),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )

    return humans, orgs, errors


def main():
    print("=" * 72)
    print("Classification + Scoring pipeline (Claude Haiku 4.5)")
    print("=" * 72)

    print("\nLoading all candidate sources...")
    pool = load_all_candidates()
    print(f"Unique candidates in pool: {len(pool)}")

    anchors = get_anchor_handles()
    print(f"Known anchors: {len(anchors)}")

    print("\nPre-filtering...")
    candidates, skipped = pre_filter_and_rank(pool, anchors)
    print(f"Passed pre-filter:      {len(candidates)}")
    print(f"Pre-filter skipped:     {len(skipped)}")

    if len(candidates) > MAX_CANDIDATES:
        print(f"Capping at top {MAX_CANDIDATES} by priority score")
        candidates = candidates[:MAX_CANDIDATES]

    OUTPUT_SKIPPED.write_text(
        json.dumps(skipped, indent=2, ensure_ascii=False, default=str)
    )

    print(f"\nStarting Claude Haiku classification...")
    print(f"  Model:       {CLAUDE_MODEL}")
    print(f"  Concurrency: {MAX_CONCURRENT}")
    print(f"  To classify: {len(candidates)}")
    print()
    start = time.time()
    humans, orgs, errors = asyncio.run(run_classification(candidates))
    elapsed = time.time() - start

    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)
    print(f"Elapsed:                 {elapsed / 60:.1f} min")
    print(f"Humans (AI+Crypto KOLs): {len(humans)}")
    print(f"Orgs/bots/off-topic:     {len(orgs)}")
    print(f"Errors:                  {len(errors)}")

    humans.sort(key=lambda h: -(h.get("overall_score") or 0))

    OUTPUT_HUMANS.write_text(
        json.dumps(
            {
                "metadata": {
                    "total": len(humans),
                    "model": CLAUDE_MODEL,
                    "elapsed_sec": round(elapsed, 1),
                    "pool_size": len(pool),
                    "classified_count": len(candidates),
                    "skipped_prefilter": len(skipped),
                    "orgs_filtered": len(orgs),
                },
                "kols": humans,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    OUTPUT_ORGS.write_text(json.dumps(orgs, indent=2, ensure_ascii=False, default=str))

    print(f"\n✅ Saved:")
    print(f"  Humans: {OUTPUT_HUMANS.relative_to(ROOT)}")
    print(f"  Orgs:   {OUTPUT_ORGS.relative_to(ROOT)}")
    print(f"  Skipped: {OUTPUT_SKIPPED.relative_to(ROOT)}")

    # Summary stats
    if humans:
        from collections import Counter
        sectors = Counter(h.get("sector") for h in humans)
        languages = Counter(h.get("language") for h in humans)
        tiers = Counter(h.get("tier") for h in humans)
        print("\n=== KOL distribution ===")
        print(f"Languages: {dict(languages)}")
        print(f"Tiers:     {dict(tiers)}")
        print(f"Sectors:   {dict(sectors)}")
        print(f"\nTop 10 by overall_score:")
        for i, h in enumerate(humans[:10], 1):
            print(
                f"  {i:>2}. @{h['username']:<22} {h.get('overall_score', 0):>3} "
                f"[{h.get('tier', '?')}/{h.get('language', '?')}] "
                f"{h.get('sector', '?')}"
            )


if __name__ == "__main__":
    main()
