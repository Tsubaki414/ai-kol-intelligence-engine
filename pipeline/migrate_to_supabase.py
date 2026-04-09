"""
One-shot migration: all existing JSON pipeline data → Supabase.

Reads:
  - classified_kols.json      → users table (674 rows, full classification)
  - raw_expansion.json        → users (candidates) + follows (seed→candidate edges)
  - circles/graph_v1.json     → users (peripheral nodes) + follows (graph edges)
  - core_tweets.json          → tweets table (1,280 rows for 66 core KOLs)

Order matters because of foreign keys:
  1. Insert all users first (union of all handles we've ever seen)
  2. Then follows (requires both endpoints to exist in users)
  3. Then tweets (requires author_handle to exist in users)
  4. Then seeds (requires handle to exist in users)

Idempotent: uses upsert everywhere, so running twice is safe. Classified data
is loaded LAST, overwriting any minimal placeholder rows from earlier steps.

Graph edges that are NOT inserted into follows:
  - co_follow_inferred (tier_3)      — derived signal, not a real follow
  - peripheral_cofollow (tier_3b)    — derived signal, not a real follow

Usage:
    python3 pipeline/migrate_to_supabase.py
    python3 pipeline/migrate_to_supabase.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.db import get_client

ROOT = Path(__file__).parent
CLASSIFIED_KOLS = ROOT / "classified_kols.json"
CLASSIFIED_ORGS = ROOT / "classified_orgs.json"
RAW_EXPANSION = ROOT / "raw_expansion.json"
GRAPH_V1 = ROOT / "circles" / "graph_v1.json"
CORE_TWEETS = ROOT / "core_tweets.json"

USERS_BATCH = 100
FOLLOWS_BATCH = 500
TWEETS_BATCH = 100

# Edge types from graph_v1.json that represent REAL follows
REAL_FOLLOW_TYPES = {
    "mutual_follow",           # bidirectional: insert as TWO rows
    "one_way_follow_anchor",   # directed
    "anchor_to_hub",           # directed (anchor follows hub)
    "anchor_to_peripheral",    # directed (anchor follows peripheral)
}
DERIVED_EDGE_TYPES = {
    "co_follow_inferred",
    "peripheral_cofollow",
}


def normalize_handle(h: str | None) -> str | None:
    if not h:
        return None
    return h.lstrip("@").lower().strip() or None


# ============================================================
# Loaders
# ============================================================


def _classified_entry_to_user(k: dict[str, Any], model: str | None, source_tag: str) -> dict[str, Any] | None:
    """Shared adapter for classified_kols.json entries and classified_orgs.json entries."""
    handle = normalize_handle(k.get("username"))
    if not handle:
        return None
    x_id_raw = k.get("id")
    x_id = str(x_id_raw) if x_id_raw not in (None, "") else None
    return {
        "handle": handle,
        "x_id": x_id,
        "name": k.get("name"),
        "bio": k.get("bio"),
        "followers_count": k.get("followers_count"),
        "following_count": k.get("following_count"),
        "tweet_count": k.get("tweet_count"),
        "verified": bool(k.get("verified", False)),
        "tier": k.get("tier"),
        "sector": k.get("sector"),
        "language": k.get("language"),
        "region": k.get("region"),
        "content_type": k.get("content_type"),
        "is_real_human": k.get("is_real_human"),
        "is_organization": k.get("is_organization_account"),
        "is_ai_crypto_focused": k.get("is_ai_crypto_focused"),
        "is_active": k.get("is_active"),
        "has_original_content": k.get("has_original_content"),
        "is_anchor": bool(k.get("is_anchor", False)),
        "cooperability": k.get("cooperability"),
        "outreach_angle": k.get("outreach_angle"),
        "estimated_price_tier": k.get("estimated_price_tier"),
        "source": k.get("source") or source_tag,
        "classified_by": model,
    }


def load_classified_kols() -> list[dict[str, Any]]:
    """Load classified_kols.json → user records with full classification."""
    with CLASSIFIED_KOLS.open() as f:
        data = json.load(f)
    model = data.get("metadata", {}).get("model")
    users: list[dict[str, Any]] = []
    for k in data.get("kols", []):
        u = _classified_entry_to_user(k, model, "classified_kols")
        if u:
            users.append(u)
    return users


def load_classified_orgs() -> list[dict[str, Any]]:
    """Load classified_orgs.json → user records for orgs/non-KOL accounts.

    These are accounts the classifier filtered out of the main KOL list
    (organizations, news aggregators, etc.). They still have valid profile
    data and some of them were seeds in earlier pipeline runs, so we need
    them in the `users` table to satisfy foreign key references from `follows`.
    """
    if not CLASSIFIED_ORGS.exists():
        return []
    with CLASSIFIED_ORGS.open() as f:
        data = json.load(f)
    # classified_orgs.json is a bare list (no metadata wrapper)
    entries = data if isinstance(data, list) else data.get("orgs", [])
    users: list[dict[str, Any]] = []
    for k in entries:
        u = _classified_entry_to_user(k, None, "classified_orgs")
        if u:
            users.append(u)
    return users


def load_raw_expansion() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load raw_expansion.json → (candidate users, seed→candidate edges).

    Each candidate in raw_expansion.json has:
      - handle
      - profile: {id, username, name, description, verified, public_metrics}
      - followed_by_seed_handles: [list of seed handles that follow this candidate]
    """
    with RAW_EXPANSION.open() as f:
        data = json.load(f)

    users: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in data.get("candidates", []):
        handle = normalize_handle(c.get("handle"))
        if not handle or handle in seen:
            continue
        seen.add(handle)

        profile = c.get("profile") or {}
        pm = profile.get("public_metrics") or {}
        users.append(
            {
                "handle": handle,
                "x_id": str(profile.get("id", "")),
                "name": profile.get("name"),
                "bio": profile.get("description"),
                "followers_count": pm.get("followers_count"),
                "following_count": pm.get("following_count"),
                "tweet_count": pm.get("tweet_count"),
                "verified": bool(profile.get("verified", False)),
                "source": "v1_raw_expansion",
            }
        )

        for seed_handle in c.get("followed_by_seed_handles", []) or []:
            seed_h = normalize_handle(seed_handle)
            if seed_h:
                edges.append(
                    {
                        "follower_handle": seed_h,
                        "followee_handle": handle,
                        "source": "v1_raw_expansion",
                    }
                )

    return users, edges


