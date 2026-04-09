"""
Fix 6 verified mutual hubs that the Claude Haiku classifier incorrectly
marked as organizations / not AI+Crypto focused.

These 6 were discovered via `pipeline/hub_verify.py` and confirmed to follow
≥1 anchor in the mutual subgraph. Their existence IN the mutual subgraph is
ground-truth evidence that they are:
1. Real humans (the mutual hub verification would have filtered out pure
   org accounts during the candidate pool construction via project-name
   heuristics in `hub_verify.py`)
2. Actually embedded in the Chinese AI+Crypto community (not tangential —
   we verified mutual follow with 2-9 anchors each)

Override their flags in `users` so they enter the scoring-ready population
on next batch_score run.

The 6:
- @cryptosociety42 — 林克Clean, 9 anchors follow
- @mscryptojiayi — jiayi 加一, 8 anchors follow
- @pxstar_ — ratsxp, 6 anchors follow
- @solomon_nahhh — Solomon, 4 anchors follow
- @mia_okx — Mia米粒儿, 2 anchors follow
- @cryptobravehq — 加密无畏, 1 anchor follow

Run once:
    pipeline/.venv/bin/python pipeline/fix_misclassified_mutual_hubs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import get_client

HANDLES_TO_FIX = [
    "cryptosociety42",
    "mscryptojiayi",
    "pxstar_",
    "solomon_nahhh",
    "mia_okx",
    "cryptobravehq",
]


def main() -> int:
    sb = get_client()
    print("Overriding is_real_human and is_ai_crypto_focused on 6 verified mutual hubs...")
    for handle in HANDLES_TO_FIX:
        result = (
            sb.table("users")
            .update(
                {
                    "is_real_human": True,
                    "is_organization": False,
                    "is_ai_crypto_focused": True,
                    "classified_by": "hub_verify_override_2026-04-09",
                }
            )
            .eq("handle", handle)
            .execute()
        )
        rows = len(result.data) if result.data else 0
        print(f"  @{handle:<22} rows updated: {rows}")
    print()
    print("Done. Next: rerun scoring/batch_score.py for the new scoring-ready additions.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
