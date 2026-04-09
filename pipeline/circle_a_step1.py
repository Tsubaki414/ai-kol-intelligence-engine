"""
Phase 3 — Circle A, Step 1: pull /following for 6 Chinese AI Agent anchors.

STOP-AND-REPORT protocol: runs ONE step, reports, waits for user approval.
Does NOT proceed to Step 2 automatically.

Circle A anchors (CLAUDE.md v3.1 §Phase 3 Scope):
    @yanhua1010, @caelynzh, @jingyuan_521, @0xzagen, @sunnyheima, @sanbuphy

Output: pipeline/circle_a_step1.json
    - Per-anchor following list (lowercase usernames)
    - Anchor-to-anchor mutual follow matrix (15 pairs)
    - Mutual follow density %
    - Exact API cost (Model A: $0.0088 per user returned)

Run:
    pipeline/.venv/bin/python pipeline/circle_a_step1.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from x_client import XAPIError, XClient

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "pipeline" / "circle_a_step1.json"

# Circle A anchors (Chinese AI Agent Mainland).
# IDs already resolved in v1 Phase 1a, reused to save a user_by_login lookup.
CIRCLE_A = [
    ("yanhua1010", "1932935705711513600"),
    ("caelynzh", "1680219166622773249"),
    ("jingyuan_521", "1820869948975280130"),
    ("0xzagen", "1496405845504327680"),
    ("sunnyheima", "1409814826885402626"),
    ("sanbuphy", "1611582713550770177"),
]

MAX_PER_ANCHOR = 1000  # Circle A anchors are Micro/Macro, 1 page should cover full list
MODEL_A_PRICE = 0.0088  # $ per user returned (empirically derived from v1 $25 / 2853 users)


async def main() -> int:
    print("=" * 64)
    print("STEP 1 — Circle A anchor /following fetch (6 anchors)")
    print("Protocol: STOP after this step, do NOT auto-advance")
    print("=" * 64)
    print()

    anchor_following: dict[str, set[str]] = {}
    anchor_counts: dict[str, int] = {}
    total_users_returned = 0
    errors: list[dict] = []

    async with XClient() as x:
        for i, (handle, uid) in enumerate(CIRCLE_A, 1):
            try:
                print(f"  [{i}/6] @{handle:<15} (id={uid}) max={MAX_PER_ANCHOR}...", end=" ", flush=True)
                following = await x.get_following(uid, max_total=MAX_PER_ANCHOR)
                count = len(following)
                anchor_following[handle] = {u["username"].lower() for u in following}
                anchor_counts[handle] = count
                total_users_returned += count
                print(f"got {count}")
            except XAPIError as e:
                print(f"ERROR: {e}")
                errors.append({"anchor": handle, "error": str(e)})
                anchor_following[handle] = set()
                anchor_counts[handle] = 0

    api_cost = total_users_returned * MODEL_A_PRICE

    print()
    print("=" * 64)
    print("=== PER-ANCHOR BREAKDOWN ===")
    for handle, count in anchor_counts.items():
        cost = count * MODEL_A_PRICE
        print(f"  @{handle:<14} {count:>5} follows  ${cost:>6.2f}")
    print(f"  {'─' * 40}")
    print(f"  {'TOTAL':<15} {total_users_returned:>5} users    ${api_cost:>6.2f}")

    if errors:
        print(f"\n  ⚠️ Errors: {len(errors)}")
        for e in errors:
            print(f"    @{e['anchor']}: {e['error']}")

    print()
    print("=== ANCHOR-TO-ANCHOR MUTUAL FOLLOW MATRIX ===")
    print("(15 possible pairs among 6 anchors)")
    print()

    handles = list(anchor_following.keys())
    mutual_pairs: list[tuple[str, str]] = []
    one_way_pairs: list[tuple[str, str, str]] = []
    no_conn_pairs: list[tuple[str, str]] = []

    for i in range(len(handles)):
        for j in range(i + 1, len(handles)):
            a = handles[i]
            b = handles[j]
            a_follows_b = b.lower() in anchor_following.get(a, set())
            b_follows_a = a.lower() in anchor_following.get(b, set())

            if a_follows_b and b_follows_a:
                mutual_pairs.append((a, b))
                marker = "✅ MUTUAL"
            elif a_follows_b:
                one_way_pairs.append((a, b, f"{a}→{b}"))
                marker = f"→   @{a} → @{b} (one-way)"
            elif b_follows_a:
                one_way_pairs.append((a, b, f"{b}→{a}"))
                marker = f"←   @{b} → @{a} (one-way)"
            else:
                no_conn_pairs.append((a, b))
                marker = "✗   no connection"
            print(f"  @{a:<13} ↔ @{b:<14} {marker}")

    total_pairs = len(handles) * (len(handles) - 1) // 2
    mutual_density = (len(mutual_pairs) / total_pairs * 100) if total_pairs else 0

    print()
    print("=== CIRCLE A COHESION ===")
    print(f"  Total pairs:        {total_pairs}")
    print(f"  Mutual follows:     {len(mutual_pairs)} ({mutual_density:.0f}%)")
    print(f"  One-way follows:    {len(one_way_pairs)}")
    print(f"  No connection:      {len(no_conn_pairs)}")
    print()

    if mutual_density >= 50:
        verdict = "✅ HIGH DENSITY (≥50%) — Circle A is well-grouped. Safe to proceed to Step 2 (find expansion candidates)."
    elif mutual_density >= 30:
        verdict = "🟡 MEDIUM DENSITY (30-50%) — Acceptable but expansion may be sparse. User should decide."
    else:
        verdict = "🔴 LOW DENSITY (<30%) — Circle A is badly grouped. Consider regrouping anchors before expanding."

    print(f"  VERDICT: {verdict}")
    print()

    # Save state for Step 2
    state = {
        "step": 1,
        "circle": "A",
        "anchors": handles,
        "anchor_counts": anchor_counts,
        "anchor_following": {h: sorted(list(f)) for h, f in anchor_following.items()},
        "mutual_pairs": [list(p) for p in mutual_pairs],
        "one_way_pairs": [{"a": p[0], "b": p[1], "direction": p[2]} for p in one_way_pairs],
        "no_connection_pairs": [list(p) for p in no_conn_pairs],
        "mutual_density_pct": round(mutual_density, 1),
        "total_users_returned": total_users_returned,
        "api_cost_usd": round(api_cost, 2),
        "errors": errors,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(f"  State saved: {OUTPUT_FILE.name}")
    print()
    print("=" * 64)
    print("⛔ STEP 1 COMPLETE. STOP. Wait for user 'continue' before Step 2.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
