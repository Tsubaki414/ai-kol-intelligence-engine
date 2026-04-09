"""
Generic circle expansion pipeline — parameterized input, stop-and-report protocol.

Reads a circle config (JSON) and executes one step at a time.
Each step saves state to pipeline/circles/{circle_name}_step{N}.json and STOPS.
Does NOT auto-advance.

Usage:
    # Step 1: fetch /following for all anchors + compute mutual matrix
    python pipeline/circle_expand.py step1 --config pipeline/circles/my_circle.json

    # Step 2: find expansion candidates (followed by >= min_anchors of N anchors)
    #         zero-cost, pure analysis of Step 1 output
    python pipeline/circle_expand.py step2 --circle my_circle --min-anchors 3

    # Step 3: fetch /following for approved candidates (batched, stops after each batch)
    python pipeline/circle_expand.py step3 --circle my_circle --candidates file.json --batch-size 5 --batch 1

Config format:
    {
      "circle_name": "descriptive_snake_case_name",
      "created": "YYYY-MM-DD",
      "status": "active",
      "hypothesis": "Why these anchors are expected to form a circle",
      "anchors": [
        {"handle": "username", "id": "1234567890", "note": "optional context"},
        ...
      ]
    }

IMPORTANT — the root meta-error:
    Anchors MUST come from a ground-truth source (Grok real-mutual-follow query,
    user-imported handles, or verified project team members). They must NOT come
    from "same sector label" or "same keyword". If you group by proxy signals
    the circle will fail with 0% density and waste $36.
    See CLAUDE.md §ROOT META-ERROR.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from x_client import XAPIError, XClient

ROOT = Path(__file__).resolve().parent.parent
CIRCLES_DIR = ROOT / "pipeline" / "circles"
MAX_PER_ANCHOR = 1000
MODEL_A_PRICE_PER_USER = 0.0088  # $ per user returned (empirical from v1 $25 / 2853 users)


# ============================================================================
# Helpers
# ============================================================================


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open() as f:
        return json.load(f)


def save_state(circle_name: str, step: int, state: dict) -> Path:
    CIRCLES_DIR.mkdir(parents=True, exist_ok=True)
    path = CIRCLES_DIR / f"{circle_name}_step{step}.json"
    with path.open("w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return path


def load_state(circle_name: str, step: int) -> dict:
    path = CIRCLES_DIR / f"{circle_name}_step{step}.json"
    if not path.exists():
        raise FileNotFoundError(f"Step {step} state missing for circle '{circle_name}': {path}")
    with path.open() as f:
        return json.load(f)


def lower_username_set(following_list: list[dict]) -> set[str]:
    return {u.get("username", "").lower() for u in following_list if u.get("username")}


# ============================================================================
# STEP 1 — Fetch anchor /following + compute mutual matrix
# ============================================================================


def _load_reuse_data(reuse_from: str, handle: str) -> dict | None:
    """
    Load anchor following data from a previous step1 state file.
    Supports two formats:
      - new format: state["anchor_data"][handle] = {id, count, following: [...full profiles]}
      - old format: state["anchor_following"][handle] = [list of usernames only]
    """
    path = ROOT / reuse_from
    if not path.exists():
        return None
    with path.open() as f:
        prev = json.load(f)

    # Try new format first
    if "anchor_data" in prev and handle in prev["anchor_data"]:
        return prev["anchor_data"][handle]

    # Fall back to old format (just usernames, reconstruct minimal profile entries)
    if "anchor_following" in prev and handle in prev["anchor_following"]:
        usernames = prev["anchor_following"][handle]
        return {
            "id": None,
            "count": len(usernames),
            "_lite_format": True,
            "following": [
                {
                    "id": None,
                    "username": u.lower(),
                    "name": None,
                    "description": "",
                    "verified": False,
                    "public_metrics": {},
                }
                for u in usernames
            ],
        }

    return None


async def step1(config: dict) -> dict:
    circle_name = config["circle_name"]
    anchors = config["anchors"]
    hypothesis = config.get("hypothesis", "(none)")

    print("=" * 72)
    print(f"STEP 1 — Circle '{circle_name}' anchor /following fetch")
    print(f"Anchors: {len(anchors)}")
    print(f"Hypothesis: {hypothesis}")
    print("Protocol: STOP after this step, do NOT auto-advance")
    print("=" * 72)
    print()

    anchor_data: dict[str, dict] = {}
    total_users_paid = 0  # Only counts NEW api calls, not reused data
    reused_count = 0
    errors: list[dict] = []

    async with XClient() as x:
        for i, anchor in enumerate(anchors, 1):
            handle = anchor["handle"]
            uid = anchor.get("id")
            reuse_from = anchor.get("reuse_from")

            # 1. Resolve ID if missing (cheap user_by_username call)
            if not uid:
                print(f"  [{i}/{len(anchors)}] @{handle:<16} resolving id...", end=" ", flush=True)
                try:
                    user = await x.get_user_by_username(handle)
                    if not user:
                        print("NOT FOUND")
                        errors.append({"handle": handle, "error": "user not found"})
                        anchor_data[handle] = {"id": None, "count": 0, "following": []}
                        continue
                    uid = user["id"]
                    print(f"id={uid}")
                except XAPIError as e:
                    print(f"LOOKUP ERROR: {e}")
                    errors.append({"handle": handle, "error": f"id lookup: {e}"})
                    anchor_data[handle] = {"id": None, "count": 0, "following": []}
                    continue

            # 2. Try reuse from previous state file (free)
            if reuse_from:
                reused = _load_reuse_data(reuse_from, handle)
                if reused:
                    reused["id"] = uid  # ensure id is set
                    anchor_data[handle] = reused
                    reused_count += 1
                    fmt = "lite" if reused.get("_lite_format") else "full"
                    print(
                        f"  [{i}/{len(anchors)}] @{handle:<16} REUSED ({fmt}, {reused['count']} follows) "
                        f"from {reuse_from}"
                    )
                    continue
                else:
                    print(
                        f"  [{i}/{len(anchors)}] @{handle:<16} reuse_from={reuse_from} "
                        f"NOT FOUND, falling back to fresh fetch"
                    )

            # 3. Fresh fetch
            try:
                print(f"  [{i}/{len(anchors)}] @{handle:<16} id={uid}...", end=" ", flush=True)
                following = await x.get_following(uid, max_total=MAX_PER_ANCHOR)
                count = len(following)
                anchor_data[handle] = {
                    "id": uid,
                    "count": count,
                    "following": [
                        {
                            "id": u.get("id"),
                            "username": (u.get("username") or "").lower(),
                            "name": u.get("name"),
                            "description": (u.get("description") or "")[:500],
                            "verified": u.get("verified", False),
                            "public_metrics": u.get("public_metrics", {}),
                        }
                        for u in following
                    ],
                }
                total_users_paid += count
                print(f"got {count}")
            except XAPIError as e:
                print(f"ERROR: {e}")
                errors.append({"handle": handle, "error": str(e)})
                anchor_data[handle] = {"id": uid, "count": 0, "following": []}

    api_cost = round(total_users_paid * MODEL_A_PRICE_PER_USER, 2)

    # Compute mutual-follow matrix among anchors
    handles = [a["handle"] for a in anchors]
    anchor_username_sets = {
        h: lower_username_set(anchor_data[h]["following"]) for h in handles
    }

    mutual_pairs: list[list[str]] = []
    one_way_pairs: list[dict] = []
    no_connection: list[list[str]] = []

    for i in range(len(handles)):
        for j in range(i + 1, len(handles)):
            a, b = handles[i], handles[j]
            a_follows_b = b.lower() in anchor_username_sets[a]
            b_follows_a = a.lower() in anchor_username_sets[b]

            if a_follows_b and b_follows_a:
                mutual_pairs.append([a, b])
            elif a_follows_b:
                one_way_pairs.append({"follower": a, "followee": b})
            elif b_follows_a:
                one_way_pairs.append({"follower": b, "followee": a})
            else:
                no_connection.append([a, b])

    total_pairs = len(handles) * (len(handles) - 1) // 2
    density = (len(mutual_pairs) / total_pairs * 100) if total_pairs else 0

    state = {
        "step": 1,
        "circle_name": circle_name,
        "hypothesis": hypothesis,
        "anchors": handles,
        "anchor_data": anchor_data,
        "mutual_pairs": mutual_pairs,
        "one_way_pairs": one_way_pairs,
        "no_connection_pairs": no_connection,
        "mutual_density_pct": round(density, 1),
        "total_users_paid_for": total_users_paid,
        "reused_anchor_count": reused_count,
        "api_cost_usd": api_cost,
        "errors": errors,
    }

    path = save_state(circle_name, 1, state)

    # Report
    print()
    print("=== COST BREAKDOWN ===")
    for h in handles:
        d = anchor_data[h]
        c = d["count"]
        is_reused = d.get("_lite_format") or h in {a["handle"] for a in anchors if a.get("reuse_from")}
        cost = 0.0 if is_reused else c * MODEL_A_PRICE_PER_USER
        marker = "  [REUSED]" if is_reused else ""
        print(f"  @{h:<16} {c:>5} follows   ${cost:>6.2f}{marker}")
    print(f"  {'─' * 56}")
    print(f"  {'NEW PAID':<17} {total_users_paid:>5} users     ${api_cost:>6.2f}")
    if reused_count > 0:
        print(f"  {'REUSED':<17} {reused_count:>5} anchors   $  0.00")

    if errors:
        print(f"\n  Errors: {len(errors)}")
        for e in errors:
            print(f"    @{e['handle']}: {e['error']}")

    print()
    print("=== ANCHOR-TO-ANCHOR MUTUAL FOLLOW MATRIX ===")
    print(f"  Total pairs:      {total_pairs}")
    print(f"  Mutual follows:   {len(mutual_pairs)} ({density:.0f}%)")
    print(f"  One-way follows:  {len(one_way_pairs)}")
    print(f"  No connection:    {len(no_connection)}")
    print()

    if density >= 50:
        verdict = "✅ HIGH DENSITY — circle input is valid. Proceed to step2."
    elif density >= 30:
        verdict = "🟡 MEDIUM DENSITY — borderline. User decides whether to proceed."
    else:
        verdict = (
            "🔴 LOW DENSITY — INPUT IS BAD, not the algorithm.\n"
            "     Do NOT regroup by another proxy signal (that's the root meta-error).\n"
            "     Obtain ground-truth anchors: Grok real-mutual-follow query OR user-imported."
        )
    print(f"  VERDICT: {verdict}")
    print()
    print(f"State saved: {path}")
    print("⛔ STOP. Report to user. Do NOT execute step2 automatically.")
    return state


# ============================================================================
# STEP 2 — Find expansion candidates (zero-cost analysis)
# ============================================================================


def step2(circle_name: str, min_anchors: int = 3) -> dict:
    step1_state = load_state(circle_name, 1)
    handles = step1_state["anchors"]
    anchor_data = step1_state["anchor_data"]

    print("=" * 72)
    print(f"STEP 2 — Circle '{circle_name}' expansion candidates")
    print(f"Threshold: candidates followed by ≥{min_anchors} of {len(handles)} anchors")
    print("Cost: $0 (pure analysis of step1 data)")
    print("=" * 72)
    print()

    # Count how many anchors follow each account
    from collections import Counter
    follower_map: dict[str, set[str]] = {}  # username -> set of anchor handles following them
    for h in handles:
        for u in anchor_data[h]["following"]:
            username = u["username"].lower()
            if username not in follower_map:
                follower_map[username] = set()
            follower_map[username].add(h)

    # Remove anchors themselves from candidate pool
    anchor_set = {h.lower() for h in handles}
    filtered = {u: s for u, s in follower_map.items() if u not in anchor_set}

    # Histogram
    histogram = Counter(len(s) for s in filtered.values())
    print("Histogram (unique non-anchor accounts followed by N anchors):")
    for n in sorted(histogram.keys(), reverse=True):
        print(f"  followed by {n}/{len(handles)}: {histogram[n]:>5} accounts")
    print(f"  total unique candidates: {len(filtered)}")
    print()

    # Pull candidates meeting threshold + enrich with profile data from anchor_data
    candidate_list = []
    for username, anchor_set_following in filtered.items():
        if len(anchor_set_following) < min_anchors:
            continue
        # Find the profile (any anchor that follows them has the data)
        profile = None
        for h in anchor_set_following:
            for u in anchor_data[h]["following"]:
                if u["username"].lower() == username:
                    profile = u
                    break
            if profile:
                break
        candidate_list.append(
            {
                "username": username,
                "followed_by_anchors": sorted(anchor_set_following),
                "anchor_count": len(anchor_set_following),
                "profile": profile,
            }
        )

    candidate_list.sort(
        key=lambda c: (
            -c["anchor_count"],
            -(c["profile"]["public_metrics"].get("followers_count", 0) if c["profile"] else 0),
        )
    )

    state = {
        "step": 2,
        "circle_name": circle_name,
        "min_anchors_threshold": min_anchors,
        "total_candidates": len(candidate_list),
        "histogram": {str(k): v for k, v in histogram.items()},
        "candidates": candidate_list,
    }

    path = save_state(circle_name, 2, state)

    print(f"=== TOP CANDIDATES (≥{min_anchors} anchors) ===")
    for i, c in enumerate(candidate_list[:30], 1):
        p = c["profile"] or {}
        m = p.get("public_metrics", {})
        bio = (p.get("description") or "")[:60]
        print(
            f"  {i:2d}. @{c['username']:<22} [{c['anchor_count']}/{len(handles)}]  "
            f"{m.get('followers_count', 0):>8,} followers — {bio}"
        )
    if len(candidate_list) > 30:
        print(f"  ... ({len(candidate_list) - 30} more)")
    print()
    print(f"State saved: {path}")
    print("⛔ STOP. User reviews candidate list. Do NOT execute step3 automatically.")
    return state


# ============================================================================
# CLI entry point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Generic circle expansion pipeline (stop-and-report protocol)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("step1", help="Fetch /following for anchors + mutual matrix")
    p1.add_argument("--config", required=True, type=Path)

    p2 = sub.add_parser("step2", help="Find expansion candidates (zero-cost)")
    p2.add_argument("--circle", required=True, help="circle_name from step1 state")
    p2.add_argument("--min-anchors", type=int, default=3)

    args = parser.parse_args()

    if args.command == "step1":
        config = load_config(args.config)
        asyncio.run(step1(config))
    elif args.command == "step2":
        step2(args.circle, args.min_anchors)


if __name__ == "__main__":
    main()
