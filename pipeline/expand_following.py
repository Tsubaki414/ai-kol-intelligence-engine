"""
Phase 1b — Method A: Following Graph Expansion.

For each verified seed KOL, fetch who they follow via the X API v2. Accumulate candidates
who are followed by multiple seeds — these are "hot leads" (high probability of being in the
same AI+Crypto niche).

Input:  seed_handles_verified.json  (30 verified seeds)
Output: pipeline/raw_expansion.json  (all unique candidates with seed-follow evidence)

Run:
    pipeline/.venv/bin/python pipeline/expand_following.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from x_client import XAPIError, XClient

ROOT = Path(__file__).resolve().parent.parent
SEEDS_FILE = ROOT / "seed_handles_verified.json"
OUTPUT_FILE = ROOT / "pipeline" / "raw_expansion.json"

# How many accounts to fetch from each seed's following list.
# 500 is a good balance between coverage and rate-limit budget.
MAX_FOLLOWING_PER_SEED = 500


def load_seeds() -> list[dict]:
    with SEEDS_FILE.open() as f:
        data = json.load(f)
    return data.get("seeds", [])


async def resolve_seed_ids(x: XClient, seeds: list[dict]) -> dict[str, dict]:
    """Resolve each seed handle to its user ID + basic profile."""
    resolved: dict[str, dict] = {}
    print("\n=== Phase 1: Resolving seed user IDs ===")
    for i, seed in enumerate(seeds, 1):
        handle = seed["handle"].lstrip("@").lower()
        try:
            user = await x.get_user_by_username(handle)
        except XAPIError as e:
            print(f"  [{i:2d}/{len(seeds)}] @{handle:<22} ERROR: {e}")
            continue
        if not user:
            print(f"  [{i:2d}/{len(seeds)}] @{handle:<22} NOT FOUND")
            continue
        resolved[handle] = user
        metrics = user.get("public_metrics", {})
        print(
            f"  [{i:2d}/{len(seeds)}] @{handle:<22} id={user['id']}  "
            f"followers={metrics.get('followers_count', 0):>8,}"
        )
    print(f"\nResolved {len(resolved)}/{len(seeds)} seeds")
    return resolved


async def expand_followings(x: XClient, seed_users: dict[str, dict]) -> dict[str, Any]:
    """For each seed, fetch up to MAX_FOLLOWING_PER_SEED following, accumulate candidates."""
    candidates: dict[str, dict] = defaultdict(
        lambda: {
            "handle": None,
            "profile": None,
            "followed_by_seed_handles": [],
            "followed_by_seed_count": 0,
        }
    )
    errors: list[dict] = []

    print("\n=== Phase 2: Fetching following lists ===")
    for i, (handle, user) in enumerate(seed_users.items(), 1):
        seed_id = user["id"]
        try:
            print(
                f"  [{i:2d}/{len(seed_users)}] @{handle:<22} fetching up to {MAX_FOLLOWING_PER_SEED}…",
                end=" ",
                flush=True,
            )
            following = await x.get_following(seed_id, max_total=MAX_FOLLOWING_PER_SEED)
            print(f"got {len(following)}")
        except XAPIError as e:
            print(f"ERROR: {e}")
            errors.append({"seed": handle, "error": str(e)})
            continue

        for f in following:
            key = f["username"].lower()
            c = candidates[key]
            c["handle"] = "@" + f["username"]
            c["followed_by_seed_handles"].append(handle)
            c["followed_by_seed_count"] = len(c["followed_by_seed_handles"])
            if c["profile"] is None:
                c["profile"] = {
                    "id": f.get("id"),
                    "username": f.get("username"),
                    "name": f.get("name"),
                    "description": f.get("description"),
                    "verified": f.get("verified", False),
                    "public_metrics": f.get("public_metrics", {}),
                }

    return {"candidates": candidates, "errors": errors}


def summarize(result: dict[str, Any], seed_users: dict[str, dict]) -> dict:
    candidates: dict = result["candidates"]

    # Remove candidates that are themselves seeds
    seed_handles_lower = {h.lower() for h in seed_users.keys()}
    filtered = {k: v for k, v in candidates.items() if k not in seed_handles_lower}

    # Sort by number of seeds that follow them (hotter = more seeds)
    sorted_candidates = sorted(
        filtered.values(),
        key=lambda c: c["followed_by_seed_count"],
        reverse=True,
    )

    buckets = {
        "followed_by_≥5_seeds": sum(1 for c in sorted_candidates if c["followed_by_seed_count"] >= 5),
        "followed_by_≥3_seeds": sum(1 for c in sorted_candidates if c["followed_by_seed_count"] >= 3),
        "followed_by_≥2_seeds": sum(1 for c in sorted_candidates if c["followed_by_seed_count"] >= 2),
        "followed_by_1_seed_only": sum(1 for c in sorted_candidates if c["followed_by_seed_count"] == 1),
    }

    return {
        "metadata": {
            "method": "A — Following Graph Expansion (X API v2)",
            "seeds_used": len(seed_users),
            "max_following_per_seed": MAX_FOLLOWING_PER_SEED,
            "total_unique_candidates": len(sorted_candidates),
            "hot_lead_buckets": buckets,
            "errors": result["errors"],
        },
        "candidates": sorted_candidates,
    }


async def main() -> int:
    seeds = load_seeds()
    if not seeds:
        print("ERROR: no seeds loaded from seed_handles_verified.json")
        return 1
    print(f"Loaded {len(seeds)} seeds from {SEEDS_FILE.name}")

    async with XClient() as x:
        seed_users = await resolve_seed_ids(x, seeds)
        if not seed_users:
            print("ERROR: failed to resolve any seed IDs")
            return 1
        result = await expand_followings(x, seed_users)

    summary = summarize(result, seed_users)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    # Print summary
    print("\n=== Summary ===")
    md = summary["metadata"]
    print(f"Method:              {md['method']}")
    print(f"Seeds used:          {md['seeds_used']}")
    print(f"Max following/seed:  {md['max_following_per_seed']}")
    print(f"Unique candidates:   {md['total_unique_candidates']}")
    for k, v in md["hot_lead_buckets"].items():
        print(f"  {k}: {v}")
    if md["errors"]:
        print(f"Errors: {len(md['errors'])}")
        for e in md["errors"][:5]:
            print(f"  - {e}")
    print(f"\nOutput: {OUTPUT_FILE}")

    print("\nTop 10 hottest leads (followed by most seeds):")
    for i, c in enumerate(summary["candidates"][:10], 1):
        p = c["profile"] or {}
        m = p.get("public_metrics", {})
        desc = (p.get("description") or "").replace("\n", " ")[:60]
        print(
            f"  {i:2d}. {c['handle']:<22}  {c['followed_by_seed_count']:2d}★  "
            f"{m.get('followers_count', 0):>8,} followers  — {desc}…"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
