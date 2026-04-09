"""
Analyze the $36 Step 1 data from the failed Circle A attempt.

Even though the 6 sector-grouped anchors don't form a circle with each other,
their combined 4,090 follow records reveal "hub" accounts — people that multiple
anchors independently follow. These hubs are useful for FUTURE circle expansion:

  - When real ground-truth circles arrive (from Grok query or user-imported),
    cross-reference the real-circle members against these hubs.
  - Hubs appearing in real circles become confirmed-relevance candidates.
  - Hubs showing up across SEVERAL real circles are bridge candidates.
  - Hubs with v1 raw_expansion.json enrichment already have bio data for free.

This analysis costs $0 — it reads existing files only.

Output: pipeline/circles/chinese_ai_agent_sector_FAILED_hubs.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEP1_FILE = ROOT / "pipeline" / "circle_a_step1.json"
V1_RAW = ROOT / "pipeline" / "raw_expansion.json"
OUTPUT = ROOT / "pipeline" / "circles" / "chinese_ai_agent_sector_FAILED_hubs.json"


def main():
    print("=" * 72)
    print("Hub analysis — salvage value from failed Circle A $36 experiment")
    print("=" * 72)
    print()

    step1 = json.loads(STEP1_FILE.read_text())
    anchors = step1["anchors"]
    anchor_following = {h: set(step1["anchor_following"][h]) for h in anchors}

    print(f"Source: {STEP1_FILE.name}")
    print(f"Anchors: {anchors}")
    print(f"Unique usernames across all anchors: {sum(len(s) for s in anchor_following.values())}")
    print()

    # Count: for each username, which anchors follow them?
    follower_map: dict[str, set[str]] = defaultdict(set)
    for h, usernames in anchor_following.items():
        for u in usernames:
            follower_map[u].add(h)

    # Remove anchors themselves
    anchor_set_lower = {h.lower() for h in anchors}
    follower_map = {u: s for u, s in follower_map.items() if u not in anchor_set_lower}

    print(f"Total unique non-anchor accounts: {len(follower_map)}")
    print()

    # Histogram
    histogram = Counter(len(s) for s in follower_map.values())
    print("Histogram of anchor count per account:")
    for n in sorted(histogram.keys(), reverse=True):
        print(f"  followed by {n}/6 anchors: {histogram[n]:>5} accounts")
    print()

    # Try to enrich with v1 raw_expansion.json (has bios)
    v1_enrichment: dict[str, dict] = {}
    try:
        v1_data = json.loads(V1_RAW.read_text())
        for candidate in v1_data.get("candidates", []):
            handle = candidate.get("handle", "").lstrip("@").lower()
            profile = candidate.get("profile") or {}
            if handle:
                v1_enrichment[handle] = {
                    "name": profile.get("name"),
                    "description": (profile.get("description") or "")[:300],
                    "verified": profile.get("verified", False),
                    "public_metrics": profile.get("public_metrics", {}),
                    "followed_by_v1_seeds": candidate.get("followed_by_seed_handles", []),
                }
        print(f"v1 raw_expansion.json loaded: {len(v1_enrichment)} candidates with bios available")
    except FileNotFoundError:
        print("v1 raw_expansion.json not found — hubs will not be enriched with bios")
        v1_enrichment = {}

    # Build hub lists at each threshold, enrich where possible
    def build_hubs(min_anchors: int) -> list[dict]:
        hubs = []
        for username, following_anchors in follower_map.items():
            if len(following_anchors) < min_anchors:
                continue
            entry = {
                "username": username,
                "anchor_count": len(following_anchors),
                "followed_by_anchors": sorted(following_anchors),
                "enriched_from_v1": username in v1_enrichment,
            }
            if username in v1_enrichment:
                entry["profile"] = v1_enrichment[username]
            hubs.append(entry)
        hubs.sort(
            key=lambda h: (
                -h["anchor_count"],
                -(h.get("profile", {}).get("public_metrics", {}).get("followers_count", 0)),
            )
        )
        return hubs

    hubs_4_plus = build_hubs(4)
    hubs_3_plus = build_hubs(3)
    hubs_2_plus = build_hubs(2)

    enriched_count_2 = sum(1 for h in hubs_2_plus if h["enriched_from_v1"])

    print()
    print(f"Hubs at 4+ threshold: {len(hubs_4_plus)}  ({sum(1 for h in hubs_4_plus if h['enriched_from_v1'])} enriched from v1)")
    print(f"Hubs at 3+ threshold: {len(hubs_3_plus)}  ({sum(1 for h in hubs_3_plus if h['enriched_from_v1'])} enriched from v1)")
    print(f"Hubs at 2+ threshold: {len(hubs_2_plus)}  ({enriched_count_2} enriched from v1)")
    print()

    # Show the top hubs with bio context
    print("=" * 72)
    print("TOP HUBS (4+ anchors) with v1 enrichment where available")
    print("=" * 72)
    for h in hubs_4_plus:
        bio = ""
        fc = ""
        if h.get("profile"):
            bio = h["profile"].get("description", "")[:60]
            m = h["profile"].get("public_metrics", {})
            fc = f"{m.get('followers_count', 0):,} followers"
        print(f"  [{h['anchor_count']}/6] @{h['username']:<25} {fc}")
        if bio:
            print(f"           bio: {bio}")
        print(f"           followed by: {', '.join('@' + a for a in h['followed_by_anchors'])}")
    print()

    print("=" * 72)
    print("HUBS AT 3+ ANCHORS (top 20 by anchor count → follower count)")
    print("=" * 72)
    for h in hubs_3_plus[:20]:
        bio = ""
        fc = ""
        if h.get("profile"):
            bio = h["profile"].get("description", "")[:60]
            m = h["profile"].get("public_metrics", {})
            fc = f"{m.get('followers_count', 0):,}"
        flag = "🏷️" if h["enriched_from_v1"] else "  "
        print(f"  {flag} [{h['anchor_count']}/6] @{h['username']:<22} {fc:>10}  {bio}")
    print()

    # Sub-cluster detection via co-occurrence patterns
    # Which PAIRS of anchors share the most hub follows?
    pairwise_overlap: dict[tuple[str, str], int] = Counter()
    for u, following_anchors in follower_map.items():
        anchor_list = sorted(following_anchors)
        for i in range(len(anchor_list)):
            for j in range(i + 1, len(anchor_list)):
                pairwise_overlap[(anchor_list[i], anchor_list[j])] += 1

    print("=" * 72)
    print("PAIRWISE CO-FOLLOW OVERLAP (which anchor pairs share many followed accounts)")
    print("=" * 72)
    top_overlaps = sorted(pairwise_overlap.items(), key=lambda x: -x[1])
    for (a, b), count in top_overlaps[:10]:
        ja = len(anchor_following[a])
        jb = len(anchor_following[b])
        union = len(anchor_following[a] | anchor_following[b])
        jaccard = count / union if union else 0
        print(f"  @{a:<14} ↔ @{b:<14} shared={count:>3}  jaccard={jaccard:.3f}")
    print()

    # Output structured analysis
    output_data = {
        "source_files": {
            "step1": str(STEP1_FILE.relative_to(ROOT)),
            "v1_raw_expansion": str(V1_RAW.relative_to(ROOT)) if V1_RAW.exists() else None,
        },
        "cost_context": "$36 already spent on Step 1 /following calls; this analysis is $0",
        "anchors": anchors,
        "total_unique_non_anchor_accounts": len(follower_map),
        "histogram": {str(k): v for k, v in sorted(histogram.items(), reverse=True)},
        "hubs_4_plus": hubs_4_plus,
        "hubs_3_plus_count": len(hubs_3_plus),
        "hubs_3_plus_top_50": hubs_3_plus[:50],
        "hubs_2_plus_count": len(hubs_2_plus),
        "pairwise_overlap_top_15": [
            {
                "anchor_a": a,
                "anchor_b": b,
                "shared_follows": count,
                "jaccard": round(
                    count / len(anchor_following[a] | anchor_following[b])
                    if anchor_following[a] | anchor_following[b]
                    else 0,
                    3,
                ),
            }
            for (a, b), count in top_overlaps[:15]
        ],
        "sub_cluster_hypothesis": {
            "observation": "Anchor-to-anchor mutual follow density is 0%, but pairwise co-follow overlap reveals two sub-groups",
            "sub_cluster_ai_research": {
                "candidate_anchors": ["yanhua1010", "jingyuan_521", "sanbuphy"],
                "signal": "These three share follows like @karpathy, @sama, @anthropicai, @claudeai, @openai, @andrewyng, @ylecun, @op7418, @dotey. Pattern: AI research/industry observers, not crypto builders.",
            },
            "sub_cluster_chinese_crypto_degen": {
                "candidate_anchors": ["caelynzh", "0xzagen", "sunnyheima"],
                "signal": "These three share follows like @0xkakarot888, @cryptopainter, @jiamigou, @mscryptojiayi, @myao86, @vvickym2, @imahsenx. Pattern: Chinese crypto trader community (numeric-suffix usernames = classic 中文 degen style).",
            },
            "cross_cluster_bridges": [
                "elonmusk (4/6)",
                "drfeifei (4/6) — Fei-Fei Li, general AI figure",
                "steipete (4/6) — Peter Steinberger, AI/dev",
                "openclaw (4/6)",
                "0xkakarot888 (4/6)",
            ],
            "interpretation": "The $36 experiment did NOT discover a single Chinese AI Agent circle. It discovered that two different communities (AI researchers and Chinese crypto degens) happen to share the 'AI Agent' sector tag. These are different social circles.",
        },
        "how_to_use_this_data": [
            "When real ground-truth circles arrive (Grok query / user imports), cross-reference their members against hubs_3_plus_top_50",
            "Hubs enriched from v1 (has bios) are immediately assessable without new API calls",
            "Pairwise overlap top-15 shows potential REAL sub-cluster anchor groupings if we want to salvage the failed data",
            "Sub-cluster hypothesis suggests 'Chinese crypto degen' (caelynzh + 0xzagen + sunnyheima) MAY be a real circle to re-test, but only if we find a ground-truth reason to trust the grouping (not just sector label)",
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Output: {OUTPUT.relative_to(ROOT)}")
    print()
    print("Key takeaway: the $36 data is not wasted — it's now an enriched hub database")
    print("that will cross-reference against future ground-truth circles for free.")


if __name__ == "__main__":
    main()
