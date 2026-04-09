"""
Phase 1d — Claude pre-classification for KOL tweets and profile signals.

For each KOL that has cached tweets, this script calls Claude Haiku once with
the KOL's bio + last 20 tweets and asks it to return a structured JSON with:

  - tweet_classifications: per-tweet content_class, sector, is_ai_crypto_related,
    originality_score_raw, promo_match, mentioned_tokens
  - contact_signals: email_in_bio, telegram_handle, website
  - past_rate_disclosures: has_public_rate_card, inferred_from_past_promos

Writes back to Supabase:
  - tweets.classification JSONB (per-tweet classification object)
  - users.contact_signals_json JSONB (new column — see migration below)
  - users.promo_history_90d JSONB (derived from tweet_classifications)
  - users.past_rate_disclosures JSONB

This populates the Phase 1d-dependent Layer 1 sub-scores (Content Originality,
Sector Relevance) and Layer 3 Promo History.

Target set: users that have ≥ 5 tweets stored (the 51 KOLs from core_tweets.json).
Cost: ~$0.05-$0.10 for all 51 using Haiku.

Usage:
    python3 -m pipeline.phase_1d_classify            # classify all eligible
    python3 -m pipeline.phase_1d_classify --handle btcdayu  # just one
    python3 -m pipeline.phase_1d_classify --limit 5  # first N for testing
    python3 -m pipeline.phase_1d_classify --dry-run  # don't call API, show prompt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")

from anthropic import Anthropic  # noqa: E402

from pipeline.db import get_client  # noqa: E402

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4000

SYSTEM_PROMPT = """You are a crypto KOL content classifier. You will receive a KOL's profile and their last 20 tweets. Return structured JSON with per-tweet classification and extracted contact/pricing signals.

CONTENT CLASS TAXONOMY (choose exactly one per tweet):
- "retweet": pure retweet with no added commentary
- "news_share": sharing a news headline with minimal commentary
- "meme_casual": meme, joke, or casual non-substantive post
- "quote_with_commentary": quote tweet with the KOL's own added take
- "original_observation": short original observation or opinion
- "thread": post that's part of a longer thread (detect via "1/", "🧵", "thread:", or sequential style)
- "original_deep_analysis": long-form original analysis, data-driven, research-oriented
- "ai_generated_suspected": suspected to be AI-generated (generic phrasing, LLM cadence, no personal voice)

SECTOR (choose one):
- "AI Agent" — AI agent frameworks (ElizaOS, Virtuals, ai16z, etc.)
- "AI Infra" — AI infrastructure (Bittensor, Render, Akash, io.net, etc.)
- "AI + DeFi" — AI applied to DeFi (Numerai, Autonolas, etc.)
- "AI + Gaming" — AI + gaming/NFTs
- "AI Dev Tools" — developer tools for AI in crypto
- "AI Safety" — AI safety / alignment commentary
- "Broader Crypto Commentary" — crypto commentary without AI focus
- "other"

is_ai_crypto_related: true only if the tweet is substantively about AI + Crypto intersection.

promo_match: return a short excerpt (≤ 80 chars) if the tweet contains sponsor-disclosure language ("#ad", "#sponsored", "in partnership with", "supported by", "@X is sponsoring", "paid partnership"). Return null otherwise.

mentioned_tokens: array of {symbol, sentiment}. Sentiment = "bullish" | "bearish" | "neutral". Only include clear $TOKEN or @TokenProject mentions, not general words like "ETH" in passing. Empty array if none.

originality_score_raw: 0-100, your own 0-100 judgment of how original/substantive this particular tweet is (independent of content_class).

is_ai_generated_suspected: boolean.

RETURN JSON OBJECT with exactly these keys:
{
  "contact_signals": {
    "email_in_bio": "email@domain.com" or null,
    "telegram_handle": "@username" or null,
    "website": "https://..." or null
  },
  "past_rate_disclosures": {
    "has_public_rate_card": boolean,
    "inferred_from_past_promos": boolean,
    "rate_card_url": "https://..." or null
  },
  "tweet_classifications": [
    {
      "tweet_id": "...",  (copy from input)
      "content_class": "...",
      "is_ai_generated_suspected": boolean,
      "sector": "...",
      "is_ai_crypto_related": boolean,
      "originality_score_raw": 0-100,
      "promo_match": "..." or null,
      "mentioned_tokens": [{"symbol": "X", "sentiment": "bullish"}]
    },
    ...
  ]
}

