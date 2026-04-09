"""
Migrate hub_verification.json results into Supabase `follows` table.

Context: `pipeline/hub_verify.py` verified that 12 hub accounts follow back
the anchors that were following them. Pre-existing `follows` rows capture
anchor → hub direction; this script adds the confirmed hub → anchor reverse
direction, which upgrades those 12 hubs from "watched" to "mutual member"
in the `mutual_follows` view.

Also adds hub → hub edges discovered during verification (when one
verified hub's /following list contained another verified hub, we detected
a mutual hub↔hub relationship that wasn't visible before).

Idempotent — uses upsert, safe to re-run.

Run:
    pipeline/.venv/bin/python pipeline/migrate_hub_verification.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from anywhere: `python pipeline/migrate_hub_verification.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.db import get_client

ROOT = Path(__file__).resolve().parent.parent
HUB_VERIFY_FILE = ROOT / "pipeline" / "circles" / "hub_verification.json"
SOURCE_TAG = "hub_verify_2026-04-09"


def main() -> int:
    print("=" * 72)
    print("Migrate hub_verification.json → Supabase follows table")
    print("=" * 72)

    data = json.loads(HUB_VERIFY_FILE.read_text())
    verified = [r for r in data["results"] if r.get("verified")]
    print(f"Loaded {len(data['results'])} hub verification results")
    print(f"  → {len(verified)} verified (hub follows ≥ 1 anchor)")
    print()

    sb = get_client()

    # Pre-fetch existing follows for all involved handles so we can report
    # new vs already-present.
    involved = set()
    for r in verified:
        involved.add(r["username"])
        involved.update(r.get("mutual_anchors", []))
        involved.update(r.get("mutual_hubs", []))

    print(f"Involved handles: {len(involved)}")

    # Build the new edges to insert
    new_edges: list[dict] = []
    hub_anchor_pairs = 0
    hub_hub_pairs = 0

    for r in verified:
        hub = r["username"].lower()

        # hub → anchor reverse-direction edges
        for anchor in r.get("mutual_anchors", []):
            anchor = anchor.lower()
            new_edges.append({
                "follower_handle": hub,
                "followee_handle": anchor,
                "source": SOURCE_TAG,
            })
            hub_anchor_pairs += 1

        # hub → hub edges (both directions aren't both captured here; we only
        # know "this hub follows that hub". The reverse will show up when the
        # OTHER hub was verified.)
        for other_hub in r.get("mutual_hubs", []):
            other_hub = other_hub.lower()
            new_edges.append({
                "follower_handle": hub,
                "followee_handle": other_hub,
                "source": SOURCE_TAG,
            })
            hub_hub_pairs += 1

    print(f"New edges to upsert: {len(new_edges)}")
    print(f"  hub → anchor: {hub_anchor_pairs}")
    print(f"  hub → other_hub: {hub_hub_pairs}")
    print()

    # Pre-count existing edges for the same (follower, followee) keys so we
    # can report "N newly inserted" vs "M already present".
    preexisting_check = sb.table("follows").select("follower_handle,followee_handle").in_(
        "follower_handle", [e["follower_handle"] for e in new_edges]
    ).execute()
    existing_pairs = {
        (r["follower_handle"], r["followee_handle"])
        for r in preexisting_check.data
    }
    new_pairs = {(e["follower_handle"], e["followee_handle"]) for e in new_edges}
    truly_new = new_pairs - existing_pairs
    already_present = new_pairs & existing_pairs
    print(f"Pre-upsert check:")
    print(f"  truly new (will insert): {len(truly_new)}")
    print(f"  already present (idempotent no-op): {len(already_present)}")
    print()

    # Upsert (idempotent — primary key is (follower_handle, followee_handle))
    CHUNK = 500
    upserted = 0
    for i in range(0, len(new_edges), CHUNK):
        batch = new_edges[i : i + CHUNK]
        result = sb.table("follows").upsert(batch, on_conflict="follower_handle,followee_handle").execute()
        upserted += len(result.data)
    print(f"Upserted {upserted} rows into follows table.")
    print()

    # Verify: count follows + mutual_follows after migration
    before_count_stmt = sb.table("follows").select("*", count="exact").limit(0).execute()
    print(f"follows table row count (post-migration): {before_count_stmt.count}")

    mutual_check = sb.rpc("count_mutual_follows").execute() if False else None
    # mutual_follows is a view; count via direct select
    mv = sb.table("mutual_follows").select("handle_a", count="exact").limit(0).execute()
    print(f"mutual_follows view row count (post-migration): {mv.count}")
    print()

    # Per-hub report: which new mutual pairs did each verified hub add?
    print("Per-hub mutual edges added (hub → anchors):")
    for r in verified:
        hub = r["username"]
        anchors = r.get("mutual_anchors", [])
        hubs_x = r.get("mutual_hubs", [])
        extra = f" + {len(hubs_x)} hubs" if hubs_x else ""
        print(f"  @{hub:<22} → {len(anchors)} anchors{extra}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
