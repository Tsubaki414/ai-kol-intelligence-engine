"""
Resume classification: pick up the 2400 candidates that failed due to credit exhaustion.

Strategy:
1. Load existing classified_kols.json (318 humans) + classified_orgs.json (1779 orgs)
   → already processed usernames
2. Re-run the same candidate loading + pre-filter pipeline
3. Skip anything already processed
4. Run Claude classification on the remaining
5. Append to classified_kols.json (humans) and classified_orgs.json (orgs)
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from anthropic import AsyncAnthropic

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "pipeline"))
from classify_and_score import (
    CLAUDE_MODEL,
    CLAUDE_SYSTEM_PROMPT,
    MAX_CONCURRENT,
    CHECKPOINT_EVERY,
    build_user_prompt,
    parse_claude_response,
    load_all_candidates,
    pre_filter_and_rank,
    get_anchor_handles,
)

HUMANS_FILE = ROOT / "pipeline" / "classified_kols.json"
ORGS_FILE = ROOT / "pipeline" / "classified_orgs.json"
CHECKPOINT = ROOT / "pipeline" / "classified_checkpoint.json"


async def classify_one(client, candidate, semaphore):
    async with semaphore:
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=900,
                system=CLAUDE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": build_user_prompt(candidate["profile"])}
                ],
            )
            text = response.content[0].text
            parsed = parse_claude_response(text)
            if not parsed:
                return {"username": candidate["username"], "error": "parse_failed"}
            profile = candidate["profile"]
            metrics = profile.get("public_metrics", {}) or {}
            return {
                "username": candidate["username"],
                "id": profile.get("id"),
                "name": profile.get("name"),
                "bio": profile.get("description"),
                "followers_count": metrics.get("followers_count"),
                "following_count": metrics.get("following_count"),
                "tweet_count": metrics.get("tweet_count"),
                "verified": profile.get("verified", False),
                "source": profile.get("_source", ""),
                "x_url": f"https://x.com/{candidate['username']}",
                "is_anchor": candidate.get("is_anchor", False),
                **parsed,
            }
        except Exception as e:
            return {"username": candidate["username"], "error": str(e)[:200]}


async def main():
    print("=" * 72)
    print("RESUME classification — pick up where credit-exhaustion left off")
    print("=" * 72)

    # Load existing classified entries
    existing_humans = json.loads(HUMANS_FILE.read_text()).get("kols", [])
    existing_orgs = json.loads(ORGS_FILE.read_text()) if ORGS_FILE.exists() else []
    processed_usernames = {k["username"] for k in existing_humans}
    processed_usernames |= {k.get("username") for k in existing_orgs if isinstance(k, dict) and k.get("username")}
    print(f"Already processed: {len(processed_usernames)} candidates")
    print(f"  Humans: {len(existing_humans)}")
    print(f"  Orgs:   {len(existing_orgs)}")

    # Re-load candidate pool
    print("\nLoading candidate pool...")
    pool = load_all_candidates()
    anchors = get_anchor_handles()
    candidates, _ = pre_filter_and_rank(pool, anchors)
    print(f"Pool size: {len(pool)}  Pre-filtered: {len(candidates)}")

    # Skip already processed
    remaining = [c for c in candidates if c["username"] not in processed_usernames]
    print(f"Remaining to classify: {len(remaining)}")

    if not remaining:
        print("Nothing to do — everything already classified.")
        return 0

    # Ensure we respect the original 4500 cap (skip below-priority candidates)
    cap = 4500
    if len(remaining) + len(processed_usernames) > cap:
        # Prefer high-priority remaining; cap = cap - already_processed
        budget = max(0, cap - len(processed_usernames))
        # But respect the existing priority order
        remaining = remaining[:budget]
        print(f"Capped to budget={budget} (total cap={cap})")

    client = AsyncAnthropic()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    humans = []
    orgs = []
    errors = []
    processed = 0
    start = time.time()

    tasks = [classify_one(client, c, semaphore) for c in remaining]

    for coro in asyncio.as_completed(tasks):
        result = await coro
        processed += 1

        if not result or "error" in result:
            errors.append(result)
        elif result.get("is_organization_account") or not result.get("is_real_human"):
            orgs.append(result)
        elif not result.get("is_ai_crypto_focused"):
            orgs.append({**result, "_filter_reason": "not_ai_crypto_focused"})
        else:
            humans.append(result)

        if processed % CHECKPOINT_EVERY == 0 or processed == len(remaining):
            elapsed = time.time() - start
            rate = processed / max(elapsed, 0.01)
            eta = (len(remaining) - processed) / max(rate, 0.01)
            print(
                f"  [{processed}/{len(remaining)}] new humans={len(humans)} "
                f"new orgs={len(orgs)} errors={len(errors)} "
                f"({rate:.1f}/s eta {eta:.0f}s)"
            )

    # Merge into existing files
    all_humans = existing_humans + humans
    all_humans.sort(key=lambda k: -(k.get("overall_score") or 0))

    existing_doc = json.loads(HUMANS_FILE.read_text())
    existing_doc["kols"] = all_humans
    existing_doc["metadata"]["total"] = len(all_humans)
    existing_doc["metadata"]["resume_applied"] = True
    existing_doc["metadata"]["resume_added_humans"] = len(humans)
    HUMANS_FILE.write_text(json.dumps(existing_doc, indent=2, ensure_ascii=False, default=str))

    all_orgs = existing_orgs + orgs
    ORGS_FILE.write_text(json.dumps(all_orgs, indent=2, ensure_ascii=False, default=str))

    print()
    print("=" * 72)
    print("RESUME RESULTS")
    print("=" * 72)
    print(f"New humans added:      {len(humans)}")
    print(f"New orgs filtered:     {len(orgs)}")
    print(f"Errors:                {len(errors)}")
    print(f"Total humans in kols:  {len(all_humans)}")
    print(f"Total orgs in file:    {len(all_orgs)}")
    print(f"Elapsed:               {(time.time() - start)/60:.1f} min")

    if humans:
        from collections import Counter
        print("\nNew KOL distribution:")
        print(f"  Languages: {dict(Counter(h.get('language') for h in humans))}")
        print(f"  Tiers:     {dict(Counter(h.get('tier') for h in humans))}")
        print(f"  Sectors:   {dict(Counter(h.get('sector') for h in humans))}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
