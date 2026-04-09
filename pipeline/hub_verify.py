"""
Hub Expansion Step 2: Mutual-follow verification.

For each top ultra_hub candidate, fetch their /following list (max 1000)
and check whether any of our 16 anchors OR previously-verified hubs appear
in it. If yes → we now have BOTH directions confirmed:
  - anchor → hub (already known from Step 1 hub discovery)
  - hub → anchor (confirmed here)
→ Upgrade hub to `is_mutual_member = True` and create a T1 mutual edge.

Cost model (Model A, X API v2 Basic tier paid):
  - Each /following call returns up to min(following_count, 1000) user records
  - $0.0088 per user returned
  - Example: hub with following=820 → ~$7.22 per call

Strategy:
  1. Load enriched hub profiles (pipeline/circles/hub_profiles_enriched.json)
  2. Filter: not celebrity, not known project/org, following_count in [50, 5000]
  3. Sort by anchor_count DESC (best signal first), then following_count ASC
  4. Process in batches of 10 so we can stop and report
  5. For each hub: fetch /following, check for anchors (+ previously confirmed hubs)
  6. Output: pipeline/circles/hub_verification.json with full results

Run in batches:
  python hub_verify.py --batch 1   # hubs 1-10
  python hub_verify.py --batch 2   # hubs 11-20
  python hub_verify.py --batch 3   # hubs 21-30

Resume-friendly: already-processed hubs are skipped.
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv

from x_client import XClient, XAPIError

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

HUB_PROFILES_FILE = ROOT / "pipeline" / "circles" / "hub_profiles_enriched.json"
CLASSIFIED_KOLS_FILE = ROOT / "pipeline" / "classified_kols.json"
UNIFIED_FILE = ROOT / "pipeline" / "circles" / "unified_16_anchor_matrix.json"
OUTPUT_FILE = ROOT / "pipeline" / "circles" / "hub_verification.json"

BATCH_SIZE = 10
TOP_N = 30  # hard cap for stage 1

# Known project/org handles — excluded from candidate pool (see analysis in previous turn)
KNOWN_PROJECT_HANDLES = {
    "binancezh", "a16zcrypto", "buidlpad", "aster_dex", "pharos_network", "zama",
    "miranetwork", "brevis_zk", "sentientagi", "openclaw", "gradient_hq", "jarsyinc",
    "techflowpost", "blocktvbee", "ccweb3hub", "hotpot_dao",
}
PROJECT_HANDLE_SUFFIXES = ["_dex", "_network", "_protocol", "_zk", "_labs", "_io",
                            "_finance", "_foundation"]


def is_likely_org(h: dict) -> bool:
    u = h["username"].lower()
    name = h.get("name") or ""
    bio = (h.get("description") or "").lower()
    if u in KNOWN_PROJECT_HANDLES:
        return True
    for s in PROJECT_HANDLE_SUFFIXES:
        if u.endswith(s):
            return True
    # Name is clearly a project (no person | brand separator, contains project keyword)
    if "｜" in name or "|" in name:
        return False
    project_kws = ["protocol", "network", "finance", "foundation", "labs",
                   "official", "mainnet", "launchpad"]
    n_lower = name.lower()
    if any(kw in n_lower for kw in project_kws):
        return True
    # Strong org bio patterns
    strong_bio_patterns = [
        r"(?i)^we(\'re|\s+are)\s+",
        r"(?i)\bofficial account\b",
        r"(?i)\bthe leading\b",
        r"(?i)\bjoin (our|the) discord\b",
    ]
    for p in strong_bio_patterns:
        if re.search(p, bio):
            return True
    return False


def build_candidate_list() -> list[dict]:
    """Return TOP_N candidates after filtering, sorted by anchor_count DESC."""
    data = json.loads(HUB_PROFILES_FILE.read_text())
    hubs = data["hubs"]

    # Celebrity threshold (same as build_graph.py)
    classified = json.loads(CLASSIFIED_KOLS_FILE.read_text())
    anchor_fc = [
        c.get("followers_count") or 0
        for c in classified.get("kols", [])
        if c.get("is_anchor")
    ]
    median_af = statistics.median(anchor_fc) if anchor_fc else 72000
    max_af = max(anchor_fc) if anchor_fc else 382000
    celeb_threshold = max(5 * median_af, 2 * max_af, 250_000)

    candidates = []
    for h in hubs:
        fc = h.get("followers_count") or 0
        following = h.get("following_count") or 0
        if fc >= celeb_threshold:
            continue
        if is_likely_org(h):
            continue
        if not (50 <= following <= 5000):
            continue
        candidates.append(h)

    # Sort: highest anchor_count first, then cheapest following_count
    candidates.sort(key=lambda h: (-h["anchor_count"], h["following_count"]))
    return candidates[:TOP_N]


def get_anchor_handles() -> set[str]:
    unified = json.loads(UNIFIED_FILE.read_text())
    anchors = set()
    for edge in unified.get("mutual_edges", []):
        anchors.add(edge["a"].lower())
        anchors.add(edge["b"].lower())
    for edge in unified.get("oneway_edges", []):
        anchors.add(edge["follower"].lower())
        anchors.add(edge["followee"].lower())
    return anchors


async def verify_hub(client: XClient, hub: dict, anchor_set: set[str], verified_hubs: set[str]) -> dict:
    """Fetch /following for a hub, check for anchor/verified-hub matches."""
    username = hub["username"]
    hub_id = hub["id"]
    expected_cost = min(hub["following_count"], 1000) * 0.0088

    t0 = time.time()
    try:
        following = await client.get_following(hub_id, max_total=1000)
    except XAPIError as e:
        return {
            "username": username,
            "anchor_count": hub["anchor_count"],
            "expected_cost_usd": expected_cost,
            "error": str(e)[:200],
            "verified": False,
            "mutual_anchors": [],
            "mutual_hubs": [],
        }
    elapsed = time.time() - t0

    following_usernames = {u["username"].lower() for u in following}
    mutual_anchors = sorted(following_usernames & anchor_set)
    mutual_hubs = sorted(following_usernames & verified_hubs)

    # Verified if hub follows AT LEAST ONE anchor (since anchors already follow them → mutual)
    verified = len(mutual_anchors) > 0

    actual_returned = len(following)
    actual_cost = actual_returned * 0.0088

    return {
        "username": username,
        "anchor_count": hub["anchor_count"],  # anchors that follow the hub
        "following_count_requested": hub["following_count"],
        "following_count_returned": actual_returned,
        "expected_cost_usd": round(expected_cost, 2),
        "actual_cost_usd": round(actual_cost, 2),
        "elapsed_sec": round(elapsed, 1),
        "verified": verified,
        "mutual_anchors": mutual_anchors,  # anchor handles that this hub follows
        "mutual_hubs": mutual_hubs,  # previously-verified hubs this hub also follows
        "error": None,
    }


def load_state() -> dict:
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text())
    return {
        "batches_run": [],
        "results": [],
        "total_cost_usd": 0.0,
        "verified_count": 0,
    }


def save_state(state: dict) -> None:
    OUTPUT_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


async def run_batch(batch_num: int) -> int:
    print("=" * 72)
    print(f"HUB VERIFICATION — Batch {batch_num} (hubs {(batch_num - 1) * BATCH_SIZE + 1}-{batch_num * BATCH_SIZE})")
    print("=" * 72)

    all_candidates = build_candidate_list()
    print(f"Total clean candidates: {len(all_candidates)} (Top {TOP_N} selected)")

    start = (batch_num - 1) * BATCH_SIZE
    end = start + BATCH_SIZE
    batch_hubs = all_candidates[start:end]
    if not batch_hubs:
        print(f"No hubs in batch {batch_num} (end of list)")
        return 0

    state = load_state()
    already_done = {r["username"] for r in state["results"]}
    pending = [h for h in batch_hubs if h["username"] not in already_done]
    print(f"Batch size: {len(batch_hubs)}, already done: {len(batch_hubs) - len(pending)}, running: {len(pending)}")
    if not pending:
        print("All hubs in this batch already processed.")
        _report_summary(state, batch_hubs)
        return 0

    anchor_set = get_anchor_handles()
    verified_hubs = {
        r["username"] for r in state["results"] if r.get("verified")
    }
    print(f"Anchors in set: {len(anchor_set)}")
    print(f"Previously verified hubs: {len(verified_hubs)}")
    print()

    # Estimated cost for this batch
    est_cost = sum(h.get("expected_cost_usd", min(h["following_count"], 1000) * 0.0088) for h in pending)
    total_expected = sum(min(h["following_count"], 1000) * 0.0088 for h in pending)
    print(f"Estimated batch cost: ${total_expected:.2f}")
    print()

    async with XClient() as client:
        for i, hub in enumerate(pending, 1):
            print(f"  [{i}/{len(pending)}] @{hub['username']:<22} ac={hub['anchor_count']:>2}/16 fc={hub['following_count']:>5} (~${min(hub['following_count'], 1000) * 0.0088:.2f})...", flush=True)
            result = await verify_hub(client, hub, anchor_set, verified_hubs)
            status = "✅" if result["verified"] else ("⚠️" if result.get("error") else "❌")
            extra = ""
            if result["verified"]:
                extra = f" → mutual w/ {','.join(result['mutual_anchors'][:4])}"
                if result["mutual_hubs"]:
                    extra += f" +hubs: {','.join(result['mutual_hubs'][:3])}"
            elif result.get("error"):
                extra = f" error: {result['error'][:80]}"
            print(f"     {status} returned={result.get('following_count_returned', 0)} cost=${result.get('actual_cost_usd', 0):.2f}{extra}")

            state["results"].append(result)
            state["total_cost_usd"] = round(state["total_cost_usd"] + result.get("actual_cost_usd", 0), 2)
            if result["verified"]:
                state["verified_count"] += 1
                verified_hubs.add(result["username"])
            save_state(state)  # checkpoint after every hub

    if batch_num not in state["batches_run"]:
        state["batches_run"].append(batch_num)
        save_state(state)

    _report_summary(state, batch_hubs)
    return 0


def _report_summary(state: dict, current_batch: list[dict]) -> None:
    print()
    print("=" * 72)
    print("BATCH REPORT")
    print("=" * 72)

    processed_total = len(state["results"])
    verified_total = sum(1 for r in state["results"] if r.get("verified"))
    errors_total = sum(1 for r in state["results"] if r.get("error"))
    hit_rate_total = (verified_total / processed_total * 100) if processed_total else 0
    print(f"Total processed so far: {processed_total}")
    print(f"Total verified (mutual): {verified_total} ({hit_rate_total:.0f}% hit rate)")
    print(f"Total errors: {errors_total}")
    print(f"Total cost so far: ${state['total_cost_usd']:.2f}")
    print()

    # This batch specifically
    batch_usernames = {h["username"] for h in current_batch}
    batch_results = [r for r in state["results"] if r["username"] in batch_usernames]
    batch_verified = sum(1 for r in batch_results if r.get("verified"))
    batch_cost = sum(r.get("actual_cost_usd", 0) for r in batch_results)
    print(f"This batch: {batch_verified}/{len(batch_results)} verified ({(batch_verified/max(len(batch_results),1))*100:.0f}% hit rate), cost ${batch_cost:.2f}")
    print()

    # Show verified hubs from this batch
    newly_verified = [r for r in batch_results if r.get("verified")]
    if newly_verified:
        print("✅ Newly verified mutual hubs (this batch):")
        for r in newly_verified:
            print(f"   @{r['username']:<22} → follows {len(r['mutual_anchors'])} anchors: {','.join(r['mutual_anchors'][:6])}")

    not_verified = [r for r in batch_results if not r.get("verified") and not r.get("error")]
    if not_verified:
        print()
        print("❌ Not verified (no mutual follow detected):")
        for r in not_verified:
            print(f"   @{r['username']:<22} follows 0/{len(get_anchor_handles())} anchors (fetched {r.get('following_count_returned', 0)} users)")

    errors = [r for r in batch_results if r.get("error")]
    if errors:
        print()
        print("⚠️  Errors:")
        for r in errors:
            print(f"   @{r['username']:<22} {r['error']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True, help="Batch number (1, 2, 3)")
    args = parser.parse_args()

    if args.batch not in [1, 2, 3]:
        print(f"Invalid batch: {args.batch}. Must be 1, 2, or 3.")
        return 1

    return asyncio.run(run_batch(args.batch))


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