def load_graph_v1() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load graph_v1.json → (node users, edge follows).

    graph_v1.json nodes have: id (handle), x_id, type, tier, sector, language,
    region, cooperability, content_type, pagerank, betweenness, cluster, etc.

    Edges have: source, target, type, tier, directed, weight, circles.
    We include only "real follow" edges; co_follow_inferred and peripheral_cofollow
    are derived signals and are skipped.
    """
    with GRAPH_V1.open() as f:
        g = json.load(f)

    users: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in g.get("nodes", []):
        handle = normalize_handle(n.get("id"))
        if not handle or handle in seen:
            continue
        seen.add(handle)
        users.append(
            {
                "handle": handle,
                "x_id": str(n.get("x_id", "")),
                "name": n.get("name"),
                "bio": n.get("description"),
                "followers_count": n.get("followers_count"),
                "following_count": n.get("following_count"),
                "tier": n.get("tier"),
                "sector": n.get("sector"),
                "language": n.get("language"),
                "region": n.get("region"),
                "content_type": n.get("content_type"),
                "cooperability": n.get("cooperability"),
                "outreach_angle": n.get("outreach_angle"),
                "estimated_price_tier": n.get("estimated_price_tier"),
                "is_anchor": n.get("type") == "anchor",
                "cluster_id": n.get("cluster"),
                "pagerank": n.get("pagerank"),
                "betweenness": n.get("betweenness"),
                "source": "graph_v1",
            }
        )

    edges: list[dict[str, Any]] = []
    skipped_derived = 0
    for e in g.get("edges", []):
        et = e.get("type")
        if et in DERIVED_EDGE_TYPES:
            skipped_derived += 1
            continue
        if et not in REAL_FOLLOW_TYPES:
            continue
        src = normalize_handle(e.get("source"))
        tgt = normalize_handle(e.get("target"))
        if not src or not tgt or src == tgt:
            continue
        if et == "mutual_follow":
            # Insert both directions
            edges.append(
                {
                    "follower_handle": src,
                    "followee_handle": tgt,
                    "source": "graph_v1_mutual",
                }
            )
            edges.append(
                {
                    "follower_handle": tgt,
                    "followee_handle": src,
                    "source": "graph_v1_mutual",
                }
            )
        else:
            edges.append(
                {
                    "follower_handle": src,
                    "followee_handle": tgt,
                    "source": f"graph_v1_{et}",
                }
            )

    print(f"    ({skipped_derived} co-follow/inferred edges skipped as non-real)")
    return users, edges


def load_core_tweets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load core_tweets.json → (minimal user stubs, tweet rows)."""
    with CORE_TWEETS.open() as f:
        data = json.load(f)

    users: list[dict[str, Any]] = []
    tweets: list[dict[str, Any]] = []

    def classify_tweet(t: dict[str, Any]) -> str:
        for r in t.get("referenced_tweets") or []:
            if r.get("type") == "retweeted":
                return "retweet"
            if r.get("type") == "replied_to":
                return "reply"
            if r.get("type") == "quoted":
                return "quote"
        return "original"

    for handle, info in data.get("tweets_by_handle", {}).items():
        h = normalize_handle(handle)
        if not h:
            continue
        users.append(
            {
                "handle": h,
                "x_id": str(info.get("x_id", "")),
                "followers_count": info.get("followers_count"),
                "tier": info.get("tier"),
                "source": "core_tweets",
            }
        )
        for t in info.get("tweets") or []:
            tweets.append(
                {
                    "tweet_id": t.get("id", ""),
                    "author_handle": h,
                    "created_at": t.get("created_at"),
                    "text": t.get("text"),
                    "lang": t.get("lang"),
                    "tweet_type": classify_tweet(t),
                    "referenced_tweets": t.get("referenced_tweets"),
                    "public_metrics": t.get("public_metrics"),
                    "classification": None,
                }
            )
    return users, tweets


