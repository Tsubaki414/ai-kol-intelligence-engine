"""
Heuristic fallback for anchor classification (when Claude credits depleted).

Anchors are user-verified humans. We compute their 5 Dual-Layer scores
deterministically from X API profile metrics. No LLM needed.

Scoring formulas (matches spirit of scoring_spec.md §4):
  view_velocity:
    - Derived from tweet_count + followers + follow ratio.
    - High tweet_count + high follower count => high velocity.
  content_originality:
    - For anchors, default 80 (user verified them as builders/analysts/creators,
      which means they have a voice). Adjusted down if bio looks like news-aggregator.
  audience_authenticity:
    - follower/following ratio health: 2 <= ratio <= 200 gives 85, outside gives 50-70.
  sector_relevance:
    - Default 90 for anchors (user put them in AI+Crypto circles).
  growth_trend:
    - Proxy from followers / (tweet_count + 1). Fewer tweets per follower = higher density.

Cooperability: defaults to is_contactable=True since these are real people
with at least DM access. Circle assignment drives contact_method.
"""

import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from x_client import XClient, XAPIError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CLASSIFIED_FILE = ROOT / "pipeline" / "classified_kols.json"

# Anchor handles + which circle they belong to
ANCHOR_CIRCLE_MAP = {
    # Circle 1 — Virtuals Chinese Builders
    "0xmediaco":     {"circles": ["C1"], "sector": "AI Agent",     "region": "Taiwan",          "language": "zh"},
    "Rav_Hedda":     {"circles": ["C1"], "sector": "AI Agent",     "region": "Taiwan",          "language": "zh"},
    "0xzagen":       {"circles": ["C1"], "sector": "AI Agent",     "region": "Mainland China",  "language": "zh"},
    "starzq":        {"circles": ["C1"], "sector": "AI Agent",     "region": "Mainland China",  "language": "zh"},
    "lanhubiji":     {"circles": ["C1"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "iamyourchaos":  {"circles": ["C1"], "sector": "AI Agent",     "region": "Mainland China",  "language": "zh"},
    # Circle 2 — XHunt Web3 Media
    "BiteyeCN":      {"circles": ["C2"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "DeFiTeddy2020": {"circles": ["C2"], "sector": "AI + DeFi",    "region": "Mainland China",  "language": "zh"},
    "Web3SisterA":   {"circles": ["C2"], "sector": "AI Agent",     "region": "Mainland China",  "language": "zh"},
    "0xKevin00":     {"circles": ["C2"], "sector": "AI Infra",     "region": "Mainland China",  "language": "zh"},
    "colinwu":       {"circles": ["C2", "C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "PhyrexNi":      {"circles": ["C2", "C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    # Circle 3 — Chinese Crypto Analysis
    "KuiGas":        {"circles": ["C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "ZKSgu":         {"circles": ["C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "jason_chen998": {"circles": ["C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
    "BTCdayu":       {"circles": ["C3"], "sector": "Broader Crypto Commentary", "region": "Mainland China", "language": "zh"},
}


def classify_tier(followers: int) -> str:
    if followers >= 100_000:
        return "Mega"
    if followers >= 10_000:
        return "Macro"
    if followers >= 1_000:
        return "Micro"
    return "Nano"


def compute_scores(profile: dict) -> dict:
    """Deterministic 5-dimension Dual-Layer scoring for anchors."""
    m = profile.get("public_metrics", {}) or {}
    followers = m.get("followers_count", 0) or 0
    following = m.get("following_count", 0) or 1
    tweet_count = m.get("tweet_count", 0) or 0
    bio = (profile.get("description") or "").lower()

    # --- view_velocity: engagement potential proxy ---
    # Based on follower tier + tweet activity
    if followers >= 100_000:
        base_velocity = 78
    elif followers >= 30_000:
        base_velocity = 73
    elif followers >= 10_000:
        base_velocity = 68
    elif followers >= 3_000:
        base_velocity = 63
    else:
        base_velocity = 55
    # Adjust for activity
    if tweet_count > 50_000:
        base_velocity += 5
    elif tweet_count > 10_000:
        base_velocity += 2
    elif tweet_count < 500:
        base_velocity -= 10
    view_velocity = max(30, min(100, base_velocity))

    # --- content_originality: anchors presumed to be original voices ---
    # Default 80; adjust for bio signals
    content_originality = 80
    if any(kw in bio for kw in ["official", "announcement", "news"]):
        content_originality -= 30
    if any(kw in bio for kw in ["builder", "founder", "co-founder", "creator", "analyst", "researcher", "podcast"]):
        content_originality += 5
    content_originality = max(30, min(95, content_originality))

    # --- audience_authenticity: follower/following ratio health ---
    ratio = followers / max(following, 1)
    if 2 <= ratio <= 200:
        authenticity = 85
    elif 0.5 <= ratio < 2:
        authenticity = 68
    elif 200 < ratio <= 1000:
        authenticity = 70
    elif ratio > 1000:
        authenticity = 45
    else:
        authenticity = 50

    # --- sector_relevance: user-verified anchors in AI+Crypto circles ---
    sector_relevance = 90

    # --- growth_trend: followers-per-tweet density as growth proxy ---
    if tweet_count > 0:
        density = followers / tweet_count
        if density > 20:
            growth_trend = 85
        elif density > 10:
            growth_trend = 78
        elif density > 5:
            growth_trend = 72
        elif density > 1:
            growth_trend = 65
        else:
            growth_trend = 55
    else:
        growth_trend = 50

    overall = round(
        0.2 * view_velocity
        + 0.2 * content_originality
        + 0.2 * authenticity
        + 0.2 * sector_relevance
        + 0.2 * growth_trend
    )

    return {
        "view_velocity": view_velocity,
        "content_originality": content_originality,
        "audience_authenticity": authenticity,
        "sector_relevance": sector_relevance,
        "growth_trend": growth_trend,
        "overall_score": overall,
    }


async def fetch_and_classify():
    results = []
    async with XClient() as x:
        for handle, meta in ANCHOR_CIRCLE_MAP.items():
            try:
                user = await x.get_user_by_username(handle)
                if not user:
                    print(f"  ✗ @{handle} not found")
                    continue

                m = user.get("public_metrics", {}) or {}
                profile = {
                    "username": user["username"].lower(),
                    "name": user.get("name"),
                    "description": user.get("description", ""),
                    "verified": user.get("verified", False),
                    "public_metrics": m,
                }
                scores_result = compute_scores(profile)
                overall = scores_result.pop("overall_score")

                tier = classify_tier(m.get("followers_count", 0) or 0)

                entry = {
                    "username": user["username"].lower(),
                    "id": user["id"],
                    "name": user.get("name"),
                    "bio": user.get("description", ""),
                    "followers_count": m.get("followers_count"),
                    "following_count": m.get("following_count"),
                    "tweet_count": m.get("tweet_count"),
                    "verified": user.get("verified", False),
                    "source": "anchor_heuristic",
                    "x_url": f"https://x.com/{user['username']}",
                    "is_anchor": True,
                    # Classification (user-verified, not Claude-generated)
                    "is_real_human": True,
                    "is_organization_account": False,
                    "is_ai_crypto_focused": True,
                    "is_active": True,
                    "has_original_content": True,
                    "sector": meta["sector"],
                    "tier": tier,
                    "language": meta["language"],
                    "region": meta["region"],
                    "content_type": ["Industry Commentary", "Research"],
                    # Cooperability: anchors are contactable by default (user trusts them)
                    "cooperability": {
                        "is_contactable": True,
                        "accepts_paid_promos": True,
                        "contact_method": "twitter_dm",
                        "public_email": None,
                        "public_telegram": None,
                    },
                    "outreach_angle": f"{meta['sector']} specialist in user-verified {','.join(meta['circles'])} circle",
                    "estimated_price_tier": {
                        "Mega": "$3000-$8000 per tweet",
                        "Macro": "$800-$2500 per tweet",
                        "Micro": "$200-$700 per tweet",
                        "Nano": "$50-$200 per tweet",
                    }[tier],
                    "scores": scores_result,
                    "overall_score": overall,
                    "score_reasoning": "Heuristic score (user-verified anchor, Claude fallback)",
                }
                results.append(entry)
                print(
                    f"  ✓ @{handle:<16} score={overall} "
                    f"[{tier}/{meta['language']}] {meta['sector']} {','.join(meta['circles'])}"
                )
            except XAPIError as e:
                print(f"  ✗ @{handle} error: {e}")
    return results


def main():
    print("=" * 72)
    print("Heuristic anchor classification (Claude fallback)")
    print("=" * 72)

    anchors = asyncio.run(fetch_and_classify())

    if not anchors:
        print("❌ No anchors classified")
        return 1

    # Load existing classified_kols.json and merge
    existing = json.loads(CLASSIFIED_FILE.read_text())
    existing_kols = existing.get("kols", [])

    # Remove any existing entries for our anchors
    anchor_set = {a["username"] for a in anchors}
    existing_kols = [k for k in existing_kols if k.get("username") not in anchor_set]

    # Append fresh anchors
    merged = existing_kols + anchors
    merged.sort(key=lambda k: -(k.get("overall_score") or 0))

    existing["kols"] = merged
    existing["metadata"]["total"] = len(merged)
    existing["metadata"]["anchor_heuristic_applied"] = True
    existing["metadata"]["anchor_count"] = len(anchors)

    CLASSIFIED_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, default=str)
    )

    print(f"\n✅ Saved {len(merged)} total KOLs")
    print(f"   {len(anchors)} anchors guaranteed (heuristic)")
    print(f"   {len(existing_kols)} non-anchors (Claude-classified)")


if __name__ == "__main__":
    sys.exit(main() or 0)
