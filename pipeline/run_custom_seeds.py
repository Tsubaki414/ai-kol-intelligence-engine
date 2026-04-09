"""
Import Your Own Seeds — custom pipeline runner.

Supabase-first: if /following data for the given seeds is already cached in
the `follows` table, the entire graph is built for free (no X API calls).
Only seeds whose /following is NOT yet in Supabase trigger a live X API fetch.

Mutual-follow verification also reads from Supabase first:
- seed ↔ seed mutual → `mutual_follows` view
- hub ↔ seed mutual  → `follows` table (hub's following, if cached)

Usage:
    python pipeline/run_custom_seeds.py --handles shawmakesmagic,punk3700,0xwitchy
    python pipeline/run_custom_seeds.py --input my_seeds.txt
    python pipeline/run_custom_seeds.py --input my_seeds.txt --output custom_graph.json

Default output overwrites kol-intelligence-engine/src/data/graph.json.
Restore with: git checkout kol-intelligence-engine/src/data/graph.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from db import get_client          # noqa: E402
from x_client import XClient, XAPIError  # noqa: E402

DEFAULT_OUTPUT = ROOT / "kol-intelligence-engine" / "src" / "data" / "graph.json"
MAX_FOLLOWING_PER_SEED = 1000
MIN_SEEDS = 3
MAX_SEEDS = 20
HUB_MIN_ANCHORS = 2    # must be followed by ≥N seeds to be a hub candidate
HUB_MAX_SHOW = 300
COST_PER_USER = 0.0088


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_handles(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[\n,\s]+", text):
        h = part.strip().lstrip("@").lower()
        if h and re.match(r"^[a-z0-9_]{1,15}$", h) and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _tier(followers: int) -> str:
    if followers >= 100_000: return "Mega"
    if followers >= 10_000:  return "Macro"
    if followers >= 1_000:   return "Micro"
    return "Nano"


# ---------------------------------------------------------------------------
# Supabase queries
# ---------------------------------------------------------------------------

def load_cached_following(seed_handles: list[str]) -> dict[str, set[str]]:
    """
    For seeds that already have /following data in Supabase, return a
    {follower_handle: set(followee_handles)} map.
    """
    c = get_client()
    r = c.table("follows").select("follower_handle,followee_handle") \
        .in_("follower_handle", seed_handles).execute()
    result: dict[str, set[str]] = defaultdict(set)
    for row in (r.data or []):
        result[row["follower_handle"]].add(row["followee_handle"])
    return dict(result)


def load_seed_profiles(seed_handles: list[str]) -> dict[str, dict]:
    """Load profile data for seeds from Supabase users table."""
    c = get_client()
    r = c.table("users").select(
        "handle,name,bio,followers_count,following_count,tier,sector,language"
    ).in_("handle", seed_handles).execute()
    return {row["handle"]: row for row in (r.data or [])}


def query_mutual_follows(seed_handles: list[str]) -> list[tuple[str, str]]:
    """
    Return (a, b) mutual pairs from the mutual_follows view
    where BOTH a and b are in seed_handles.
    """
    c = get_client()
    r = c.table("mutual_follows").select("handle_a,handle_b") \
        .in_("handle_a", seed_handles).in_("handle_b", seed_handles).execute()
    return [(row["handle_a"], row["handle_b"]) for row in (r.data or [])]


def query_hub_mutual_confirmation(
    hub_handles: list[str], seed_handles: list[str]
) -> set[str]:
    """
    Among hub_handles, return those that follow ≥1 seed (i.e., we have their
    /following cached AND it contains a seed → confirmed mutual member).
    """
    if not hub_handles:
        return set()
    c = get_client()
    r = c.table("follows").select("follower_handle") \
        .in_("follower_handle", hub_handles) \
        .in_("followee_handle", seed_handles).execute()
    return {row["follower_handle"] for row in (r.data or [])}


# ---------------------------------------------------------------------------
# X API fallback (only for seeds not in Supabase)
# ---------------------------------------------------------------------------

async def fetch_and_save_seeds(
    missing: list[str],
) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """
    Fetch /following for seeds not cached in Supabase.
    Saves results back to Supabase (users + follows tables).
    Returns (followings_dict, profiles_dict).
    """
    c = get_client()
    followings: dict[str, set[str]] = {}
    profiles: dict[str, dict] = {}

    async with XClient() as x:
        # Resolve handles → user IDs
        print(f"\n  Resolving {len(missing)} handles via X API…")
        seed_users: dict[str, dict] = {}
        for h in missing:
            try:
                user = await x.get_user_by_username(h)
                if user:
                    seed_users[h] = user
                    m = user.get("public_metrics", {})
                    print(f"  ✓ @{h:<22} followers={m.get('followers_count', 0):>8,}")
                else:
                    print(f"  ✗ @{h} not found")
            except XAPIError as e:
                print(f"  ✗ @{h} {e}")

        if not seed_users:
            return {}, {}

        # Cost estimate + confirmation
        total_est = sum(
            min(u.get("public_metrics", {}).get("following_count", 500), MAX_FOLLOWING_PER_SEED)
            for u in seed_users.values()
        )
        print(f"\n  Estimated API cost: ~${total_est * COST_PER_USER:.2f}  ({total_est:,} max users)")
        try:
            input("  Press Enter to fetch, Ctrl+C to abort… ")
        except KeyboardInterrupt:
            print("\n  Aborted.")
            sys.exit(0)

        # Fetch /following and persist
        for handle, user in seed_users.items():
            try:
                print(f"  @{handle:<22} fetching /following…", end=" ", flush=True)
                raw = await x.get_following(user["id"], max_total=MAX_FOLLOWING_PER_SEED)
                followed_handles = {f["username"].lower() for f in raw}
                followings[handle] = followed_handles
                print(f"got {len(followed_handles)}")

                # Upsert follower into users
                m = user.get("public_metrics", {})
                c.table("users").upsert({
                    "handle": handle,
                    "x_id": user.get("id"),
                    "name": user.get("name"),
                    "bio": user.get("description"),
                    "followers_count": m.get("followers_count"),
                    "following_count": m.get("following_count"),
                    "source": "custom_seed_import",
                }, on_conflict="handle").execute()

                # Upsert followees into users (minimal profile)
                followee_rows = [
                    {
                        "handle": f["username"].lower(),
                        "x_id": f.get("id"),
                        "name": f.get("name"),
                        "bio": f.get("description"),
                        "followers_count": f.get("public_metrics", {}).get("followers_count"),
                        "following_count": f.get("public_metrics", {}).get("following_count"),
                        "source": "custom_seed_followee",
                    }
                    for f in raw
                ]
                for i in range(0, len(followee_rows), 100):
                    c.table("users").upsert(
                        followee_rows[i:i+100], on_conflict="handle"
                    ).execute()

                # Upsert follow edges
                follow_rows = [
                    {"follower_handle": handle, "followee_handle": f["username"].lower(), "source": "custom_seed_import"}
                    for f in raw
                ]
                for i in range(0, len(follow_rows), 100):
                    c.table("follows").upsert(
                        follow_rows[i:i+100], on_conflict="follower_handle,followee_handle"
                    ).execute()

                profiles[handle] = {
                    "name": user.get("name", handle),
                    "bio": user.get("description", ""),
                    "followers_count": m.get("followers_count", 0),
                    "following_count": m.get("following_count", 0),
                }
            except XAPIError as e:
                print(f"ERROR: {e}")
                followings[handle] = set()

    return followings, profiles


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(
    seed_handles: list[str],
    seed_profiles: dict[str, dict],         # handle → profile dict
    all_followings: dict[str, set[str]],    # handle → set of followee handles (from Supabase + API)
    mutual_seed_pairs: list[tuple[str, str]],  # already-confirmed seed↔seed mutuals
    confirmed_hubs: set[str],               # hubs confirmed mutual with ≥1 seed
    hub_counts: dict[str, int],             # all hub candidates with co-follow count
) -> dict:
    seed_set = set(seed_handles)

    # Seed↔seed edges
    edges: list[dict] = []
    confirmed_pairs = {(a, b) for a, b in mutual_seed_pairs}
    for a, b in mutual_seed_pairs:
        edges.append({"source": a, "target": b, "tier": 1, "type": "mutual", "kind": "confirmed"})

    # One-way seed↔seed edges (seed follows another seed but not mutual)
    for s in seed_handles:
        for other in seed_handles:
            if s == other:
                continue
            if (s, other) in confirmed_pairs or (other, s) in confirmed_pairs:
                continue
            if other in all_followings.get(s, set()):
                edges.append({"source": s, "target": other, "tier": 2, "type": "oneway", "kind": "one_way"})

    # Hub nodes
    top_hubs = sorted(hub_counts.items(), key=lambda x: x[1], reverse=True)[:HUB_MAX_SHOW]
    hub_set = {h for h, _ in top_hubs}

    # Seed→hub edges (T2 one-way; T1 if hub is confirmed mutual)
    for seed in seed_handles:
        for hub_handle in hub_set:
            if hub_handle in all_followings.get(seed, set()):
                tier = 1 if hub_handle in confirmed_hubs else 2
                kind = "confirmed" if hub_handle in confirmed_hubs else "seed_to_hub"
                edges.append({"source": seed, "target": hub_handle, "tier": tier, "type": "mutual" if tier == 1 else "oneway", "kind": kind})

    # Nodes
    nodes: list[dict] = []
    for handle in seed_handles:
        prof = seed_profiles.get(handle, {})
        t1_count = sum(1 for a, b in confirmed_pairs if a == handle or b == handle)
        t1_count += sum(1 for h in confirmed_hubs if h in all_followings.get(handle, set()))
        nodes.append({
            "id": handle,
            "label": handle,
            "name": prof.get("name", handle),
            "description": prof.get("bio", ""),
            "followers_count": prof.get("followers_count", 0),
            "following_count": prof.get("following_count", 0),
            "is_mutual_member": True,
            "is_celebrity_outbound": False,
            "is_bridge": t1_count >= 2,
            "type": "anchor",
            "t1_mutual_count": t1_count,
            "cluster": 0,
            "circles": ["Custom Seeds"],
            "tier": prof.get("tier") or _tier(prof.get("followers_count", 0)),
            "in_graph": True,
            "pagerank": None,
            "betweenness": None,
        })

    for hub_handle, count in top_hubs:
        is_confirmed = hub_handle in confirmed_hubs
        nodes.append({
            "id": hub_handle,
            "label": hub_handle,
            "name": hub_handle,
            "is_mutual_member": is_confirmed,
            "is_celebrity_outbound": False,
            "is_bridge": False,
            "type": "hub",
            "anchor_count": count,
            "in_graph": True,
            "cluster": 0 if is_confirmed else None,
            "circles": ["Custom Seeds"] if is_confirmed else [],
            "tier": None,
            "pagerank": None,
            "betweenness": None,
        })

    mutual_count = sum(1 for e in edges if e["tier"] == 1)
    oneway_count = sum(1 for e in edges if e["tier"] == 2)
    total_fetched = sum(len(f) for f in all_followings.values())

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "source": "custom_seeds",
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "mutual_members": len(seed_handles) + len(confirmed_hubs),
            "watched_nodes": len(top_hubs) - len(confirmed_hubs),
            "celebrity_filtered": 0,
            "connected_clusters": 1,
            "clusters_found": 1,
            "isolated_nodes": 0,
            "cluster_summary": [{
                "cluster_id": 0,
                "size": len(seed_handles),
                "members": seed_handles,
                "recommended_entry_point": f"@{seed_handles[0]}",
                "bridge_nodes": [n["id"] for n in nodes if n.get("is_bridge")][:3],
                "circles_touched": ["Custom Seeds"],
            }],
            "top_pagerank": [],
            "top_betweenness": [],
            "edge_breakdown": {
                "tier_1_mutual": mutual_count,
                "tier_2a_oneway_anchor": oneway_count,
                "tier_2b_anchor_to_hub": 0,
                "tier_2c_anchor_to_peripheral": 0,
                "tier_3_cofollow_inferred": 0,
                "tier_3b_peripheral_cofollow": 0,
            },
            "input_data": {
                "circles": 1,
                "anchors_from_circles": len(seed_handles),
                "total_raw_following_records_analyzed": total_fetched,
                "cost_usd_total": round(total_fetched * COST_PER_USER, 2),
            },
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a mutual-follow graph from custom seed handles. Uses Supabase cache first."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--handles", help="Comma-separated handles (no @ needed)")
    group.add_argument("--input", metavar="FILE", help="Text file with one handle per line")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Output path (default: frontend graph.json)")
    args = parser.parse_args()

    text = args.handles if args.handles else Path(args.input).read_text()
    handles = parse_handles(text)

    if len(handles) < MIN_SEEDS:
        print(f"Error: need ≥{MIN_SEEDS} valid handles, got {len(handles)}")
        return 1
    if len(handles) > MAX_SEEDS:
        print(f"Warning: capping at {MAX_SEEDS} (got {len(handles)})")
        handles = handles[:MAX_SEEDS]

    print(f"\n{'='*55}")
    print(f"  Custom Seed Pipeline")
    print(f"  Seeds ({len(handles)}): {', '.join('@'+h for h in handles)}")
    print(f"{'='*55}")

    # ── Step 1: Check Supabase cache ──────────────────────────
    print("\n[1/4] Checking Supabase cache…")
    cached_followings = load_cached_following(handles)
    cached_seeds = set(cached_followings.keys())
    missing_seeds = [h for h in handles if h not in cached_seeds]

    if cached_seeds:
        print(f"  ✓ Cached ({len(cached_seeds)}): {', '.join(sorted(cached_seeds))}")
    if missing_seeds:
        print(f"  ✗ Not cached ({len(missing_seeds)}): {', '.join(missing_seeds)}")
    else:
        print(f"  All seeds cached — no X API calls needed!")

    # Load profiles from Supabase
    seed_profiles = load_seed_profiles(handles)

    # ── Step 2: Fetch missing seeds from X API ────────────────
    api_followings: dict[str, set[str]] = {}
    api_profiles: dict[str, dict] = {}
    if missing_seeds:
        print(f"\n[2/4] Fetching {len(missing_seeds)} uncached seeds from X API…")
        api_followings, api_profiles = await fetch_and_save_seeds(missing_seeds)
        seed_profiles.update(api_profiles)
    else:
        print(f"\n[2/4] Skipped — all seeds cached.")

    # Merge followings
    all_followings = {**cached_followings, **api_followings}
    available_seeds = [h for h in handles if h in all_followings]

    if len(available_seeds) < MIN_SEEDS:
        print(f"\nError: only {len(available_seeds)} seeds have following data. Need ≥{MIN_SEEDS}.")
        return 1

    # ── Step 3: Build hub candidates from Supabase ───────────
    print(f"\n[3/4] Computing hub candidates from {sum(len(f) for f in all_followings.values()):,} follow edges…")
    seed_set = set(available_seeds)
    co_follow: Counter[str] = Counter()
    for seed in available_seeds:
        for followee in all_followings[seed]:
            if followee not in seed_set:
                co_follow[followee] += 1
    hub_counts = {h: c for h, c in co_follow.items() if c >= HUB_MIN_ANCHORS}
    print(f"  {len(hub_counts)} hub candidates (followed by ≥{HUB_MIN_ANCHORS} seeds)")

    # ── Step 4: Mutual verification ──────────────────────────
    print(f"\n[4/4] Verifying mutual follows…")

    # Seed↔seed mutual from mutual_follows view
    mutual_pairs = query_mutual_follows(available_seeds)
    print(f"  {len(mutual_pairs)} mutual pairs among seeds (from Supabase)")

    # Hub mutual confirmation from follows table
    top_hub_handles = [h for h, _ in
                       sorted(hub_counts.items(), key=lambda x: x[1], reverse=True)[:HUB_MAX_SHOW]]
    confirmed_hubs = query_hub_mutual_confirmation(top_hub_handles, available_seeds)
    print(f"  {len(confirmed_hubs)} hubs confirmed mutual (Supabase cache)")

    # ── Build and write graph ─────────────────────────────────
    graph = build_graph(
        seed_handles=available_seeds,
        seed_profiles=seed_profiles,
        all_followings=all_followings,
        mutual_seed_pairs=mutual_pairs,
        confirmed_hubs=confirmed_hubs,
        hub_counts=hub_counts,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, indent=2, ensure_ascii=False))

    m = graph["metadata"]
    print(f"\n✓ Done → {out}")
    print(f"  {m['total_nodes']} nodes · {m['total_edges']} edges")
    print(f"  {m['edge_breakdown']['tier_1_mutual']} mutual (T1) · {m['edge_breakdown']['tier_2a_oneway_anchor']} one-way (T2)")
    print(f"  Actual API cost: ~${m['input_data']['cost_usd_total']:.2f}")
    print(f"\n  Refresh the web app → Network Graph shows your custom graph.")
    print(f"  Restore: git checkout kol-intelligence-engine/src/data/graph.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
