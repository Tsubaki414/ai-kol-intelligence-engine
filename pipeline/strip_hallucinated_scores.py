"""
One-off cleanup: strip fabricated `scores`, `overall_score`, `score_reasoning`
fields from classified_kols.json.

Background:
The previous classification pass (classify_and_score.py) asked Claude Haiku
to assign numeric sub-scores (view_velocity, content_originality, ...) based
on profile data alone. These scores are fabricated — view_velocity in
particular cannot be computed without per-tweet view data that X API v2
Basic tier doesn't expose, and the observed values are all suspiciously
round 80-95 integers.

Per CLAUDE.md Anti-pattern #1 ("no fabricated data"), these must be removed
before the three-layer scoring system (scoring/scoring_spec.md v3 2026-04-08)
runs against this data.

This script:
1. Loads classified_kols.json
2. For each KOL entry, removes keys: scores, overall_score, score_reasoning
3. Writes back to classified_kols.json
4. Adds a metadata marker noting the cleanup
5. Preserves all other classification fields (is_real_human, sector, tier,
   cooperability, outreach_angle, estimated_price_tier, etc.)

Run once. Idempotent (safe to re-run — will just report "nothing to strip").
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(__file__).parent / "classified_kols.json"
BACKUP = Path(__file__).parent / "classified_kols.backup_pre_cleanup.json"

FIELDS_TO_STRIP = ("scores", "overall_score", "score_reasoning")


def main() -> int:
    if not BACKUP.exists():
        print(f"ERROR: backup {BACKUP.name} does not exist — refusing to proceed")
        print("Create a backup first: cp classified_kols.json classified_kols.backup_pre_cleanup.json")
        return 1

    with TARGET.open() as f:
        data = json.load(f)

    kols = data.get("kols", [])
    total = len(kols)
    print(f"Loaded {total} KOL entries from {TARGET.name}")

    stripped_counts = {field: 0 for field in FIELDS_TO_STRIP}
    preserved_field_samples = None

    for kol in kols:
        if preserved_field_samples is None:
            preserved_field_samples = sorted(
                k for k in kol.keys() if k not in FIELDS_TO_STRIP
            )
        for field in FIELDS_TO_STRIP:
            if field in kol:
                del kol[field]
                stripped_counts[field] += 1

    # Add cleanup marker to metadata
    md = data.setdefault("metadata", {})
    md["scores_stripped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md["scores_stripped_reason"] = (
        "Fabricated scores from classify_and_score.py removed. "
        "Three-layer scoring (scoring_spec.md v3 2026-04-08) will repopulate."
    )
    md["scores_stripped_fields"] = list(FIELDS_TO_STRIP)

    with TARGET.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nStripped field counts (out of {total} KOLs):")
    for field, count in stripped_counts.items():
        print(f"  {field}: {count}")

    print(f"\nPreserved fields per KOL (sample from first entry):")
    for field in preserved_field_samples or []:
        print(f"  - {field}")

    print(f"\nMetadata marker added: scores_stripped_at={md['scores_stripped_at']}")
    print(f"Backup remains at: {BACKUP.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
