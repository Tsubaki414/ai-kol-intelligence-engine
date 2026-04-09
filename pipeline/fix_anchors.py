"""
Fix anchor classification: fetch fresh profiles for all 16 anchors via X API,
classify via Claude, merge into classified_kols.json.

The original classify_and_score.py run injected anchors with empty bios
(loader bug) so Claude filtered 13 of 16 out. This script fixes that.

Cost: ~16 X API user lookups (trivial) + 16 Claude Haiku calls (~$0.05)
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from x_client import XClient, XAPIError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CLASSIFIED_FILE = ROOT / "pipeline" / "classified_kols.json"

# All 16 anchor handles across 3 circles (deduped, colinwu & phyrexni are bridges)
ANCHOR_HANDLES = [
    # Circle 1 — Virtuals Chinese Builders
    "0xmediaco",
    "Rav_Hedda",
    "0xzagen",
    "starzq",
    "lanhubiji",
    "iamyourchaos",
    # Circle 2 — XHunt Web3 Media
    "BiteyeCN",
    "DeFiTeddy2020",
    "Web3SisterA",
    "0xKevin00",
    "colinwu",
    "PhyrexNi",
    # Circle 3 — Chinese Crypto Analysis (non-overlapping with C2)
    "KuiGas",
    "ZKSgu",
    "jason_chen998",
    "BTCdayu",
]

# Import classification helpers from classify_and_score
sys.path.insert(0, str(ROOT / "pipeline"))
from classify_and_score import (
    CLAUDE_MODEL,
    CLAUDE_SYSTEM_PROMPT,
    build_user_prompt,
    parse_claude_response,
)


async def fetch_anchor_profiles() -> list[dict]:
    """Fetch fresh profile data for all 16 anchors via X API."""
    profiles = []
    async with XClient() as x:
        for handle in ANCHOR_HANDLES:
            try:
                user = await x.get_user_by_username(handle)
                if user:
                    profiles.append(
                        {
                            "username": user["username"].lower(),
                            "id": user["id"],
                            "name": user.get("name"),
                            "description": user.get("description", ""),
                            "verified": user.get("verified", False),
                            "public_metrics": user.get("public_metrics", {}),
                            "_source": "anchor_refetch",
                        }
                    )
                    m = user.get("public_metrics", {})
                    print(
                        f"  ✓ @{handle:<16} {m.get('followers_count', 0):>8,} followers"
                    )
                else:
                    print(f"  ✗ @{handle} not found")
            except XAPIError as e:
                print(f"  ✗ @{handle} error: {e}")
    return profiles


async def classify_profiles(profiles: list[dict]) -> list[dict]:
    client = AsyncAnthropic()
    sem = asyncio.Semaphore(5)  # conservative concurrency for anchor subset

    async def one(p):
        async with sem:
            try:
                response = await client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=900,
                    system=CLAUDE_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": build_user_prompt(p)}],
                )
                text = response.content[0].text
                parsed = parse_claude_response(text)
                if not parsed:
                    return {"username": p["username"], "error": "parse_failed"}
                result = {
                    "username": p["username"],
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "bio": p.get("description"),
                    "followers_count": p.get("public_metrics", {}).get("followers_count"),
                    "following_count": p.get("public_metrics", {}).get("following_count"),
                    "tweet_count": p.get("public_metrics", {}).get("tweet_count"),
                    "verified": p.get("verified", False),
                    "source": "anchor_refetch",
                    "x_url": f"https://x.com/{p['username']}",
                    "is_anchor": True,
                    **parsed,
                }
                return result
            except Exception as e:
                return {"username": p["username"], "error": str(e)[:200]}

    print(f"\nClassifying {len(profiles)} anchors via Claude Haiku...")
    results = await asyncio.gather(*[one(p) for p in profiles])
    return results


async def main():
    print("=" * 72)
    print("Fix anchors: fetch fresh profiles + re-classify")
    print("=" * 72)

    print(f"\nFetching fresh X profiles for {len(ANCHOR_HANDLES)} anchors...")
    profiles = await fetch_anchor_profiles()

    if not profiles:
        print("❌ No profiles fetched — aborting")
        return 1

    classified = await classify_profiles(profiles)

    # CRITICAL: override is_ai_crypto_focused and is_real_human for anchors.
    # These are USER-VERIFIED humans. Claude may still misclassify edge cases but we trust
    # the user's domain knowledge over Claude here.
    forced_anchors = []
    for r in classified:
        if "error" in r:
            print(f"  ✗ @{r['username']}: {r['error']}")
            continue
        # Force anchor status
        r["is_real_human"] = True
        r["is_organization_account"] = False
        r["is_ai_crypto_focused"] = True  # user-verified ground truth
        r["is_anchor"] = True
        forced_anchors.append(r)
        print(
            f"  ✓ @{r['username']:<16} score={r.get('overall_score')} "
            f"[{r.get('tier')}/{r.get('language')}] {r.get('sector')}"
        )

    # Load existing classified_kols.json and merge
    if CLASSIFIED_FILE.exists():
        existing = json.loads(CLASSIFIED_FILE.read_text())
    else:
        existing = {"metadata": {}, "kols": []}

    existing_kols = existing.get("kols", [])

    # Remove any existing entries for our anchors (they had incomplete data)
    anchor_set = {a["username"].lower() for a in forced_anchors}
    existing_kols = [k for k in existing_kols if k.get("username") not in anchor_set]

    # Append the freshly-classified anchors
    merged_kols = existing_kols + forced_anchors

    # Re-sort by overall_score
    merged_kols.sort(key=lambda k: -(k.get("overall_score") or 0))

    existing["kols"] = merged_kols
    existing["metadata"]["total"] = len(merged_kols)
    existing["metadata"]["anchor_fix_applied"] = True
    existing["metadata"]["anchor_count"] = len(forced_anchors)

    CLASSIFIED_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, default=str)
    )

    print(f"\n✅ Saved {len(merged_kols)} total KOLs to classified_kols.json")
    print(f"   ({len(forced_anchors)} anchors guaranteed + {len(existing_kols)} others)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
