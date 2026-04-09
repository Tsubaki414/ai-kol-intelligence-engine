# KOL Data Schema — Field Source Mapping

> Single source of truth: [`schema.py`](schema.py) (Pydantic 2 models).
> For scoring formulas, see [`scoring_spec.md`](scoring_spec.md).
> For high-level architecture, see [`../CLAUDE.md`](../CLAUDE.md) §Phase 2.

The scoring system consumes a normalized `KolRaw` record. The existing pipeline
files (`classified_kols.json`, `core_tweets.json`, `graph_v1.json`) each hold a
**slice** of the `KolRaw` shape — no single file has everything. An enrichment
step merges them into `KolRaw` before scoring.

This doc maps every `KolRaw` field to its source file (or to the Phase 1d
Claude pre-classification pass that still needs to run).

---

## Top-level `KolRaw`

| Field | Type | Source | Status |
|---|---|---|---|
| `handle` | `str` | [`classified_kols.json`](../pipeline/classified_kols.json) `kols[].username` | ✅ available |
| `profile` | `Profile` | merged from multiple files — see below | ✅ partial |
| `contact_signals` | `ContactSignals` | Phase 1d bio/pinned parse — see below | ⚠️ Phase 1d |
| `cooperability_hard_filter` | `CooperabilityHardFilter` | [`classified_kols.json`](../pipeline/classified_kols.json) `kols[].cooperability` | ✅ available |
| `recent_posts` | `list[Tweet]` | [`core_tweets.json`](../pipeline/core_tweets.json) `tweets_by_handle[handle].tweets` | ✅ 66 core nodes only |
| `posts_last_30d` | `PostsLast30d` | computed from `recent_posts` OR from a separate `/users/:id/tweets` with date filter | ⚠️ derived |
| `reply_stream_sample` | `ReplyStreamSample` | Phase 1d `/tweets/search/recent` with `conversation_id` | ⚠️ Phase 1d |
| `network_stats` | `NetworkStats` | [`circles/graph_v1.json`](../pipeline/circles/graph_v1.json) — computed from edges | ✅ 66 core nodes only |
| `promo_history_90d` | `PromoHistory90d` | Phase 1d Claude scan of last 90d posts | ⚠️ Phase 1d |
| `past_rate_disclosures` | `PastRateDisclosures` | Phase 1d bio parse + optional external rate DB | ⚠️ Phase 1d |
| `onchain` | `OnchainData` | Phase 1d Etherscan/Arkham integration (null in bootstrap) | ⚠️ Phase 1d |
| `campaign_history` | `list[dict]` | Internal campaign database (empty in bootstrap) | ❌ not yet |

---

## `Profile` sub-record

| Field | Source file | Source field |
|---|---|---|
| `followers` | `classified_kols.json` | `kols[].followers_count` |
| `following` | `classified_kols.json` | `kols[].following_count` |
| `joined` | **missing** — needs `user.fields=created_at` call via X API `/users/by/username` | |
| `verified` | `classified_kols.json` | `kols[].verified` |
| `bio` | `classified_kols.json` | `kols[].bio` |
| `is_dm_open` | **missing** — not exposed by X API v2 public endpoints | |
| `tier` | `classified_kols.json` | `kols[].tier` |

**Gap: `joined` and `is_dm_open`.**
- `joined` can be fetched in bulk via `x_client.get_users_by_ids()` — the v2
  endpoint returns `created_at` when requested. One-time backfill for the 674
  classified KOLs is feasible (`/users` batch endpoint handles 100 at a time →
  ~7 requests total).
- `is_dm_open` is genuinely not available via the public API. Workaround: default
  to `None` and let Layer 3 Contact Accessibility fall back to other signals
  (email / telegram / none).

---

## `Tweet` sub-records (→ `KolRaw.recent_posts`)

Source: [`core_tweets.json`](../pipeline/core_tweets.json) `tweets_by_handle[handle].tweets[]`.

| Field | X API field | Notes |
|---|---|---|
| `id` | `id` | direct |
| `created_at` | `created_at` | ISO8601 string |
| `text` | `text` | direct |
| `lang` | `lang` | direct |
| `referenced_tweets` | `referenced_tweets` | array of `{type, id}`; drives `tweet_type` property |
| `public_metrics` | `public_metrics` | `{like_count, reply_count, retweet_count, quote_count}` |
| `classification` | — | null until Phase 1d Claude pass runs |

Convenience: `tweet_from_x_api(raw_dict)` in [`schema.py`](schema.py) normalizes
a raw X API dict directly. The `tweet.tweet_type` property computes
`original/retweet/quote/reply` from `referenced_tweets` (X API v2 doesn't
provide this classification directly).

**EQR uses `tweet.is_authored` = True**, which means `tweet_type in (original, quote)`.
Retweets and replies are excluded from the KOL's "own broadcast content" per
the 2026-04-09 calibration (see `scoring_spec.md` §4.1).

---

## `NetworkStats` sub-record

Source: [`circles/graph_v1.json`](../pipeline/circles/graph_v1.json).

