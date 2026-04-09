"""
Export Supabase `follows` + `users` → `kol-intelligence-engine/src/data/graph.json`.

Replaces the JSON-file-based `pipeline/build_graph.py` flow. Supabase is now
the source of truth; this script just reads from it and produces the
graph.json shape the React demo expects.

Design:
- Nodes = all scoring-ready KOLs (is_real_human + is_ai_crypto_focused)
  + flagged mutual_member status from `t1_mutual_count > 0`
  + flagged celebrity_outbound status from followers vs anchor median × 5
- Edges = rows from follows table, classified into tiers:
    T1 (tier=1, solid) = mutual follows (both directions present)
    T2 (tier=2, dashed) = one-way follows (only one direction)
    T3 (tier=3, dotted) = SKIPPED — co-follow inferred, no longer produced
      (we only store real follows in Supabase, not inferred edges)

Metadata includes:
- node breakdown (mutual_members / watched / celebrity_filtered)
- edge tier breakdown
- cluster_summary (derived from users.cluster_id for mutual members only)
- top_pagerank / top_betweenness from users table
- input_data (provenance info)

Run:
    pipeline/.venv/bin/python scoring/export_graph_json.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.db import get_client

OUTPUT_FILE = ROOT / "kol-intelligence-engine" / "src" / "data" / "graph.json"

# Celebrity threshold constants (match build_graph.py v3.5)
CELEB_MEDIAN_MULTIPLIER = 5
CELEB_MAX_MULTIPLIER = 2
CELEB_AUDIENCE_CUTOFF = 250_000
CELEB_SMALL_AUDIENCE_ANCHOR_CAP = 5


def fetch_users(sb) -> list[dict]:
    """Fetch all scoring-ready KOLs (paginated)."""
    rows = []
    offset = 0
    page = 1000
    while True:
        r = (
            sb.table("users")
            .select(
                "handle, x_id, name, bio, followers_count, following_count, tweet_count, "
                "verified, tier, sector, language, region, is_anchor, "
                "cooperability, outreach_angle, estimated_price_tier, "
                "cluster_id, pagerank, betweenness, t1_mutual_count, "
                "cross_cluster_mutual_count, bridge_ratio, "
                "quality_score, cooperability_score, source"
            )
            .eq("is_real_human", True)
            .eq("is_ai_crypto_focused", True)
            .range(offset, offset + page - 1)
            .execute()
        )
        if not r.data:
            break
        rows.extend(r.data)
        if len(r.data) < page:
            break
        offset += page
    return rows


def fetch_follows(sb, handles: set[str]) -> list[tuple[str, str]]:
    """Fetch all follow edges where both endpoints are in our user set."""
    rows = []
    offset = 0
    page = 1000
    while True:
        r = (
            sb.table("follows")
            .select("follower_handle,followee_handle")
            .range(offset, offset + page - 1)
            .execute()
        )
        if not r.data:
            break
        rows.extend(
            (row["follower_handle"], row["followee_handle"])
            for row in r.data
            if row["follower_handle"] in handles and row["followee_handle"] in handles
        )
        if len(r.data) < page:
            break
        offset += page
    return rows


def compute_celebrity_threshold(users: list[dict]) -> tuple[float, float]:
    """Compute celebrity cutoffs the same way build_graph.py used to."""
    anchor_fc = [
        u.get("followers_count") or 0
        for u in users
        if u.get("is_anchor") and (u.get("followers_count") or 0) > 0
    ]
    if not anchor_fc:
        return 500_000, 1_000_000
    median_af = statistics.median(anchor_fc)
    max_af = max(anchor_fc)
    celeb_threshold = max(
        CELEB_MEDIAN_MULTIPLIER * median_af,
        CELEB_MAX_MULTIPLIER * max_af,
        CELEB_AUDIENCE_CUTOFF,
    )
    return celeb_threshold, median_af


def classify_celebrity(user: dict, threshold: float, median_af: float) -> bool:
    fc = user.get("followers_count") or 0
    if fc >= threshold:
        return True
    t1 = user.get("t1_mutual_count") or 0
    if fc >= CELEB_AUDIENCE_CUTOFF and t1 <= CELEB_SMALL_AUDIENCE_ANCHOR_CAP:
        return True
    return False


def derive_circles_from_source(source: str | None) -> list[str]:
    if not source:
        return []
    s = source.lower()
    circles = []
    if "virtuals" in s:
        circles.append("C1")
    if "xhunt" in s or "biteye" in s:
        circles.append("C2")
    if "chinese_crypto_analysis" in s:
        circles.append("C3")
    return circles


def main() -> int:
    print("=" * 72)
    print("Export Supabase → graph.json")
    print("=" * 72)

    sb = get_client()

    print("Fetching users...")
    users = fetch_users(sb)
    print(f"  → {len(users)} scoring-ready users")

    celeb_threshold, median_af = compute_celebrity_threshold(users)
    print(f"Celebrity threshold: {celeb_threshold:,.0f} followers (median anchor = {median_af:,.0f})")

    handle_set = {u["handle"] for u in users}
    print("Fetching follows...")
    follows = fetch_follows(sb, handle_set)
    print(f"  → {len(follows)} follow edges (both endpoints scoring-ready)")

    # Directed edge set for mutual detection
    directed = set(follows)

    # Classify edges into tiers
    t1_edges = []
    t2_edges = []
    seen_mutual: set[tuple[str, str]] = set()

    for a, b in follows:
        if (b, a) in directed:
            # mutual — emit once with canonical ordering
            u, v = sorted((a, b))
            if (u, v) in seen_mutual:
                continue
            seen_mutual.add((u, v))
            t1_edges.append({"source": u, "target": v, "tier": 1, "type": "mutual_follow"})
        else:
            # one-way
            t2_edges.append(
                {
                    "source": a,
                    "target": b,
                    "tier": 2,
                    "type": "one_way_follow",
                    "directed": True,
                }
            )

    print(f"  → T1 mutual: {len(t1_edges)}, T2 one-way: {len(t2_edges)}")

    # Build node objects
    nodes = []
    mutual_count = 0
    celeb_count = 0
    watched_count = 0
    anchor_count = 0

    for u in users:
        handle = u["handle"]
        t1 = u.get("t1_mutual_count") or 0
        is_mutual = t1 > 0
        is_celeb = classify_celebrity(u, celeb_threshold, median_af)

        if u.get("is_anchor"):
            type_label = "anchor"
            anchor_count += 1
        elif is_mutual:
            type_label = "mutual_hub"
        else:
            type_label = "watched"

        if is_mutual:
            mutual_count += 1
        else:
            watched_count += 1
        if is_celeb:
            celeb_count += 1

        circles = derive_circles_from_source(u.get("source"))
        is_bridge = (u.get("cross_cluster_mutual_count") or 0) > 0

        nodes.append(
            {
                "id": handle,
                "label": "@" + handle,
                "type": type_label,
                "name": u.get("name"),
                "description": (u.get("bio") or "")[:200],
                "followers_count": u.get("followers_count") or 0,
                "following_count": u.get("following_count") or 0,
                "verified": u.get("verified", False),
                "x_id": u.get("x_id"),
                "tier": u.get("tier"),
                "sector": u.get("sector"),
                "language": u.get("language"),
                "region": u.get("region"),
                "circles": circles,
                "primary_circle": circles[0] if circles else None,
                "cluster": u.get("cluster_id"),
                "pagerank": u.get("pagerank"),
                "betweenness": u.get("betweenness"),
                "t1_mutual_count": t1,
                "cross_cluster_mutual_count": u.get("cross_cluster_mutual_count") or 0,
                "bridge_ratio": u.get("bridge_ratio") or 0.0,
                "is_bridge": is_bridge,
                "is_mutual_member": is_mutual,
                "is_celebrity_outbound": is_celeb,
                "overall_score": u.get("quality_score"),  # legacy alias
                "quality_score": u.get("quality_score"),
                "cooperability_score": u.get("cooperability_score"),
                "cooperability": u.get("cooperability"),
                "outreach_angle": u.get("outreach_angle"),
                "estimated_price_tier": u.get("estimated_price_tier"),
            }
        )

    # Cluster summary (mutual subgraph only)
    cluster_members: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        if n["is_mutual_member"] and n["cluster"] is not None:
            cluster_members[n["cluster"]].append(n["id"])

    cluster_summary = []
    for cid, members in sorted(cluster_members.items(), key=lambda x: -len(x[1])):
        if len(members) < 3:
            continue
        top_pr = sorted(
            members,
            key=lambda h: -(next((n["pagerank"] or 0 for n in nodes if n["id"] == h), 0)),
        )[:3]
        top_bc = sorted(
            members,
            key=lambda h: -(next((n["betweenness"] or 0 for n in nodes if n["id"] == h), 0)),
        )[:2]
        circles_touched = set()
        for m in members:
            for nn in nodes:
                if nn["id"] == m:
                    circles_touched.update(nn["circles"])
                    break
        cluster_summary.append(
            {
                "cluster_id": cid,
                "size": len(members),
                "members": members,
                "recommended_entry_point": "@" + top_pr[0] if top_pr else None,
                "bridge_nodes": ["@" + h for h in top_bc],
                "circles_touched": sorted(circles_touched),
            }
        )

    # Top 10 by PageRank (mutual only)
    mutual_nodes = [n for n in nodes if n["is_mutual_member"] and n["pagerank"] is not None]
    top_pr = sorted(mutual_nodes, key=lambda n: -n["pagerank"])[:10]
    top_bc = sorted(mutual_nodes, key=lambda n: -(n["betweenness"] or 0))[:10]

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_nodes": len(nodes),
        "total_edges": len(t1_edges) + len(t2_edges),
        "node_breakdown": {
            "anchors": anchor_count,
            "mutual_members": mutual_count,
            "watched": watched_count - celeb_count,
            "celebrity_filtered": celeb_count,
        },
        "mutual_members": mutual_count,
        "watched_nodes": watched_count - celeb_count,
        "celebrity_filtered": celeb_count,
        "edge_breakdown": {
            "tier_1_mutual": len(t1_edges),
            "tier_2a_oneway_anchor": 0,
            "tier_2b_anchor_to_hub": 0,
            "tier_2c_anchor_to_peripheral": len(t2_edges),
            "tier_3_cofollow_inferred": 0,
            "tier_3b_peripheral_cofollow": 0,
        },
        "clusters_found": len(cluster_members),
        "connected_clusters": len(cluster_summary),
        "isolated_nodes": sum(1 for n in nodes if not n["is_mutual_member"]),
        "cluster_summary": cluster_summary,
        "top_pagerank": [
            {"id": n["id"], "pagerank": n["pagerank"]} for n in top_pr
        ],
        "top_betweenness": [
            {"id": n["id"], "betweenness": n["betweenness"] or 0} for n in top_bc
        ],
        "input_data": {
            "circles": 3,
            "anchors_from_circles": anchor_count,
            "total_raw_following_records_analyzed": 13217,
            "cost_usd_total": 94.39,  # hub_verify_total_so_far
        },
    }

    doc = {
        "metadata": metadata,
        "nodes": nodes,
        "edges": t1_edges + t2_edges,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    print()
    print(f"✅ Wrote {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size / 1024:.0f} KB)")
    print()
    print(f"Nodes:            {len(nodes)}")
    print(f"  anchors:        {anchor_count}")
    print(f"  mutual members: {mutual_count}")
    print(f"  watched:        {watched_count - celeb_count}")
    print(f"  celeb-filtered: {celeb_count}")
    print(f"Edges:            {len(t1_edges) + len(t2_edges)}")
    print(f"  T1 mutual:      {len(t1_edges)}")
    print(f"  T2 one-way:     {len(t2_edges)}")
    print(f"Clusters (≥3):    {len(cluster_summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
