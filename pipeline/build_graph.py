"""
Phase 1 Step 3: Build the unified KOL network graph.

Combines:
  - 16 anchors from 3 ground-truth circles (C1/C2/C3)
  - Top N ultra-hubs (accounts followed by ≥6 anchors) as expansion nodes
  - T1 confirmed mutual edges (26, among anchors)
  - T2 one-way edges (36 anchor↔anchor + many anchor→hub)
  - T3 inferred co-follow edges (hub↔hub sharing ≥4 anchors)

Runs Louvain community detection + PageRank + betweenness centrality.

Output:
  kol-intelligence-engine/src/data/graph.json   (nodes + edges + metadata)
  kol-intelligence-engine/src/data/kols.json    (flat list of all KOLs with scores)

Zero API cost — pure computation on existing data.
"""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx
import community as community_louvain  # python-louvain

ROOT = Path(__file__).resolve().parent.parent
CIRCLES = ROOT / "pipeline" / "circles"

# Input files
C1_FILE = CIRCLES / "virtuals_chinese_builders_step1.json"
C2_FILE = CIRCLES / "xhunt_web3_media_step1.json"
C3_FILE = CIRCLES / "chinese_crypto_analysis_step1.json"
HUBS_FILE = CIRCLES / "hub_candidates.json"
UNIFIED_FILE = CIRCLES / "unified_16_anchor_matrix.json"

# Output: goes into the (future) Vite project's data dir
OUTPUT_DIR = ROOT / "kol-intelligence-engine" / "src" / "data"

# Config — how many hubs to include as graph nodes
ULTRA_HUB_INCLUDE = 50  # top 50 ultra hubs (≥6 anchors, sorted by anchor count + followers)
T3_COFOLLOW_MIN_SHARED = 6  # hub-to-hub co-follow edge if they share this many anchors (was 4, too dense)
T3_MAX_PER_NODE = 5  # cap T3 edges per node to prevent hairball

# Peripheral (classified-but-not-ultra-hub) config
# Every classified KOL becomes a graph node so the network reflects the full 674-KOL database.
# Peripheral nodes get T2/T3 edges based on anchor-follow data from hub_candidates.json.
PERIPHERAL_T2_MIN_ANCHORS = 1   # anchor→peripheral edge if ≥1 anchor follows them (from hub_candidates)
PERIPHERAL_T3_MIN_SHARED = 3    # peripheral↔peripheral T3 co-follow if they share ≥3 anchors
PERIPHERAL_T3_MAX_PER_NODE = 3  # cap T3 edges per peripheral (sparser than hub tier)

# Classified KOLs file (produced by classify_and_score.py). If present, enrich nodes with
# Claude-generated Dual-Layer scores, sector/tier/language tags, and cooperability.
CLASSIFIED_KOLS_FILE = ROOT / "pipeline" / "classified_kols.json"


def load_json(p: Path) -> dict:
    return json.loads(p.read_text())