Not stored directly as a per-node field — must be **derived from the edges**
at enrichment time. The computation (for each core node):

```python
t1_edges = [e for e in graph["edges"] if e["type"] == "mutual_follow"]

def network_stats_for(handle: str) -> NetworkStats:
    my_edges = [e for e in t1_edges if handle in (e["source"], e["target"])]
    t1_count = len(my_edges)
    cluster_of = {n["id"]: n.get("cluster") for n in graph["nodes"]}
    my_cluster = cluster_of.get(handle)
    cross_count = sum(
        1 for e in my_edges
        if cluster_of.get(e["source"]) != cluster_of.get(e["target"])
    )
    return NetworkStats(
        t1_mutual_count=t1_count,
        cross_cluster_mutual_count=cross_count,
        bridge_ratio=cross_count / t1_count if t1_count else 0.0,
        cluster_id=my_cluster,
    )
```

Current state: 66 core nodes (anchors + hubs) have meaningful graph data.
647 peripheral nodes are present but only have one-way follow edges, so their
`t1_mutual_count` will be 0 and their Network Position score will be 0. That's
expected — peripherals are low-confidence discoveries.

---

## `CooperabilityHardFilter` sub-record

Source: [`classified_kols.json`](../pipeline/classified_kols.json)
`kols[].cooperability` — directly maps field-for-field:

```json
"cooperability": {
  "is_contactable": true,
  "accepts_paid_promos": true,
  "contact_method": "twitter_dm",
  "public_email": null,
  "public_telegram": null
}
```

KOLs with `is_contactable == False` or `accepts_paid_promos == False` should be
routed to `observe_only.json` **before** the scoring step runs. This model
preserves the decision for audit/display.

---

## Fields that still need a Phase 1d pass

These fields are in the `KolRaw` schema but have **no source data yet**. They
require a dedicated Phase 1d step to populate:

| Field | What it needs | Cost estimate |
|---|---|---|
| `Tweet.classification` | Claude API call per KOL, classifying last 20 tweets (8-class taxonomy + sector + promo_match) | ~1 Haiku call per KOL × 674 = $5-10 total |
| `ContactSignals` | Claude parses bio + pinned tweet for email/telegram/website | bundled with classification call |
| `ReplyStreamSample` | X API `/tweets/search/recent?query=conversation_id:<id>` for recent posts | ~3-5 searches per KOL (pay-per-use billed) |
| `PromoHistory90d` | Claude scans last 90d posts for sponsor phrases | bundled with classification call if posts cover 90d |
| `PastRateDisclosures` | Bio parse + optional external rate DB lookup | bundled with classification |
| `OnchainData` | Etherscan/Arkham integration (deferred) | — |

---

## Enrichment pipeline (proposed, not yet implemented)

```
┌─ classified_kols.json ────┐
│  profile + tier + sector  │
│  + cooperability          │
└────────────┬──────────────┘
             │
┌─ core_tweets.json ────────┐      ┌─ enrich_kol_raw.py ─┐      ┌─ KolRaw records ─┐
│  recent_posts             │────▶│   merge + validate  │─────▶│  → score_kol()   │
│  public_metrics           │      └──────────┬──────────┘      └──────────────────┘
└───────────────────────────┘                 │
                                              │
┌─ circles/graph_v1.json ───┐                  │
│  nodes + edges            │──────────────────┘
│  → derived network_stats  │
└───────────────────────────┘
                                              ▲
┌─ Phase 1d Claude pass ────┐                  │
│  classification per tweet │──────────────────┘
│  contact_signals          │
│  promo_history_90d        │
│  past_rate_disclosures    │
└───────────────────────────┘
```

The `enrich_kol_raw.py` script (not yet written) will:
1. Load `classified_kols.json` as the primary index
2. For each entry, attempt to merge in `core_tweets.json` data (only 66 of 674 have it)
3. Attempt to merge `network_stats` from `graph_v1.json` (only 66 core nodes)
4. Attempt to merge Phase 1d outputs when available
5. Build and validate a `KolRaw` (Pydantic raises on required-field failure)
6. Write `pipeline/kol_raw_records.json` as the scoring input file

---

## Usage

```python
from scoring.schema import KolRaw, ScoredKol, tweet_from_x_api
import json

# Load raw dict from JSON
with open("pipeline/kol_raw_records.json") as f:
    records = json.load(f)

# Validate + parse
kols = [KolRaw.model_validate(r) for r in records]

# Score each
from scoring.score_kol import score_kol
results = [score_kol(k) for k in kols]

# Serialize scored results
with open("pipeline/scored_kols.json", "w") as f:
    json.dump([r.model_dump() for r in results], f, indent=2)
```

## Generating JSON Schema (for React demo)

```bash
cd scoring
python3 -m schema > kol_schema.json
```

This produces a JSON Schema file that React/TypeScript can consume via tools
like `json-schema-to-typescript` to generate `.d.ts` types for the demo.

---

## Version

- Schema version: **v3_2026-04-09** (matches `ScoredKol.scored_with_version`)
- Any breaking schema change should bump this string; the scorer should refuse
  to consume records with a mismatched version.
