"""
Fetch last 20 tweets for each of the 66 core graph nodes (anchors + hubs).

Purpose:
Provide the empirical data needed to calibrate EQR (Engagement Quality Ratio)
bucket thresholds in scoring/scoring_spec.md §4.1. The pipeline currently has
no tweet-level public_metrics anywhere, blocking empirical calibration.

This script is option (B) from spec §14 Q1: core-sample-only fetch, 66 requests
total, well within Basic tier monthly quota.

Output: pipeline/core_tweets.json
  {
    "metadata": {
      "fetched_at": "...",
      "core_nodes_total": 66,
      "fetched_successfully": N,
      "failed": [...],
      "tweets_per_node_requested": 20,
    },
    "tweets_by_handle": {
      "biteyecn": {
        "x_id": "1449010217702739969",
        "tier": "Macro",
        "tweet_count_returned": 18,
        "tweets": [
          {
            "id": "...",
            "created_at": "...",
            "text": "...",
            "lang": "en",
            "referenced_tweets": [...],  # detects retweet/quote/reply
            "public_metrics": {
              "retweet_count": N,
              "reply_count": N,
              "like_count": N,
              "quote_count": N,
            }
          },
          ...
        ]
      },
      ...
    }
  }
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow importing x_client from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from x_client import XClient, XAPIError  # noqa: E402

ROOT = Path(__file__).parent
GRAPH_PATH = ROOT / "circles" / "graph_v1.json"
OUTPUT_PATH = ROOT / "core_tweets.json"


def load_core_nodes() -> list[dict]:
    """Load the 66 core nodes (type in anchor/hub) from graph_v1.json."""
    with GRAPH_PATH.open() as f:
        g = json.load(f)
    return [
        {
            "handle": n["id"],
            "x_id": n["x_id"],
            "type": n.get("type"),
            "tier": n.get("tier"),
            "followers_count": n.get("followers_count"),
        }
        for n in g["nodes"]
        if n.get("type") in ("anchor", "hub")
    ]


async def fetch_all(core_nodes: list[dict], *, per_node: int = 20) -> dict:
    results: dict[str, dict] = {}
    failures: list[dict] = []

    async with XClient() as x:
        for i, node in enumerate(core_nodes, 1):
            handle = node["handle"]
            x_id = node["x_id"]
            print(f"[{i}/{len(core_nodes)}] @{handle} (x_id={x_id}) ...", end=" ", flush=True)
            try:
                tweets = await x.get_user_tweets(str(x_id), max_total=per_node)
                results[handle] = {
                    "x_id": x_id,
                    "type": node["type"],
                    "tier": node["tier"],
                    "followers_count": node["followers_count"],
                    "tweet_count_returned": len(tweets),
                    "tweets": tweets,
                }
                print(f"got {len(tweets)} tweets")
            except XAPIError as e:
                print(f"FAILED: {e.status} {e.body[:80]}")
                failures.append({"handle": handle, "x_id": x_id, "error": str(e)})
            except Exception as e:
                print(f"FAILED: {type(e).__name__}: {e}")
                failures.append({"handle": handle, "x_id": x_id, "error": str(e)})

    return {
        "metadata": {
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "core_nodes_total": len(core_nodes),
            "fetched_successfully": len(results),
            "failed_count": len(failures),
            "failed": failures,
            "tweets_per_node_requested": per_node,
            "source": "fetch_core_tweets.py",
        },
        "tweets_by_handle": results,
    }


async def main() -> int:
    core_nodes = load_core_nodes()
    print(f"Loaded {len(core_nodes)} core nodes from {GRAPH_PATH.name}")
    print(f"Fetching last 20 tweets each via X API v2 /users/:id/tweets\n")

    result = await fetch_all(core_nodes, per_node=20)

    with OUTPUT_PATH.open("w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    md = result["metadata"]
    print(f"\n{'='*60}")
    print(f"Done. Wrote {OUTPUT_PATH.name}")
    print(f"  Successfully fetched: {md['fetched_successfully']}/{md['core_nodes_total']}")
    print(f"  Failed: {md['failed_count']}")
    if md["failed"]:
        print("  Failures:")
        for f in md["failed"][:10]:
            print(f"    {f['handle']}: {f['error'][:100]}")
    return 0 if md["failed_count"] == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
