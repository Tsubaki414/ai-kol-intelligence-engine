"""
Export Supabase `users` table → `kol-intelligence-engine/src/data/kols.json`.

The front-end reads kols.json as a static artifact. Before Supabase migration,
kols.json was produced by `pipeline/build_graph.py` and carried a hallucinated
`scores` dict from the old Claude-based classifier. Post-migration, Supabase is
the source of truth, and this script rewrites kols.json from the DB's real
Layer 1/2/3 scores.

Run this script whenever:
- batch_score.py has been re-run (new scores)
- rebuild_network_stats.py has been re-run (new t1_mutual_count / cluster_id)
- Users table has gained/lost classified KOLs

The output matches the schema expected by Dashboard.jsx / Profile.jsx /
NetworkGraphPage.jsx / Outreach Panel.

Usage:
    pipeline/.venv/bin/python scoring/export_kols_json.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.db import get_client

OUTPUT_FILE = ROOT / "kol-intelligence-engine" / "src" / "data" / "kols.json"


def fetch_all_scoring_ready(sb):
    """Fetch all KOLs that passed Phase 1d hard filter (is_real_human + is_ai_crypto_focused)."""
    # Supabase has a default 1000 row limit. Paginate explicitly.
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        result = (
            sb.table("users")
            .select(
                "handle, x_id, name, bio, followers_count, following_count, tweet_count, "
                "verified, tier, sector, language, region, content_type, is_real_human, "
                "is_organization, is_ai_crypto_focused, is_active, has_original_content, is_anchor, "
                "cooperability, outreach_angle, estimated_price_tier, "
                "cluster_id, pagerank, betweenness, t1_mutual_count, "
                "cross_cluster_mutual_count, bridge_ratio, graph_indexed_at, "
                "quality_score, cooperability_score, onchain_score, "
                "quality_confidence, cooperability_confidence, onchain_confidence, "
                "score_traces, scored_at, scored_with_version, source"
            )
            .eq("is_real_human", True)
            .eq("is_ai_crypto_focused", True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_rows


def transform(row: dict) -> dict:
    """Shape a Supabase users row into the kols.json entry format."""
    handle = row["handle"]
    x_id = row.get("x_id")
    t1 = row.get("t1_mutual_count") or 0
    cluster_id = row.get("cluster_id")
    is_mutual_member = t1 > 0

    # Derive type label for display compatibility with old graph view
    if row.get("is_anchor"):
        type_label = "anchor"
    elif is_mutual_member:
        type_label = "verified_hub"
    else:
        type_label = "classified"

    # Legacy compatibility fields — Dashboard.jsx still reads `circles`, `is_bridge`,
    # `in_graph`. We populate them from the network stats.
    circles = []
    if row.get("is_anchor"):
        # Anchors have circles based on source; we don't have a direct mapping
        # in users table, so infer from source string if present.
        source = (row.get("source") or "").lower()
        if "virtuals" in source:
            circles.append("C1")
        if "xhunt" in source or "biteye" in source:
            circles.append("C2")
        if "chinese_crypto_analysis" in source:
            circles.append("C3")

    is_bridge = (
        row.get("cross_cluster_mutual_count") is not None
        and row.get("cross_cluster_mutual_count") > 0
    )

    return {
        "id": handle,
        "handle": "@" + handle,
        "x_id": x_id,
        "name": row.get("name"),
        "bio": row.get("bio"),
        "followers_count": row.get("followers_count"),
        "following_count": row.get("following_count"),
        "tweet_count": row.get("tweet_count"),
        "verified": row.get("verified", False),
        "x_url": f"https://x.com/{handle}",

        # Classification
        "is_real_human": row.get("is_real_human"),
        "is_organization": row.get("is_organization"),
        "is_ai_crypto_focused": row.get("is_ai_crypto_focused"),
        "is_active": row.get("is_active"),
        "has_original_content": row.get("has_original_content"),
        "is_anchor": row.get("is_anchor", False),
        "sector": row.get("sector"),
        "tier": row.get("tier"),
        "language": row.get("language"),
        "region": row.get("region"),
        "content_type": row.get("content_type"),

        # Cooperability v3 hard filter fields
        "cooperability": row.get("cooperability"),
        "outreach_angle": row.get("outreach_angle"),
        "estimated_price_tier": row.get("estimated_price_tier"),

        # Three-layer scores (real, from score_kol.py — not fabricated)
        "quality_score": row.get("quality_score"),
        "cooperability_score": row.get("cooperability_score"),
        "onchain_score": row.get("onchain_score"),
        "quality_confidence": row.get("quality_confidence"),
        "cooperability_confidence": row.get("cooperability_confidence"),
        "onchain_confidence": row.get("onchain_confidence"),
        "score_traces": row.get("score_traces"),
        "scored_at": row.get("scored_at"),
        "scored_with_version": row.get("scored_with_version"),

        # Network metrics (from rebuild_network_stats.py)
        "cluster": cluster_id,
        "cluster_id": cluster_id,
        "pagerank": row.get("pagerank"),
        "betweenness": row.get("betweenness"),
        "t1_mutual_count": t1,
        "cross_cluster_mutual_count": row.get("cross_cluster_mutual_count") or 0,
        "bridge_ratio": row.get("bridge_ratio") or 0.0,

        # Display flags
        "is_mutual_member": is_mutual_member,
        "is_bridge": is_bridge,
        "in_graph": is_mutual_member,   # legacy compat — "in_graph" now means "in mutual subgraph"
        "type": type_label,
        "circles": circles,
    }


def main() -> int:
    print("=" * 72)
    print("Export Supabase users → kols.json")
    print("=" * 72)

    sb = get_client()
    rows = fetch_all_scoring_ready(sb)
    print(f"Fetched {len(rows)} scoring-ready KOLs from Supabase")

    kols = [transform(r) for r in rows]
    # Sort: mutual members first (by t1 desc, then quality desc), then non-mutual by quality
    kols.sort(
        key=lambda k: (
            -1 if k["is_mutual_member"] else 0,
            -(k["t1_mutual_count"] or 0),
            -(k.get("quality_score") or 0),
            -(k.get("cooperability_score") or 0),
        )
    )

    # Derive aggregate metadata
    mutual_count = sum(1 for k in kols if k["is_mutual_member"])
    quality_count = sum(1 for k in kols if k.get("quality_score") is not None)
    coop_count = sum(1 for k in kols if k.get("cooperability_score") is not None)
    bridge_count = sum(1 for k in kols if k["is_bridge"])
    zh_count = sum(1 for k in kols if k.get("language") == "zh")
    en_count = sum(1 for k in kols if k.get("language") == "en")

    doc = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_kols": len(kols),
            "mutual_members": mutual_count,
            "bridges": bridge_count,
            "quality_scored": quality_count,
            "cooperability_scored": coop_count,
            "language_distribution": {"zh": zh_count, "en": en_count},
            "source": "Supabase users table (three-layer scoring v3_2026-04-09)",
            "notes": (
                "quality_score is null for KOLs without cached tweets (Phase 1d "
                "classification skipped due to budget constraint). "
                "cooperability_score is populated for all scoring-ready KOLs."
            ),
        },
        "kols": kols,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    print(f"✅ Wrote {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size / 1024:.0f} KB)")
    print()
    print(f"Total KOLs:           {len(kols)}")
    print(f"Mutual members:       {mutual_count}")
    print(f"Bridges:              {bridge_count}")
    print(f"Quality scored:       {quality_count}")
    print(f"Cooperability scored: {coop_count}")
    print(f"Language zh/en:       {zh_count}/{en_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