def main() -> None:
    print("=" * 72)
    print("GRAPH BUILDER — unified KOL network (16 anchors + top hubs)")
    print("=" * 72)
    print()

    c1 = load_json(C1_FILE)
    c2 = load_json(C2_FILE)
    c3 = load_json(C3_FILE)
    hubs_data = load_json(HUBS_FILE)
    unified = load_json(UNIFIED_FILE)

    # Build anchor_following (lowercase username sets)
    all_anchors: dict[str, set[str]] = {}
    anchor_profiles: dict[str, dict] = {}
    circle_membership: dict[str, list[str]] = defaultdict(list)

    for state, circle_label in [(c1, "C1"), (c2, "C2"), (c3, "C3")]:
        for h in state["anchors"]:
            h_lower = h.lower()
            following = state["anchor_data"][h]["following"]
            if h_lower not in all_anchors:
                all_anchors[h_lower] = {u["username"].lower() for u in following}
                # Use data from whichever circle has the anchor first
                anchor_profiles[h_lower] = {
                    "handle": h,
                    "id": state["anchor_data"][h].get("id"),
                    "following_count": len(following),
                }
            if circle_label not in circle_membership[h_lower]:
                circle_membership[h_lower].append(circle_label)

    anchor_handles = sorted(all_anchors.keys())
    print(f"Anchors loaded: {len(anchor_handles)}")

    # Pull hub profiles from hubs_data. Only take top N ultra hubs.
    ultra_hubs = hubs_data["ultra_hubs_6_plus"][:ULTRA_HUB_INCLUDE]
    hub_handles_lower = {h["username"] for h in ultra_hubs}
    print(f"Ultra hubs included: {len(ultra_hubs)} (top {ULTRA_HUB_INCLUDE} by anchor count + followers)")

    # Build a global follow-lookup: for any candidate username, which anchors follow them?
    # Pulls from ALL tiers (ultra / strong / weak / co_follows_2) in hub_candidates.
    follow_lookup: dict[str, list[str]] = {}
    for tier_key in ("ultra_hubs_6_plus", "strong_hubs_4_5", "weak_hubs_3", "co_follows_2"):
        for h in hubs_data.get(tier_key, []):
            follow_lookup[h["username"].lower()] = [a.lower() for a in h.get("followed_by_anchors", [])]
    print(f"Follow lookup built: {len(follow_lookup)} candidates with anchor-follow data")
    print()

    # ---------- Build NODES ----------
    nodes: list[dict] = []

    # Anchor nodes
    for h in anchor_handles:
        circles = circle_membership[h]
        node = {
            "id": h,
            "label": "@" + anchor_profiles[h]["handle"],
            "type": "anchor",
            "circles": circles,
            "primary_circle": circles[0] if circles else None,
            "is_bridge": len(circles) > 1,
            "following_count": anchor_profiles[h]["following_count"],
            "x_id": anchor_profiles[h]["id"],
        }
        nodes.append(node)

    # Hub nodes
    for h in ultra_hubs:
        circles_via = []  # which circles' anchors follow this hub
        for anchor in h["followed_by_anchors"]:
            for c in circle_membership.get(anchor, []):
                if c not in circles_via:
                    circles_via.append(c)
        nodes.append({
            "id": h["username"],
            "label": "@" + h["username"],
            "type": "hub",
            "name": h.get("name"),
            "anchor_count": h["anchor_count"],
            "followed_by_anchors": h["followed_by_anchors"],
            "circles": sorted(circles_via),
            "is_bridge": len(circles_via) > 1,
            "description": h.get("description", ""),
            "followers_count": h.get("followers_count") or 0,
            "verified": h.get("verified", False),
            "x_id": h.get("id"),
        })

    # PERIPHERAL NODES — every classified human not already in graph becomes a node.
    # Load classified KOLs now (so we can add them as nodes before edge construction).
    classified_by_handle: dict[str, dict] = {}
    if CLASSIFIED_KOLS_FILE.exists():
        try:
            classified_data = json.loads(CLASSIFIED_KOLS_FILE.read_text())
            for ck in classified_data.get("kols", []):
                classified_by_handle[ck["username"].lower()] = ck
            print(f"Loaded {len(classified_by_handle)} classified KOLs")
        except Exception as e:
            print(f"Warning: failed to load classified KOLs: {e}")

    core_node_ids = {n["id"] for n in nodes}  # anchors + hubs
    peripheral_count = 0
    for uname, ck in classified_by_handle.items():
        if uname in core_node_ids:
            continue
        anchors_following = follow_lookup.get(uname, [])
        circles_via = []
        for a in anchors_following:
            for c in circle_membership.get(a, []):
                if c not in circles_via:
                    circles_via.append(c)
        nodes.append({
            "id": uname,
            "label": "@" + uname,
            "type": "peripheral",
            "name": ck.get("name"),
            "description": (ck.get("bio") or "")[:200],
            "followers_count": ck.get("followers_count") or 0,
            "verified": ck.get("verified", False),
            "x_id": ck.get("id"),
            "anchor_count": len(anchors_following),
            "followed_by_anchors": anchors_following,
            "circles": sorted(circles_via),
            "is_bridge": len(circles_via) > 1,
        })
        peripheral_count += 1

    node_id_set = {n["id"] for n in nodes}
    print(f"Nodes built: {len(nodes)}")
    print(f"  anchors:     {sum(1 for n in nodes if n['type'] == 'anchor')}")
    print(f"  hubs:        {sum(1 for n in nodes if n['type'] == 'hub')}")
    print(f"  peripherals: {peripheral_count}")
    print()

    # ---------- Build EDGES ----------
    edges: list[dict] = []

    # T1: anchor ↔ anchor MUTUAL follows (from unified_16_anchor_matrix)
    t1_count = 0
    for edge in unified["mutual_edges"]:
        a, b = edge["a"], edge["b"]
        edges.append({
            "source": a,
            "target": b,
            "tier": 1,
            "type": "mutual_follow",
            "kind": edge["kind"],  # INTERNAL or CROSS-CIRCLE
            "circles": edge["circles"],
            "directed": False,
            "weight": 3.0,
        })
        t1_count += 1

    # T2a: anchor ↔ anchor ONE-WAY follows (also from unified)
    t2a_count = 0
    for edge in unified["oneway_edges"]:
        follower, followee = edge["follower"], edge["followee"]
        edges.append({
            "source": follower,
            "target": followee,
            "tier": 2,
            "type": "one_way_follow_anchor",
            "kind": edge["kind"],
            "circles": edge["circles"],
            "directed": True,
            "weight": 1.5,
        })
        t2a_count += 1

    # T2b: anchor → hub ONE-WAY follows (we know anchors follow these hubs;
    #      we don't know if hubs follow back without fetching their /following)
    t2b_count = 0
    for hub in ultra_hubs:
        hub_id = hub["username"]
        if hub_id not in node_id_set:
            continue
        for anchor in hub["followed_by_anchors"]:
            if anchor not in node_id_set:
                continue
            edges.append({
                "source": anchor,
                "target": hub_id,
                "tier": 2,
                "type": "anchor_to_hub",
                "directed": True,
                "weight": 1.0,
            })
            t2b_count += 1

    # T3: hub ↔ hub inferred co-follow (if they share ≥T3_COFOLLOW_MIN_SHARED anchors)
    # Capped at T3_MAX_PER_NODE edges per node to prevent hairball visualization.
    t3_count = 0
    hub_anchor_sets = {h["username"]: set(h["followed_by_anchors"]) for h in ultra_hubs}
    # Collect all candidate T3 edges first
    candidate_t3 = []
    for u1, u2 in combinations(hub_anchor_sets.keys(), 2):
        shared = hub_anchor_sets[u1] & hub_anchor_sets[u2]
        if len(shared) >= T3_COFOLLOW_MIN_SHARED:
            candidate_t3.append((len(shared), u1, u2, shared))
    # Sort by shared count descending, then greedily add while respecting per-node cap
    candidate_t3.sort(key=lambda x: -x[0])
    t3_per_node = defaultdict(int)
    for shared_count, u1, u2, shared_set in candidate_t3:
        if t3_per_node[u1] >= T3_MAX_PER_NODE or t3_per_node[u2] >= T3_MAX_PER_NODE:
            continue
        edges.append({
            "source": u1,
            "target": u2,
            "tier": 3,
            "type": "co_follow_inferred",
            "shared_anchors": sorted(shared_set),
            "shared_count": shared_count,
            "directed": False,
            "weight": 0.3 + 0.1 * shared_count,
        })
        t3_per_node[u1] += 1
        t3_per_node[u2] += 1
        t3_count += 1

    # T2c: anchor → peripheral (one-way, from follow_lookup)
    # Every peripheral with ≥PERIPHERAL_T2_MIN_ANCHORS gets edges from the anchors that follow them.
    t2c_count = 0
    peripheral_ids = {n["id"] for n in nodes if n["type"] == "peripheral"}
    for pid in peripheral_ids:
        anchors_following = follow_lookup.get(pid, [])
        if len(anchors_following) < PERIPHERAL_T2_MIN_ANCHORS:
            continue
        for anchor in anchors_following:
            if anchor not in node_id_set:
                continue
            edges.append({
                "source": anchor,
                "target": pid,
                "tier": 2,
                "type": "anchor_to_peripheral",
                "directed": True,
                "weight": 0.6,
            })
            t2c_count += 1

    # T3b: peripheral ↔ peripheral co-follow (sparser than hub T3)
    # Only connect peripherals that share ≥PERIPHERAL_T3_MIN_SHARED anchors.
    t3b_count = 0
    per_anchor_sets = {pid: set(follow_lookup.get(pid, [])) for pid in peripheral_ids}
    candidate_p3 = []
    for u1, u2 in combinations(per_anchor_sets.keys(), 2):
        if not per_anchor_sets[u1] or not per_anchor_sets[u2]:
            continue
        shared = per_anchor_sets[u1] & per_anchor_sets[u2]
        if len(shared) >= PERIPHERAL_T3_MIN_SHARED:
            candidate_p3.append((len(shared), u1, u2, shared))
    candidate_p3.sort(key=lambda x: -x[0])
    p3_per_node = defaultdict(int)
    for shared_count, u1, u2, shared_set in candidate_p3:
        if p3_per_node[u1] >= PERIPHERAL_T3_MAX_PER_NODE or p3_per_node[u2] >= PERIPHERAL_T3_MAX_PER_NODE:
            continue
        edges.append({
            "source": u1,
            "target": u2,
            "tier": 3,
            "type": "peripheral_cofollow",
            "shared_anchors": sorted(shared_set),
            "shared_count": shared_count,
            "directed": False,
            "weight": 0.2 + 0.05 * shared_count,
        })
        p3_per_node[u1] += 1
        p3_per_node[u2] += 1
        t3b_count += 1

    print(f"Edges built: {len(edges)}")
    print(f"  T1  (mutual anchor↔anchor):       {t1_count}")
    print(f"  T2a (one-way anchor↔anchor):      {t2a_count}")
    print(f"  T2b (anchor→hub):                  {t2b_count}")
    print(f"  T2c (anchor→peripheral):           {t2c_count}")
    print(f"  T3  (hub co-follow inferred):     {t3_count}")
    print(f"  T3b (peripheral co-follow):       {t3b_count}")
    print()

    # ---------- Run network metrics ----------
    # CRITICAL: Centrality metrics (PageRank, betweenness, Louvain) are computed
    # ONLY on the MUTUAL SUBGRAPH — i.e. anchors + T1 mutual edges + T2a one-way
    # anchor↔anchor edges. T2b/T2c (anchor→hub/peripheral) are EXCLUDED from
    # metrics because they encode "X is followed by anchors" which is the famous-
    # person bias (anchors follow CZ, but CZ doesn't follow back). Including
    # these one-way celebrity-follows in PageRank inflates @justinsuntron etc.
    # to look like network hubs when they're really external celebrities.
    #
    # The mutual subgraph contains only the 16 anchors. Hubs/peripherals are
    # rendered in the visualization as "watched" nodes (visually demoted) and
    # do NOT receive PageRank / cluster assignments.
    anchor_id_set_for_metrics = {h for h in anchor_handles}
    G_mutual = nx.Graph()
    for nid in anchor_id_set_for_metrics:
        G_mutual.add_node(nid)
    mutual_edge_count = 0
    for e in edges:
        if e["tier"] != 1 and e["type"] != "one_way_follow_anchor":
            continue
        s, t = e["source"], e["target"]
        if s not in anchor_id_set_for_metrics or t not in anchor_id_set_for_metrics:
            continue
        if G_mutual.has_edge(s, t):
            G_mutual[s][t]["weight"] += e["weight"]
        else:
            G_mutual.add_edge(s, t, weight=e["weight"], tier=e["tier"])
        mutual_edge_count += 1

    print()
    print(f"Mutual subgraph: {G_mutual.number_of_nodes()} nodes, {G_mutual.number_of_edges()} edges (T1 + anchor↔anchor T2a only)")
    print("  → centrality metrics (PR, betweenness, Louvain) computed on this only")

    print("Running Louvain community detection (mutual subgraph)...")
    if G_mutual.number_of_edges() > 0:
        partition = community_louvain.best_partition(G_mutual, random_state=42)
    else:
        partition = {nid: 0 for nid in anchor_id_set_for_metrics}
    n_clusters = len(set(partition.values()))
    print(f"  → {n_clusters} communities found")

    print("Running PageRank (mutual subgraph, weighted)...")
    pagerank = nx.pagerank(G_mutual, weight="weight") if G_mutual.number_of_edges() > 0 else {}

    print("Running betweenness centrality (mutual subgraph)...")
    betweenness = nx.betweenness_centrality(G_mutual, weight="weight") if G_mutual.number_of_edges() > 0 else {}

    # Build the full degree graph (for `degree` field — informational, includes
    # one-way edges so users can see "this account is followed by N anchors")
    G_full = nx.Graph()
    for n in nodes:
        G_full.add_node(n["id"])
    for e in edges:
        if not G_full.has_edge(e["source"], e["target"]):
            G_full.add_edge(e["source"], e["target"])

    # Enrich nodes with metrics. Watched nodes (hubs/peripherals) get NULL for
    # pagerank/cluster — they are NOT in the centrality subgraph by design.
    for n in nodes:
        nid = n["id"]
        if nid in anchor_id_set_for_metrics:
            n["cluster"] = partition.get(nid, 0)
            n["pagerank"] = round(pagerank.get(nid, 0), 5)
            n["betweenness"] = round(betweenness.get(nid, 0), 5)
            n["is_mutual_member"] = True
        else:
            n["cluster"] = None
            n["pagerank"] = None
            n["betweenness"] = None
            n["is_mutual_member"] = False
        n["degree"] = G_full.degree(nid) if nid in G_full else 0

    # Build cluster summary
    cluster_members: dict[int, list[str]] = defaultdict(list)
    for nid, cid in partition.items():
        cluster_members[cid].append(nid)

    cluster_summary = []
    # Only surface clusters with real structure (≥3 members). Singletons (isolated
    # peripherals with no anchor-follow data) still appear as nodes in the graph but
    # don't clutter the cluster summary.
    for cid, members in sorted(cluster_members.items(), key=lambda x: -len(x[1])):
        if len(members) < 3:
            continue
        top_by_pagerank = sorted(members, key=lambda h: -pagerank.get(h, 0))[:3]
        top_by_betweenness = sorted(members, key=lambda h: -betweenness.get(h, 0))[:2]
        # Find which circles this cluster spans
        circles_in_cluster = set()
        for m in members:
            if m in anchor_profiles:
                circles_in_cluster.update(circle_membership[m])
        cluster_summary.append({
            "cluster_id": cid,
            "size": len(members),
            "members": members,
            "recommended_entry_point": "@" + top_by_pagerank[0] if top_by_pagerank else None,
            "entry_point_reason": f"Highest PageRank in cluster ({pagerank.get(top_by_pagerank[0], 0):.4f})" if top_by_pagerank else "",
            "bridge_nodes": ["@" + h for h in top_by_betweenness],
            "circles_touched": sorted(circles_in_cluster),
        })

    connected_clusters_count = len(cluster_summary)
    isolated_count = sum(1 for members in cluster_members.values() if len(members) == 1)

    # ---------- Save outputs ----------
    metadata = {
        "generated_at": "2026-04-08",
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "node_breakdown": {
            "anchors": sum(1 for n in nodes if n["type"] == "anchor"),
            "hubs": sum(1 for n in nodes if n["type"] == "hub"),
            "peripherals": sum(1 for n in nodes if n["type"] == "peripheral"),
        },
        "edge_breakdown": {
            "tier_1_mutual": t1_count,
            "tier_2a_oneway_anchor": t2a_count,
            "tier_2b_anchor_to_hub": t2b_count,
            "tier_2c_anchor_to_peripheral": t2c_count,
            "tier_3_cofollow_inferred": t3_count,
            "tier_3b_peripheral_cofollow": t3b_count,
        },
        "clusters_found": n_clusters,
        "connected_clusters": connected_clusters_count,
        "isolated_nodes": isolated_count,
        "cluster_summary": cluster_summary,
        "top_pagerank": [
            {"id": nid, "pagerank": round(pr, 5)}
            for nid, pr in sorted(pagerank.items(), key=lambda x: -x[1])[:10]
        ],
        "top_betweenness": [
            {"id": nid, "betweenness": round(bc, 5)}
            for nid, bc in sorted(betweenness.items(), key=lambda x: -x[1])[:10]
        ],
        "input_data": {
            "circles": 3,
            "anchors_from_circles": len(anchor_handles),
            "total_raw_following_records_analyzed": sum(
                state["anchor_data"][h]["count"]
                for state in [c1, c2, c3]
                for h in state["anchors"]
            ),
            "cost_usd_total": round(
                c1.get("api_cost_usd", 0)
                + c2.get("api_cost_usd", 0)
                + c3.get("api_cost_usd", 0),
                2,
            ),
        },
    }

    # classified_by_handle was loaded earlier (before peripheral nodes were added).
    # Merge classification data into ALL graph nodes (anchors, hubs, peripherals).
    # Critical: also merge followers_count so the celebrity heuristic below works.
    for n in nodes:
        merge = classified_by_handle.get(n["id"])
        if merge:
            n["scores"] = merge.get("scores", {})
            n["overall_score"] = merge.get("overall_score")
            n["sector"] = merge.get("sector")
            n["tier"] = merge.get("tier")
            n["language"] = merge.get("language")
            n["region"] = merge.get("region")
            n["content_type"] = merge.get("content_type")
            n["cooperability"] = merge.get("cooperability")
            n["outreach_angle"] = merge.get("outreach_angle")
            n["estimated_price_tier"] = merge.get("estimated_price_tier")
            n["score_reasoning"] = merge.get("score_reasoning")
            # Anchor nodes are missing followers_count from earlier construction
            # (only following_count was set). Merge it from classified data.
            if not n.get("followers_count") and merge.get("followers_count"):
                n["followers_count"] = merge.get("followers_count")
            if not n.get("name") and merge.get("name"):
                n["name"] = merge.get("name")
            if not n.get("description") and merge.get("bio"):
                n["description"] = merge.get("bio")[:200]

    # ---------- Celebrity heuristic (Plan B) ----------
    # Mark watched (non-anchor) nodes as `is_celebrity_outbound` when they're
    # clearly more famous than the typical anchor. Famous-person bias: Jack Ma
    # doesn't follow you back. We use the MEDIAN anchor follower count (×5) as
    # the threshold rather than the mean, because the mean is skewed by a
    # couple of outlier anchors (@phyrexni 382K, @btcdayu 300K) that pull the
    # average up and let real celebrities slip through.
    #
    # Rule: if followers >= 5 × median(anchor followers), flag as celebrity.
    # AND/OR: if followers >= 2 × max(anchor followers), definitely flag.
    # AND/OR: if followers >= 250K and anchor_count <= 5, flag (small audience
    # of anchors following, big external megaphone).
    anchor_followers = sorted(
        n.get("followers_count") or 0
        for n in nodes
        if n["type"] == "anchor" and (n.get("followers_count") or 0) > 0
    )
    if anchor_followers:
        avg_anchor_followers = sum(anchor_followers) / len(anchor_followers)
        median_anchor_followers = anchor_followers[len(anchor_followers) // 2]
        max_anchor_followers = max(anchor_followers)
    else:
        avg_anchor_followers = 50000
        median_anchor_followers = 50000
        max_anchor_followers = 100000

    threshold_5x_median = 5 * median_anchor_followers
    threshold_2x_max = 2 * max_anchor_followers
    threshold_small_audience = 250000  # small N anchors but big external audience

    print(
        f"\nCelebrity heuristic: avg={avg_anchor_followers:,.0f}, "
        f"median={median_anchor_followers:,.0f}, max={max_anchor_followers:,.0f}"
    )
    print(
        f"  thresholds: 5×median={threshold_5x_median:,.0f}, "
        f"2×max={threshold_2x_max:,.0f}, "
        f"small_audience_cutoff={threshold_small_audience:,}"
    )

    celebrity_count = 0
    for n in nodes:
        if n["type"] == "anchor":
            n["is_celebrity_outbound"] = False
            continue
        fc = n.get("followers_count") or 0
        ac = n.get("anchor_count") or 0
        is_celeb = (
            fc >= threshold_5x_median
            or fc >= threshold_2x_max
            or (fc >= threshold_small_audience and ac <= 5)
        )
        n["is_celebrity_outbound"] = is_celeb
        if is_celeb:
            celebrity_count += 1
    print(f"  → {celebrity_count} nodes flagged as celebrity_outbound (filtered from default view)")

    watched_count = sum(
        1
        for n in nodes
        if not n.get("is_mutual_member") and not n.get("is_celebrity_outbound")
    )
    mutual_member_count = sum(1 for n in nodes if n.get("is_mutual_member"))
    metadata["mutual_members"] = mutual_member_count
    metadata["watched_nodes"] = watched_count
    metadata["celebrity_filtered"] = celebrity_count
    print(f"  → mutual_members={mutual_member_count}, watched={watched_count}, celebrity_filtered={celebrity_count}")

    graph_doc = {
        "metadata": metadata,
        "nodes": nodes,
        "edges": edges,
    }

    # Build kols.json as union of ALL classified humans, with graph fields merged
    # for those that are also in the graph.
    graph_node_ids = {n["id"] for n in nodes}
    anchor_id_set = {n["id"] for n in nodes if n["type"] == "anchor"}

    merged_kols = []
    for username, ck in classified_by_handle.items():
        in_graph = username in graph_node_ids
        graph_node = next((n for n in nodes if n["id"] == username), None)

        entry = {
            "id": username,
            "handle": "@" + (ck.get("name_handle") or username),
            "name": ck.get("name"),
            "bio": ck.get("bio"),
            "followers_count": ck.get("followers_count"),
            "following_count": ck.get("following_count"),
            "tweet_count": ck.get("tweet_count"),
            "verified": ck.get("verified", False),
            "x_url": ck.get("x_url"),

            # Classification
            "is_real_human": ck.get("is_real_human"),
            "is_ai_crypto_focused": ck.get("is_ai_crypto_focused"),
            "is_active": ck.get("is_active"),
            "has_original_content": ck.get("has_original_content"),
            "sector": ck.get("sector"),
            "tier": ck.get("tier"),
            "language": ck.get("language"),
            "region": ck.get("region"),
            "content_type": ck.get("content_type"),
            "cooperability": ck.get("cooperability"),
            "outreach_angle": ck.get("outreach_angle"),
            "estimated_price_tier": ck.get("estimated_price_tier"),

            # Dual-Layer scores (from Claude Haiku classification)
            "scores": ck.get("scores"),
            "overall_score": ck.get("overall_score"),
            "score_reasoning": ck.get("score_reasoning"),

            # Graph metrics (only for nodes in the graph)
            "in_graph": in_graph,
            "type": graph_node["type"] if graph_node else "database_only",
            "circles": graph_node["circles"] if graph_node else [],
            "is_bridge": graph_node.get("is_bridge", False) if graph_node else False,
            "cluster": graph_node.get("cluster") if graph_node else None,
            "pagerank": graph_node.get("pagerank") if graph_node else None,
            "betweenness": graph_node.get("betweenness") if graph_node else None,
            "anchor_count": graph_node.get("anchor_count") if graph_node else None,
            # New honesty flags (Plan D — fix for asymmetric-follow bug)
            "is_mutual_member": graph_node.get("is_mutual_member", False) if graph_node else False,
            "is_celebrity_outbound": graph_node.get("is_celebrity_outbound", False) if graph_node else False,
        }
        merged_kols.append(entry)

    # Sort by overall_score desc (highest-scoring KOLs first)
    merged_kols.sort(key=lambda k: -(k.get("overall_score") or 0))

    # If classified_kols.json wasn't available yet, fall back to the old graph-only list.
    if not merged_kols:
        merged_kols = [
            {
                "id": n["id"],
                "handle": n["label"],
                "type": n["type"],
                "name": n.get("name"),
                "bio": n.get("description", ""),
                "followers_count": n.get("followers_count"),
                "verified": n.get("verified", False),
                "circles": n["circles"],
                "is_bridge": n.get("is_bridge", False),
                "cluster": n.get("cluster"),
                "pagerank": n.get("pagerank"),
                "betweenness": n.get("betweenness"),
                "anchor_count": n.get("anchor_count"),
                "x_url": f"https://x.com/{n['id']}",
                "in_graph": True,
                "scores": None,
                "overall_score": None,
            }
            for n in nodes
        ]

    kols_doc = {
        "metadata": {
            "generated_at": "2026-04-08",
            "total_kols": len(merged_kols),
            "in_graph_count": sum(1 for k in merged_kols if k.get("in_graph")),
            "database_only_count": sum(1 for k in merged_kols if not k.get("in_graph")),
            "classified": CLASSIFIED_KOLS_FILE.exists(),
            "source": "Phase 1 Step 3 graph build + Claude Haiku classification",
        },
        "kols": merged_kols,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "graph.json").write_text(json.dumps(graph_doc, indent=2, ensure_ascii=False))
    (OUTPUT_DIR / "kols.json").write_text(json.dumps(kols_doc, indent=2, ensure_ascii=False))

    # Also save a copy in pipeline/circles for audit
    (CIRCLES / "graph_v1.json").write_text(json.dumps(graph_doc, indent=2, ensure_ascii=False))

    print()
    print("=" * 72)
    print("REPORT")
    print("=" * 72)
    print(f"\nClusters ({n_clusters}):")
    for cs in cluster_summary:
        print(f"\n  Cluster {cs['cluster_id']} ({cs['size']} members, circles: {','.join(cs['circles_touched']) or '—'})")
        print(f"    Entry point:  {cs['recommended_entry_point']}  ({cs['entry_point_reason']})")
        print(f"    Bridges:      {', '.join(cs['bridge_nodes'])}")
        # Show first few members
        sample = cs["members"][:6]
        print(f"    Members ({len(cs['members'])}): {', '.join('@'+m for m in sample)}{'...' if len(cs['members']) > 6 else ''}")

    print()
    print("Top 10 by PageRank (overall network centrality):")
    for i, entry in enumerate(metadata["top_pagerank"], 1):
        node = next(n for n in nodes if n["id"] == entry["id"])
        label = "⚓" if node["type"] == "anchor" else "🔹"
        print(f"  {i:>2}. {label} @{entry['id']:<22} pr={entry['pagerank']}  [{','.join(node['circles']) or '—'}]")

    print()
    print("Top 10 by Betweenness (bridge potential):")
    for i, entry in enumerate(metadata["top_betweenness"], 1):
        node = next(n for n in nodes if n["id"] == entry["id"])
        label = "⚓" if node["type"] == "anchor" else "🔹"
        print(f"  {i:>2}. {label} @{entry['id']:<22} bc={entry['betweenness']}  [{','.join(node['circles']) or '—'}]")

    print()
    print(f"✅ graph.json saved: {OUTPUT_DIR / 'graph.json'}")
    print(f"✅ kols.json  saved: {OUTPUT_DIR / 'kols.json'}")
    print(f"✅ audit copy: {CIRCLES / 'graph_v1.json'}")


if __name__ == "__main__":
    main()