Return JSON only, no prose. No markdown code fences."""


def build_user_prompt(handle: str, bio: str, name: str, tier: str | None, tweets: list[dict]) -> str:
    """Render the per-KOL prompt body."""
    lines = [
        f"KOL: @{handle}",
        f"Name: {name or '(none)'}",
        f"Tier: {tier or '(unknown)'}",
        f"Bio: {bio or '(empty)'}",
        "",
        "TWEETS (last 20):",
    ]
    for i, t in enumerate(tweets, 1):
        text = (t.get("text") or "").replace("\n", " ")[:500]
        lines.append(f'[{i}] id={t.get("tweet_id")}  "{text}"')
    lines.append("")
    lines.append("Classify each tweet and extract contact/pricing signals. Return JSON only.")
    return "\n".join(lines)


def fetch_kol_with_tweets(handle: str) -> dict[str, Any] | None:
    """Fetch a KOL + their tweets from Supabase."""
    c = get_client()
    ur = c.table("users").select("handle, name, bio, tier").eq("handle", handle).execute()
    if not ur.data:
        return None
    user = ur.data[0]

    tr = (
        c.table("tweets")
        .select("tweet_id, text, lang, classification")
        .eq("author_handle", handle)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"user": user, "tweets": tr.data}


def fetch_target_handles(limit: int | None = None) -> list[str]:
    """Return handles that have ≥ 5 tweets stored (the set worth classifying)."""
    c = get_client()
    # Count tweets per author
    r = c.table("tweets").select("author_handle").limit(10000).execute()
    from collections import Counter

    counts = Counter(t["author_handle"] for t in r.data)
    handles = sorted(h for h, n in counts.items() if n >= 5)
    if limit:
        handles = handles[:limit]
    return handles


def call_claude(client: Anthropic, user_prompt: str) -> dict[str, Any]:
    """Make one Claude API call with the classification prompt."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    # Strip any accidental code fences
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def write_classifications(handle: str, result: dict[str, Any]) -> int:
    """Write classification back to tweets table + users table. Returns tweet count updated."""
    c = get_client()

    # 1. Update tweets.classification for each tweet
    updated = 0
    for tc in result.get("tweet_classifications", []):
        tweet_id = tc.get("tweet_id")
        if not tweet_id:
            continue
        classification_obj = {
            "content_class": tc.get("content_class"),
            "is_ai_generated_suspected": tc.get("is_ai_generated_suspected", False),
            "sector": tc.get("sector", "other"),
            "is_ai_crypto_related": tc.get("is_ai_crypto_related", False),
            "originality_score_raw": tc.get("originality_score_raw", 0),
            "promo_match": tc.get("promo_match"),
            "mentioned_tokens": tc.get("mentioned_tokens", []),
        }
        c.table("tweets").update({"classification": classification_obj}).eq("tweet_id", tweet_id).execute()
        updated += 1

    # 2. Derive promo_history_90d from tweet_classifications
    promo_matches = [
        tc for tc in result.get("tweet_classifications", []) if tc.get("promo_match")
    ]
    promo_history = {
        "promo_match_count": len(promo_matches),
        "promo_examples": [tc["promo_match"][:80] for tc in promo_matches[:5]],
    }

    # 3. Write user-level signals to users table
    # Use score_traces JSONB to stash phase1d outputs for now (avoid schema churn)
    contact = result.get("contact_signals") or {}
    rates = result.get("past_rate_disclosures") or {}
    user_phase1d = {
        "phase1d_contact_signals": contact,
        "phase1d_past_rate_disclosures": rates,
        "phase1d_promo_history_90d": promo_history,
        "phase1d_classified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # Merge into existing score_traces without clobbering scoring results
    existing = c.table("users").select("score_traces").eq("handle", handle).execute()
    merged: dict[str, Any] = dict(existing.data[0].get("score_traces") or {}) if existing.data else {}
    merged.update(user_phase1d)
    c.table("users").update({"score_traces": merged}).eq("handle", handle).execute()

    return updated


def classify_one(client: Anthropic, handle: str, *, dry_run: bool = False) -> tuple[bool, str | None, int]:
    """Classify one KOL. Returns (success, error, tweets_classified_count)."""
    try:
        data = fetch_kol_with_tweets(handle)
        if not data:
            return False, "handle not found", 0
        user = data["user"]
        tweets = data["tweets"]
        if not tweets:
            return False, "no tweets stored", 0

        prompt = build_user_prompt(
            handle=handle,
            bio=user.get("bio") or "",
            name=user.get("name") or "",
            tier=user.get("tier"),
            tweets=tweets,
        )

        if dry_run:
            print(f"\n=== DRY RUN for @{handle} ===")
            print(prompt[:2000])
            print("... (truncated)" if len(prompt) > 2000 else "")
            return True, None, 0

        result = call_claude(client, prompt)
        n = write_classifications(handle, result)
        return True, None, n
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handle", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        return 1

    client = Anthropic(api_key=api_key)

    if args.handle:
        handles = [args.handle.lstrip("@").lower()]
    else:
        handles = fetch_target_handles(args.limit)

    print(f"Phase 1d: classifying {len(handles)} KOLs (model={MODEL})")
    if args.dry_run:
        print("[DRY RUN — no API calls, no writes]\n")

    t0 = time.time()
    ok = 0
    fail = 0
    total_tweets = 0
    errors: list[tuple[str, str]] = []

    for i, h in enumerate(handles, 1):
        success, err, n = classify_one(client, h, dry_run=args.dry_run)
        if success:
            ok += 1
            total_tweets += n
            if not args.dry_run:
                print(f"  [{i}/{len(handles)}] @{h}  → {n} tweets classified")
        else:
            fail += 1
            errors.append((h, err or "unknown"))
            print(f"  [{i}/{len(handles)}] @{h}  FAILED: {err}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Success: {ok}. Failed: {fail}. Tweets classified: {total_tweets}")

    if errors:
        print("\nErrors:")
        for h, err in errors[:10]:
            print(f"  @{h}: {err}")

    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