# ============================================================
# Merge helpers
# ============================================================


def merge_users(*batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union multiple user record lists, merging on `handle`.
    Later batches overwrite earlier ones field-by-field, but only for non-null values.
    This preserves partial data from earlier sources while letting classified data
    enrich the row.
    """
    merged: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for u in batch:
            h = u.get("handle")
            if not h:
                continue
            if h not in merged:
                merged[h] = {}
            for k, v in u.items():
                if v is not None:
                    merged[h][k] = v
    return list(merged.values())


def dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for e in edges:
        key = (e["follower_handle"], e["followee_handle"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def dedupe_tweets(tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for t in tweets:
        tid = t.get("tweet_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(t)
    return out


# ============================================================
# Upsert helpers
# ============================================================


def batched(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_users(client, users: list[dict[str, Any]]) -> int:
    total = 0
    for batch in batched(users, USERS_BATCH):
        client.table("users").upsert(batch, on_conflict="handle").execute()
        total += len(batch)
        print(f"    upserted {total}/{len(users)} users")
    return total


def upsert_follows(client, edges: list[dict[str, Any]]) -> int:
    total = 0
    for batch in batched(edges, FOLLOWS_BATCH):
        client.table("follows").upsert(
            batch, on_conflict="follower_handle,followee_handle"
        ).execute()
        total += len(batch)
        print(f"    upserted {total}/{len(edges)} follows")
    return total


def upsert_tweets(client, tweets: list[dict[str, Any]]) -> int:
    total = 0
    for batch in batched(tweets, TWEETS_BATCH):
        client.table("tweets").upsert(batch, on_conflict="tweet_id").execute()
        total += len(batch)
        print(f"    upserted {total}/{len(tweets)} tweets")
    return total


def upsert_seeds(client, seed_handles: list[str]) -> int:
    if not seed_handles:
        return 0
    rows = [{"handle": h, "added_by": "pipeline_v1"} for h in seed_handles]
    client.table("seeds").upsert(rows, on_conflict="handle").execute()
    return len(rows)


# ============================================================
# Main
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load + merge + dedupe but don't write to Supabase (prints counts only)",
    )
    args = parser.parse_args()

    print("Loading JSON files…")
    classified_users = load_classified_kols()
    print(f"  classified_kols.json: {len(classified_users)} users")

    orgs_users = load_classified_orgs()
    print(f"  classified_orgs.json: {len(orgs_users)} orgs/non-KOL users")

    raw_users, raw_edges = load_raw_expansion()
    print(f"  raw_expansion.json: {len(raw_users)} candidate users, {len(raw_edges)} edges")

    graph_users, graph_edges = load_graph_v1()
    print(f"  graph_v1.json: {len(graph_users)} nodes, {len(graph_edges)} real-follow edges")

    tweet_users, tweets = load_core_tweets()
    print(f"  core_tweets.json: {len(tweet_users)} users with tweets, {len(tweets)} tweets")

    print("\nMerging…")
    # Load order matters for merge: earliest (least enriched) first, latest (most enriched) last.
    # This way classified_kols data wins for fields both sources populate.
    # Orgs are loaded alongside raw/graph as "mid-tier" enrichment — they have real
    # profiles but aren't primary KOLs.
    all_users = merge_users(raw_users, tweet_users, graph_users, orgs_users, classified_users)
    all_edges = dedupe_edges(raw_edges + graph_edges)
    all_tweets = dedupe_tweets(tweets)
    print(f"  merged users: {len(all_users)}")
    print(f"  deduped edges: {len(all_edges)}")
    print(f"  deduped tweets: {len(all_tweets)}")

    # Build the set of valid handles for FK validation
    valid_handles = {u["handle"] for u in all_users}

    # Any edge endpoints still missing? Create minimal placeholder user rows so
    # we don't silently drop the edges. These are real referenced handles from
    # earlier pipeline runs where we didn't capture full profile data — they
    # can be backfilled later via a targeted X API /users call.
    referenced_handles: set[str] = set()
    for e in all_edges:
        referenced_handles.add(e["follower_handle"])
        referenced_handles.add(e["followee_handle"])
    missing_refs = referenced_handles - valid_handles
    if missing_refs:
        print(f"  {len(missing_refs)} referenced handles have no profile; creating placeholder rows")
        print(f"    (backfill later via /users batch call — they become real once we see them)")
        for h in missing_refs:
            all_users.append(
                {
                    "handle": h,
                    "x_id": None,
                    "source": "placeholder_from_edge_reference",
                }
            )
            valid_handles.add(h)

    # After placeholder insertion no edges should need dropping
    valid_edges = [
        e
        for e in all_edges
        if e["follower_handle"] in valid_handles and e["followee_handle"] in valid_handles
    ]
    dropped = len(all_edges) - len(valid_edges)
    if dropped:
        print(f"  dropped {dropped} edges (unexpected — investigate)")

    valid_tweets = [t for t in all_tweets if t["author_handle"] in valid_handles]
    dropped_t = len(all_tweets) - len(valid_tweets)
    if dropped_t:
        print(f"  dropped {dropped_t} tweets with unknown author")

    # Identify seed handles from classified data
    seed_handles = [u["handle"] for u in classified_users if u.get("is_anchor")]
    print(f"  seed handles (is_anchor=True): {len(seed_handles)}")

    if args.dry_run:
        print("\n[DRY RUN] would upsert:")
        print(f"  users:   {len(all_users)}")
        print(f"  follows: {len(valid_edges)}")
        print(f"  tweets:  {len(valid_tweets)}")
        print(f"  seeds:   {len(seed_handles)}")
        return 0

    print("\nConnecting to Supabase…")
    client = get_client()

    print(f"\nUpserting {len(all_users)} users…")
    upsert_users(client, all_users)

    print(f"\nUpserting {len(valid_edges)} follows…")
    upsert_follows(client, valid_edges)

    print(f"\nUpserting {len(valid_tweets)} tweets…")
    upsert_tweets(client, valid_tweets)

    print(f"\nUpserting {len(seed_handles)} seeds…")
    upsert_seeds(client, seed_handles)

    print("\n" + "=" * 60)
    print("Migration complete. Row counts in DB:")
    from pipeline.db import ping

    health = ping()
    for table, count in health["tables"].items():
        print(f"  {table}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
