"""
Import Your Own Seeds — custom pipeline runner.

Takes a list of KOL handles, fetches their /following lists via X API v2,
computes the mutual-follow matrix, finds hub candidates, and writes a
graph.json compatible with the React frontend.

Usage:
    python pipeline/run_custom_seeds.py --handles shawmakesmagic,punk3700,0xwitchy
    python pipeline/run_custom_seeds.py --input my_seeds.txt
    python pipeline/run_custom_seeds.py --input my_seeds.txt --output custom_graph.json

Default output overwrites kol-intelligence-engine/src/data/graph.json so the
web app shows your custom graph on refresh. Use --output to write elsewhere.

Cost: ~$0.0088 per user returned from /following. A seed with 800 followings
costs ~$7. Check estimated cost printed before API calls start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from x_client import XClient, XAPIError  # noqa: E402

DEFAULT_OUTPUT = ROOT / "kol-intelligence-engine" / "src" / "data" / "graph.json"
MAX_FOLLOWING_PER_SEED = 1000
MIN_SEEDS = 3
MAX_SEEDS = 20
COST_PER_USER = 0.0088
HUB_MIN_SEEDS = 2      # account must be followed by ≥N seeds to be a hub candidate
HUB_MAX_SHOW = 300     # cap watched nodes in output


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_handles(text: str) -> list[str]:
    handles = []
    for part in re.split(r"[\n,\s]+", text):
        h = part.strip().lstrip("@").lower()
        if h and re.match(r"^[a-z0-9_]{1,15}$", h):
            handles.append(h)
    # dedupe preserving order
    seen: set[str] = set()
    return [h for h in handles if not (h in seen or seen.add(h))]  # type: ignore[func-returns-value]


# ---------------------------------------------------------------------------
# X API calls
# ---------------------------------------------------------------------------

async def resolve_handles(x: XClient, handles: list[str]) -> dict[str, dict]:
    print(f"\n[1/3] Resolving {len(handles)} handles → user IDs…")
    resolved: dict[str, dict] = {}
    for h in handles:
        try:
            user = await x.get_user_by_username(h)
            if user:
                resolved[h] = user
                m = user.get("public_metrics", {})
                print(f"  ✓ @{h:<22} id={user['id']}  followers={m.get('followers_count', 0):>8,}")
            else:
                print(f"  ✗ @{h:<22} not found")
        except XAPIError as e:
            print(f"  ✗ @{h:<22} {e}")
    print(f"  Resolved {len(resolved)}/{len(handles)}")
    return resolved


async def fetch_followings(
    x: XClient, seed_users: dict[str, dict]
) -> dict[str, set[str]]:
    print(f"\n[2/3] Fetching /following for {len(seed_users)} seeds…")
    # Print cost estimate first
    total_est = sum(
        min(u.get("public_metrics", {}).get("following_count", 500), MAX_FOLLOWING_PER_SEED)
        for u in seed_users.values()
    )
    print(f"  Estimated cost: ~${total_est * COST_PER_USER:.2f}  ({total_est:,} max users returned)")
    input("  Press Enter to continue, Ctrl+C to abort… ")

    followings: dict[str, set[str]] = {}
    for handle, user in seed_users.items():
        try:
            print(f"  @{handle:<22} fetching…", end=" ", flush=True)
            raw = await x.get_following(user["id"], max_total=MAX_FOLLOWING_PER_SEED)
            followed = {f["username"].lower() for f in raw}
            followings[handle] = followed
            print(f"got {len(followed)}")
        except XAPIError as e:
            print(f"ERROR: {e}")
            followings[handle] = set()
    return followings


# ---------------------------------------------------------------------------
# Graph computation
# ---------------------------------------------------------------------------

def compute_edges(
    seed_handles: list[str], followings: dict[str, set[str]]
) -> list[dict]:
    """Mutual-follow edges between seeds only (T1 = mutual, T2 = one-way)."""
    edges = []
    for i, a in enumerate(seed_handles):
        for b in seed_handles[i + 1 :]:
            a_to_b = b in followings.get(a, set())
            b_to_a = a in followings.get(b, set())
            if a_to_b and b_to_a:
                edges.append({"source": a, "target": b, "tier": 1, "type": "mutual", "kind": "confirmed"})
            elif a_to_b:
                edges.append({"source": a, "target": b, "tier": 2, "type": "oneway", "kind": "one_way"})
            elif b_to_a:
                edges.append({"source": b, "target": a, "tier": 2, "type": "oneway", "kind": "one_way"})
    return edges


def find_hub_candidates(
    seed_handles: set[str], followings: dict[str, set[str]]
) -> dict[str, int]:
    """Accounts followed by ≥HUB_MIN_SEEDS seeds (not seeds themselves)."""
    counts: dict[str, int] = defaultdict(int)
    for seed, followed in followings.items():
        for candidate in followed:
            if candidate not in seed_handles:
                counts[candidate] += 1
    return {h: c for h, c in counts.items() if c >= HUB_MIN_SEEDS}


def _tier(followers: int) -> str:
    if followers >= 100_000:
        return "Mega"
    if followers >= 10_000:
        return "Macro"
    if followers >= 1_000:
        return "Micro"
    return "Nano"


def build_graph(
    seed_users: dict[str, dict],
    followings: dict[str, set[str]],
    seed_edges: list[dict],
) -> dict:
    seed_handles = set(seed_users.keys())
    hubs = find_hub_candidates(seed_handles, followings)
    # sort hubs by co-follow count desc, cap output
    top_hubs = sorted(hubs.items(), key=lambda x: x[1], reverse=True)[:HUB_MAX_SHOW]

    mutual_pairs: set[tuple[str, str]] = {
        (e["source"], e["target"]) for e in seed_edges if e["tier"] == 1
    }

    # --- Nodes ---
    nodes = []
    for handle, user in seed_users.items():
        m = user.get("public_metrics", {})
        t1 = sum(1 for a, b in mutual_pairs if a == handle or b == handle)
        nodes.append({
            "id": handle,
            "label": handle,
            "name": user.get("name", handle),
            "description": user.get("description", ""),
            "followers_count": m.get("followers_count", 0),
            "following_count": m.get("following_count", 0),
            "is_mutual_member": True,
            "is_celebrity_outbound": False,
            "is_bridge": t1 >= 2,
            "type": "anchor",
            "t1_mutual_count": t1,
            "cluster": 0,
            "circles": ["Custom Seeds"],
            "tier": _tier(m.get("followers_count", 0)),
            "in_graph": True,
            "pagerank": None,
            "betweenness": None,
        })

    for handle, count in top_hubs:
        nodes.append({
            "id": handle,
            "label": handle,
            "name": handle,
            "is_mutual_member": False,
            "is_celebrity_outbound": False,
            "is_bridge": False,
            "type": "hub",
            "anchor_count": count,
            "in_graph": True,
            "cluster": None,
            "circles": [],
            "tier": None,
            "pagerank": None,
            "betweenness": None,
        })

    # --- Edges: seed-to-seed + seed-to-hub (T2) ---
    all_edges = list(seed_edges)
    hub_handles = {h for h, _ in top_hubs}
    for seed in seed_handles:
        for candidate in followings.get(seed, set()):
            if candidate in hub_handles:
                all_edges.append({
                    "source": seed,
                    "target": candidate,
                    "tier": 2,
                    "type": "oneway",
                    "kind": "seed_to_hub",
                })

    mutual_count = sum(1 for e in all_edges if e["tier"] == 1)
    oneway_count = sum(1 for e in all_edges if e["tier"] == 2)
    total_followed = sum(len(f) for f in followings.values())

    return {
        "nodes": nodes,
        "edges": all_edges,
        "metadata": {
            "source": "custom_seeds",
            "total_nodes": len(nodes),
            "total_edges": len(all_edges),
            "mutual_members": len(seed_users),
            "watched_nodes": len(top_hubs),
            "celebrity_filtered": 0,
            "connected_clusters": 1,
            "clusters_found": 1,
            "isolated_nodes": 0,
            "cluster_summary": [{
                "cluster_id": 0,
                "size": len(seed_users),
                "members": list(seed_users.keys()),
                "recommended_entry_point": f"@{list(seed_users.keys())[0]}",
                "bridge_nodes": [f"@{h}" for h, t1 in
                                 [(n["id"], n["t1_mutual_count"]) for n in nodes if n["is_mutual_member"]]
                                 if t1 >= 2][:3],
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
                "anchors_from_circles": len(seed_users),
                "total_raw_following_records_analyzed": total_followed,
                "cost_usd_total": round(total_followed * COST_PER_USER, 2),
            },
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a mutual-follow graph from custom seed handles."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--handles", help="Comma-separated handles (no @ needed)")
    group.add_argument("--input", metavar="FILE", help="Text file with handles, one per line")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    text = args.handles if args.handles else Path(args.input).read_text()
    handles = parse_handles(text)

    if len(handles) < MIN_SEEDS:
        print(f"Error: need at least {MIN_SEEDS} valid handles, got {len(handles)}")
        return 1
    if len(handles) > MAX_SEEDS:
        print(f"Warning: capping at {MAX_SEEDS} seeds (got {len(handles)}), using first {MAX_SEEDS}")
        handles = handles[:MAX_SEEDS]

    print(f"\n{'='*50}")
    print(f"  Custom Seed Pipeline")
    print(f"  Seeds ({len(handles)}): {', '.join('@' + h for h in handles)}")
    print(f"{'='*50}")

    async with XClient() as x:
        seed_users = await resolve_handles(x, handles)
        if len(seed_users) < MIN_SEEDS:
            print(f"\nError: only {len(seed_users)} handles resolved. Need at least {MIN_SEEDS}.")
            return 1

        followings = await fetch_followings(x, seed_users)

    print(f"\n[3/3] Computing graph…")
    edges = compute_edges(list(seed_users.keys()), followings)
    graph = build_graph(seed_users, followings, edges)

    mutual = graph["metadata"]["edge_breakdown"]["tier_1_mutual"]
    hubs = graph["metadata"]["watched_nodes"]
    cost = graph["metadata"]["input_data"]["cost_usd_total"]
    print(f"  {mutual} mutual pairs · {hubs} hub candidates · actual cost ~${cost:.2f}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, indent=2, ensure_ascii=False))

    print(f"\n✓ Written to {out}")
    print(f"  Refresh the web app → Network Graph page shows your custom graph.")
    if str(out) == str(DEFAULT_OUTPUT):
        print(f"  (restore original: git checkout kol-intelligence-engine/src/data/graph.json)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
