"""
Rebuild per-user network metrics from Supabase `follows` table.

Populates on `users` table:
- `t1_mutual_count`            — # of mutual-follow edges incident on this user
- `cross_cluster_mutual_count` — # of those mutual edges that cross cluster boundaries
- `bridge_ratio`               — cross_cluster_mutual_count / t1_mutual_count
- `cluster_id`                 — Louvain community in the mutual subgraph
- `pagerank`                   — PageRank in the mutual subgraph
- `betweenness`                — betweenness centrality in the mutual subgraph
- `graph_indexed_at`           — now()

**Critical design**: all centrality metrics (Louvain, PageRank, betweenness)
are computed on the MUTUAL SUBGRAPH only (where both A→B and B→A exist in
the `follows` table). One-way follows are deliberately excluded, because
celebrity bias (anchor → @justinsuntron without reciprocation) would
contaminate centrality otherwise.

Reads 4106 follow rows → computes 98 mutual edges → runs networkx →
upserts 28 user rows with non-null network fields. The other ~5,800 users
stay at defaults (t1_mutual_count=0, cluster_id=NULL).

Idempotent. Safe to re-run after new follows get added.

Run:
    pipeline/.venv/bin/python pipeline/rebuild_network_stats.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import get_client

try:
    import community as community_louvain
except ImportError:
    print("ERROR: install python-louvain first: pip install python-louvain")
    sys.exit(1)


def fetch_all_follows(sb) -> list[tuple[str, str]]:
    """Paginate through follows table to get every (follower, followee) pair."""
    all_rows: list[tuple[str, str]] = []
    page_size = 1000
    offset = 0
    while True:
        result = (
            sb.table("follows")
            .select("follower_handle,followee_handle")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        all_rows.extend((r["follower_handle"], r["followee_handle"]) for r in result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_rows


def compute_mutual_graph(follows: list[tuple[str, str]]) -> nx.Graph:
    """Build undirected mutual-follow graph: edge exists iff both directions present."""
    directed = set(follows)
    G = nx.Graph()
    seen_pair: set[tuple[str, str]] = set()
    for a, b in follows:
        if (b, a) not in directed:
            continue
        # canonical ordering so we don't add (a,b) and (b,a) twice
        u, v = sorted((a, b))
        if (u, v) in seen_pair:
            continue
        seen_pair.add((u, v))
        G.add_edge(u, v, weight=1.0)
    return G


def chunked(iterable, size):
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def main() -> int:
    print("=" * 72)
    print("Rebuild network stats on users table from follows table")
    print("=" * 72)

    sb = get_client()

    print("Fetching all follow edges...")
    follows = fetch_all_follows(sb)
    print(f"  → {len(follows)} directed follow rows")

    G = compute_mutual_graph(follows)
    print(f"  → mutual subgraph: {G.number_of_nodes()} nodes, {G.number_of_edges()} mutual edges")
    if G.number_of_edges() == 0:
        print("No mutual edges yet — nothing to compute.")
        return 0
    print()

    print("Running Louvain community detection on mutual subgraph...")
    partition = community_louvain.best_partition(G, random_state=42)
    n_clusters = len(set(partition.values()))
    print(f"  → {n_clusters} communities found")

    print("Running PageRank (weighted) on mutual subgraph...")
    pagerank = nx.pagerank(G, weight="weight")

    print("Running betweenness centrality on mutual subgraph...")
    betweenness = nx.betweenness_centrality(G, weight="weight")
    print()

    # Per-node: t1 count, cross-cluster count, bridge ratio
    per_node_stats: dict[str, dict] = {}
    for node in G.nodes():
        cluster_id = partition[node]
        t1_count = G.degree(node)
        cross_cluster = sum(
            1 for neighbor in G.neighbors(node)
            if partition.get(neighbor) != cluster_id
        )
        bridge_ratio = cross_cluster / t1_count if t1_count else 0.0
        per_node_stats[node] = {
            "cluster_id": int(cluster_id),
            "pagerank": round(float(pagerank.get(node, 0)), 6),
            "betweenness": round(float(betweenness.get(node, 0)), 6),
            "t1_mutual_count": int(t1_count),
            "cross_cluster_mutual_count": int(cross_cluster),
            "bridge_ratio": round(float(bridge_ratio), 4),
        }

    # Cluster size histogram
    cluster_sizes: dict[int, int] = defaultdict(int)
    for stats in per_node_stats.values():
        cluster_sizes[stats["cluster_id"]] += 1
    print("Cluster sizes:")
    for cid, size in sorted(cluster_sizes.items(), key=lambda x: -x[1]):
        print(f"  cluster {cid}: {size} members")
    print()

    # Top 10 by PageRank for sanity check
    print("Top 10 by PageRank in mutual subgraph:")
    top = sorted(per_node_stats.items(), key=lambda x: -x[1]["pagerank"])[:10]
    for handle, stats in top:
        print(
            f"  @{handle:<24} cluster={stats['cluster_id']} "
            f"pr={stats['pagerank']:.4f} bc={stats['betweenness']:.4f} "
            f"t1={stats['t1_mutual_count']} cross={stats['cross_cluster_mutual_count']}"
        )
    print()

    # Write back to users table
    print(f"Writing {len(per_node_stats)} rows to users table...")
    now_iso = datetime.now(timezone.utc).isoformat()
    updates = []
    for handle, stats in per_node_stats.items():
        updates.append(
            {
                "handle": handle,
                **stats,
                "graph_indexed_at": now_iso,
            }
        )

    # Supabase upsert (on_conflict=handle). Must not overwrite other fields.
    upserted = 0
    for batch in chunked(updates, 100):
        result = sb.table("users").upsert(batch, on_conflict="handle").execute()
        upserted += len(result.data)
    print(f"  → upserted {upserted} users")
    print()

    # Reset rows that were previously in the graph but aren't anymore
    # (safety net — unlikely in our pipeline but cheap insurance)
    indexed_handles = list(per_node_stats.keys())
    stale = sb.table("users").select("handle").not_.is_("graph_indexed_at", "null").not_.in_(
        "handle", indexed_handles
    ).execute()
    stale_count_checked = len(stale.data) if stale.data else 0
    if stale.data:
        stale_handles = [r["handle"] for r in stale.data]
        print(f"Resetting {len(stale_handles)} stale entries (were in graph, now aren't)...")
        reset = [
            {
                "handle": h,
                "t1_mutual_count": 0,
                "cross_cluster_mutual_count": 0,
                "bridge_ratio": 0.0,
                "cluster_id": None,
                "pagerank": None,
                "betweenness": None,
                "graph_indexed_at": None,
            }
            for h in stale_handles
        ]
        for batch in chunked(reset, 100):
            sb.table("users").upsert(batch, on_conflict="handle").execute()
    else:
        print("No stale entries to reset.")
    print()
    print("=" * 72)
    print(f"Done. Mutual subgraph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {n_clusters} clusters.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
