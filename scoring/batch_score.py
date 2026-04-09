"""
Batch-score all classified KOLs in Supabase and persist results.

Target set: users where is_real_human=True AND is_ai_crypto_focused=True.
These are the 674 classified humans from classified_kols.json. For each:
  1. load_kol_raw() → KolRaw
  2. score_kol() → ScoredKol (three parallel scores + traces)
  3. write_score_to_db() → UPDATE users row

Tracks failures per-KOL so one broken record doesn't stop the batch.
Prints distribution stats at the end.

Usage:
    python3 -m scoring.batch_score                 # score all
    python3 -m scoring.batch_score --limit 20      # score first 20 (debugging)
    python3 -m scoring.batch_score --handle btcdayu  # score one (debugging)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.db import get_client  # noqa: E402
from scoring.load_kol import load_kol_raw  # noqa: E402
from scoring.score_kol import score_kol, write_score_to_db  # noqa: E402


def fetch_target_handles(limit: int | None = None) -> list[str]:
    """Return the list of handles to score: classified real-human ai-crypto KOLs."""
    c = get_client()
    q = (
        c.table("users")
        .select("handle")
        .eq("is_real_human", True)
        .eq("is_ai_crypto_focused", True)
        .order("handle")
    )
    if limit:
        q = q.limit(limit)
    else:
        q = q.limit(10000)  # explicit cap above expected 674
    r = q.execute()
    return [row["handle"] for row in r.data]


def score_one(handle: str) -> tuple[bool, str | None]:
    """Score one KOL and write to DB. Returns (success, error_msg)."""
    try:
        kol = load_kol_raw(handle)
        if kol is None:
            return False, "not found in users"
        result = score_kol(kol)
        write_score_to_db(result)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Score only first N handles")
    parser.add_argument("--handle", type=str, default=None, help="Score a single handle")
    args = parser.parse_args()

    if args.handle:
        handles = [args.handle.lstrip("@").lower()]
    else:
        handles = fetch_target_handles(args.limit)
        print(f"Fetched {len(handles)} scoring targets (is_real_human=True AND is_ai_crypto_focused=True)")

    t0 = time.time()
    ok = 0
    fail = 0
    errors: list[tuple[str, str]] = []

    for i, h in enumerate(handles, 1):
        success, err = score_one(h)
        if success:
            ok += 1
        else:
            fail += 1
            errors.append((h, err or "unknown"))

        if i % 50 == 0 or i == len(handles):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"  [{i}/{len(handles)}] ok={ok} fail={fail} ({rate:.1f}/s)")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Success: {ok}. Failed: {fail}.")

    if errors:
        print(f"\nFirst 10 errors:")
        for h, err in errors[:10]:
            print(f"  @{h}: {err}")

    # Summary stats from DB
    print("\n" + "=" * 60)
    print("Score distribution (from DB):")
    print("=" * 60)

    c = get_client()

    # Quality score distribution
    r = c.table("users").select("quality_score, quality_confidence").eq("is_real_human", True).eq("is_ai_crypto_focused", True).limit(10000).execute()
    q_scores = [row["quality_score"] for row in r.data if row["quality_score"] is not None]
    q_null = sum(1 for row in r.data if row["quality_score"] is None)
    q_conf = Counter(row["quality_confidence"] for row in r.data)

    print(f"\nQuality Score:")
    print(f"  computed: {len(q_scores)}   null: {q_null}")
    if q_scores:
        q_sorted = sorted(q_scores)
        n = len(q_sorted)
        print(f"  min={min(q_scores):.1f}  max={max(q_scores):.1f}  mean={sum(q_scores)/n:.1f}")
        print(f"  P25={q_sorted[n//4]:.1f}  P50={q_sorted[n//2]:.1f}  P75={q_sorted[3*n//4]:.1f}")
    print(f"  confidence: {dict(q_conf)}")

    # Cooperability score distribution
    r = c.table("users").select("cooperability_score, cooperability_confidence").eq("is_real_human", True).eq("is_ai_crypto_focused", True).limit(10000).execute()
    c_scores = [row["cooperability_score"] for row in r.data if row["cooperability_score"] is not None]
    c_null = sum(1 for row in r.data if row["cooperability_score"] is None)
    c_conf = Counter(row["cooperability_confidence"] for row in r.data)

    print(f"\nCooperability Score:")
    print(f"  computed: {len(c_scores)}   null: {c_null}")
    if c_scores:
        c_sorted = sorted(c_scores)
        n = len(c_sorted)
        print(f"  min={min(c_scores):.1f}  max={max(c_scores):.1f}  mean={sum(c_scores)/n:.1f}")
        print(f"  P25={c_sorted[n//4]:.1f}  P50={c_sorted[n//2]:.1f}  P75={c_sorted[3*n//4]:.1f}")
    print(f"  confidence: {dict(c_conf)}")

    # Top 10 by quality
    r = c.table("users").select("handle, tier, sector, quality_score, cooperability_score").eq("is_real_human", True).eq("is_ai_crypto_focused", True).not_.is_("quality_score", "null").order("quality_score", desc=True).limit(10).execute()
    print(f"\nTop 10 by Quality Score:")
    print(f"  {'handle':<22}{'tier':<8}{'sector':<28}{'Q':<8}{'C':<8}")
    for row in r.data:
        sector = (row["sector"] or "")[:27]
        q = row["quality_score"]
        cc = row["cooperability_score"]
        print(f"  @{row['handle']:<21}{row['tier'] or '?':<8}{sector:<28}{q:<8}{cc if cc is not None else 'null':<8}")

    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
