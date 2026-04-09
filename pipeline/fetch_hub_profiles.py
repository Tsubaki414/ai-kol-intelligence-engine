"""
Phase 1 of hub expansion: batch-fetch full profiles (public_metrics) for all
215 ultra_hubs so we have accurate following_count per hub. Needed to estimate
verification cost accurately before running the expensive /following calls.

Cheap: 3 batch calls of 100 ids each = ~$2 total.
Output: pipeline/circles/hub_profiles_enriched.json
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from x_client import XClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

HUB_FILE = ROOT / "pipeline" / "circles" / "hub_candidates.json"
OUTPUT = ROOT / "pipeline" / "circles" / "hub_profiles_enriched.json"


async def main() -> int:
    print("=" * 72)
    print("Fetch full profiles for all 215 ultra_hubs (batched /users endpoint)")
    print("=" * 72)

    hub_data = json.loads(HUB_FILE.read_text())
    ultra = hub_data["ultra_hubs_6_plus"]

    ids = [h["id"] for h in ultra if h.get("id")]
    print(f"Ultra hubs to enrich: {len(ids)}")

    enriched: list[dict] = []
    async with XClient() as x:
        for batch_start in range(0, len(ids), 100):
            batch_ids = ids[batch_start : batch_start + 100]
            print(f"  batch {batch_start//100 + 1}: {len(batch_ids)} ids…")
            users = await x.get_users_by_ids(batch_ids)
            enriched.extend(users)

    print(f"  → enriched {len(enriched)} users")

    by_id = {u["id"]: u for u in enriched}

    combined: list[dict] = []
    for h in ultra:
        u = by_id.get(h.get("id"))
        m = (u.get("public_metrics") if u else {}) or {}
        combined.append(
            {
                "username": h["username"].lower(),
                "id": h.get("id"),
                "anchor_count": h["anchor_count"],
                "followed_by_anchors": h["followed_by_anchors"],
                "name": (u or {}).get("name") or h.get("name"),
                "description": (u or {}).get("description") or h.get("description", ""),
                "verified": (u or {}).get("verified", False),
                "followers_count": m.get("followers_count") or h.get("followers_count") or 0,
                "following_count": m.get("following_count") or 0,
                "tweet_count": m.get("tweet_count") or 0,
            }
        )

    OUTPUT.write_text(json.dumps({"hubs": combined}, indent=2, ensure_ascii=False))
    missing = sum(1 for c in combined if not c["following_count"])
    print()
    print(f"✅ Saved {OUTPUT}")
    print(f"   {len(combined) - missing} hubs have following_count, {missing} still missing (not resolvable → likely deleted/suspended)")
    # Cost estimate preview
    following_counts = [c["following_count"] for c in combined if c["following_count"]]
    if following_counts:
        import statistics

        print(
            f"   following_count stats: min={min(following_counts)}, "
            f"median={int(statistics.median(following_counts))}, "
            f"avg={int(statistics.mean(following_counts))}, "
            f"max={max(following_counts)}"
        )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()) or 0)
