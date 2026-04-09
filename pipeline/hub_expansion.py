"""
Phase 1 Step 2: Hub expansion analysis.

Goal: from the 16 anchors' /following data (13,763 total records after dedup),
find accounts that are followed by MULTIPLE anchors. These are "hub" candidates
that extend the 16-node skeleton into a richer graph (60-100 nodes).

Zero cost — pure set intersection on already-paid data.

Thresholds:
  ≥6 anchors = ultra-hub (core influencer in the whole Chinese AI+Crypto scene)
  ≥4 anchors = strong hub (expansion candidate for graph)
  ≥3 anchors = weak hub (optional, for fuller graph)
  ≥2 anchors = co-follow (T3 inferred edges only)

Output:
  pipeline/circles/hub_candidates.json
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
C1_FILE = ROOT / "pipeline" / "circles" / "virtuals_chinese_builders_step1.json"
C2_FILE = ROOT / "pipeline" / "circles" / "xhunt_web3_media_step1.json"
C3_FILE = ROOT / "pipeline" / "circles" / "chinese_crypto_analysis_step1.json"
OUTPUT = ROOT / "pipeline" / "circles" / "hub_candidates.json"


def load_circle(path: Path) -> dict[str, list[dict]]:
    """Return {handle_lower: [list of profile dicts]}"""
    state = json.loads(path.read_text())
    out = {}
    for h in state["anchors"]:
        following = state["anchor_data"][h]["following"]
        out[h.lower()] = following
    return out


def main() -> None:
    print("=" * 72)
    print("STEP 2 — Hub expansion from 16-anchor /following data")
    print("Zero cost: pure computation on already-paid data")
    print("=" * 72)
    print()

    c1 = load_circle(C1_FILE)
    c2 = load_circle(C2_FILE)
    c3 = load_circle(C3_FILE)

    # Unify, deduplicating colinwu/phyrexni (in both C2 and C3)
    all_anchors: dict[str, list[dict]] = {}
    circle_of: dict[str, list[str]] = defaultdict(list)
    for h, following in c1.items():
        all_anchors[h] = following
        circle_of[h].append("C1")
    for h, following in c2.items():
        if h not in all_anchors:
            all_anchors[h] = following
        circle_of[h].append("C2")
    for h, following in c3.items():
        if h not in all_anchors:
            all_anchors[h] = following
        circle_of[h].append("C3")

    anchor_handles = set(all_anchors.keys())
    print(f"Unified anchors: {len(anchor_handles)}")
    print(f"Total /following records: {sum(len(v) for v in all_anchors.values())}")
    print()

    # Build: username → {anchor_handle: profile_dict_seen_via_this_anchor}
    # This lets us track both who follows the candidate AND retrieve profile data
    candidate_map: dict[str, dict] = defaultdict(lambda: {
        "anchors_following": set(),
        "profiles": [],  # may have multiple with same data — dedupe by id later
    })

    for anchor, following_list in all_anchors.items():
        for u in following_list:
            username = (u.get("username") or "").lower()
            if not username:
                continue
            if username in anchor_handles:
                continue  # skip anchor-to-anchor, that's in unified_16_anchor_matrix
            candidate_map[username]["anchors_following"].add(anchor)
            candidate_map[username]["profiles"].append(u)

    total_unique_candidates = len(candidate_map)
    print(f"Unique non-anchor accounts followed by ≥1 anchor: {total_unique_candidates:,}")

    # Histogram of anchor count per candidate
    histogram = defaultdict(int)
    for v in candidate_map.values():
        histogram[len(v["anchors_following"])] += 1

    print()
    print("Histogram — how many anchors follow each candidate:")
    for n in sorted(histogram.keys(), reverse=True):
        bar = "█" * min(50, histogram[n] // 10) if histogram[n] >= 10 else "▏"
        print(f"  {n:>2}/16 anchors : {histogram[n]:>6}  {bar}")
    print()

    # Classify hubs
    def best_profile(profiles: list[dict]) -> dict:
        """Pick the richest profile (most fields populated)."""
        def score(p):
            return (
                1 if p.get("id") else 0,
                1 if p.get("name") else 0,
                1 if p.get("description") else 0,
                1 if p.get("public_metrics", {}).get("followers_count") else 0,
            )
        return max(profiles, key=score) if profiles else {}

    def build_hub_entry(username: str, info: dict) -> dict:
        profile = best_profile(info["profiles"])
        metrics = profile.get("public_metrics", {})
        return {
            "username": username,
            "anchor_count": len(info["anchors_following"]),
            "followed_by_anchors": sorted(info["anchors_following"]),
            "id": profile.get("id"),
            "name": profile.get("name"),
            "description": (profile.get("description") or "")[:300],
            "verified": profile.get("verified", False),
            "followers_count": metrics.get("followers_count"),
            "following_count": metrics.get("following_count"),
        }

    # Thresholds
    ultra_hubs = []   # ≥6 anchors
    strong_hubs = []  # ≥4 anchors
    weak_hubs = []    # =3 anchors
    co_follows = []   # =2 anchors (NOT added as nodes, but as T3 inferred edges)

    for username, info in candidate_map.items():
        n = len(info["anchors_following"])
        entry = build_hub_entry(username, info)
        if n >= 6:
            ultra_hubs.append(entry)
        elif n >= 4:
            strong_hubs.append(entry)
        elif n == 3:
            weak_hubs.append(entry)
        elif n == 2:
            co_follows.append({
                "username": username,
                "followed_by_anchors": entry["followed_by_anchors"],
            })

    # Sort each bucket by anchor_count desc, then followers desc
    def sort_key(h):
        return (-h["anchor_count"], -(h.get("followers_count") or 0))

    ultra_hubs.sort(key=sort_key)
    strong_hubs.sort(key=sort_key)
    weak_hubs.sort(key=sort_key)

    print(f"=== HUB TIERS ===")
    print(f"Ultra hubs (≥6 anchors): {len(ultra_hubs):>4}")
    print(f"Strong hubs (4-5 anchors): {len(strong_hubs):>4}")
    print(f"Weak hubs  (=3 anchors): {len(weak_hubs):>4}")
    print(f"Co-follow  (=2 anchors): {len(co_follows):>4}")
    print()

    # Show ultra-hubs in detail
    print("=" * 72)
    print(f"ULTRA HUBS (≥6 anchors) — top influencers in the combined network")
    print("=" * 72)
    for h in ultra_hubs:
        name = h.get("name") or "?"
        fc = h.get("followers_count") or 0
        bio = (h.get("description") or "").replace("\n", " ")[:60]
        print(f"  [{h['anchor_count']:>2}/16] @{h['username']:<22} {fc:>10,}  {name[:25]:<25}  {bio}")
    print()

    print("=" * 72)
    print(f"STRONG HUBS (4-5 anchors) — top 30 by anchor count + followers")
    print("=" * 72)
    for h in strong_hubs[:30]:
        name = h.get("name") or "?"
        fc = h.get("followers_count") or 0
        bio = (h.get("description") or "").replace("\n", " ")[:50]
        print(f"  [{h['anchor_count']:>2}/16] @{h['username']:<22} {fc:>10,}  {name[:25]:<25}  {bio}")
    if len(strong_hubs) > 30:
        print(f"  ... ({len(strong_hubs)-30} more)")
    print()

    # Save
    output = {
        "source_files": [str(C1_FILE.name), str(C2_FILE.name), str(C3_FILE.name)],
        "total_anchors": len(anchor_handles),
        "total_unique_candidates": total_unique_candidates,
        "histogram": {str(k): v for k, v in sorted(histogram.items(), reverse=True)},
        "ultra_hubs_6_plus": ultra_hubs,
        "strong_hubs_4_5": strong_hubs,
        "weak_hubs_3": weak_hubs,
        "co_follows_2": co_follows,
        "suggested_nodes_for_graph": {
            "core_anchors": sorted(anchor_handles),
            "ultra_hubs": [h["username"] for h in ultra_hubs],
            "strong_hubs": [h["username"] for h in strong_hubs],
            "total_core_plus_hubs": len(anchor_handles) + len(ultra_hubs) + len(strong_hubs),
        },
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=list)

    print(f"✅ Saved: {OUTPUT}")
    print(f"\n=== GRAPH SIZE ESTIMATE ===")
    core = len(anchor_handles)
    ultra = len(ultra_hubs)
    strong = len(strong_hubs)
    print(f"  Core anchors (T1-rich):  {core}")
    print(f"  Ultra hubs (≥6 anchors): {ultra}")
    print(f"  Strong hubs (≥4 anchors): {strong}")
    print(f"  Total nodes if all included: {core + ultra + strong}")
    print(f"  (Add weak hubs for +{len(weak_hubs)} more if desired)")


if __name__ == "__main__":
    main()
