# AI KOL Intelligence Engine

> **Trial task deliverable.** A referral-chain discovery engine for AI + Crypto KOLs on Chinese/English Twitter. Data pipeline in Python + Supabase, static React demo as the user-facing product.

---

## What this is

An end-to-end system for discovering, scoring, and routing outreach to AI+Crypto KOLs. The core insight: **mutual follow is the only confirmed relationship signal** on Twitter/X. Everything else — one-way follows, interaction counts, sector labels — is a targeting hint, not evidence of "they're in the same circle".

Four pieces:

1. **Python pipeline** (`pipeline/`, `scoring/`) — X API v2 ingestion, Claude-based classification (real human vs org, sector, language, etc.), mutual-follow graph construction, three-layer parallel scoring, Louvain community detection.
2. **Supabase Postgres** (`supabase/`) — single source of truth for users / follows / tweets / seeds. The pipeline writes to it; the frontend reads static JSON exports produced from it.
3. **React demo** (`kol-intelligence-engine/`) — Vite + React + TailwindCSS. 11 pages including KOL Database, Network Graph, **Outreach Priority Panel** (the killer feature), AI Agent, Discovery Pipeline.
4. **Five demo-mode pages** showing planned features (Guilds, Brief Generator, Campaign Simulator, 3rd-party integration, On-chain Verification).

---

## The output

After running the full pipeline, you get:

- **680 classified KOLs** (real humans, AI+Crypto focused) with Layer 1 Quality Scores, Layer 3 Cooperability Scores, sector/tier/language tags, cooperability flags, outreach angles, estimated price tiers
- **27 mutual-follow-verified network members** (16 ground-truth seeds + 11 hub-verified additions) with PageRank, betweenness, cluster assignment, cross-cluster bridge ratio
- **4106 directed follow edges** in the `follows` table producing **98 mutual edges** in the mutual subgraph
- **A three-column Outreach Priority Panel** sorting the 27 mutual members into:
  - 🗝️ **Gateway KOLs** (13) — attack first, high referral potential
  - 🎯 **Strategic Targets** (2) — important but hard to reach, use Gateway warm intros
  - ⚡ **Quick Wins** (5) — easy bookings for testimonials

---

## Quick start (demo only)

If you just want to see the React demo without running the pipeline, the static JSON data is pre-generated and committed:

```bash
cd kol-intelligence-engine
npm install
npm run dev    # http://127.0.0.1:5175
```

---

## Quick start (full pipeline)

If you want to regenerate the data from scratch:

```bash
# 1. Python pipeline setup
python3 -m venv pipeline/.venv
source pipeline/.venv/bin/activate
pip install -r pipeline/requirements.txt  # (or scoring/requirements.txt)

# 2. Copy .env.example and fill in credentials
cp .env.example .env
# Required: ANTHROPIC_API_KEY, X_BEARER_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY

# 3. Set up Supabase (one-time) — follow supabase/SETUP.md
#    Run supabase/schema.sql in the Supabase SQL editor

# 4. Run the pipeline end-to-end
pipeline/.venv/bin/python pipeline/classify_and_score.py    # Phase 1: classification
pipeline/.venv/bin/python pipeline/hub_verify.py --batch 1  # Phase 1c: mutual-follow verification
pipeline/.venv/bin/python pipeline/migrate_hub_verification.py
pipeline/.venv/bin/python pipeline/rebuild_network_stats.py # Louvain + PageRank + betweenness
pipeline/.venv/bin/python -m scoring.batch_score             # Layer 1/2/3 scoring

# 5. Export to frontend
pipeline/.venv/bin/python scoring/export_kols_json.py
pipeline/.venv/bin/python scoring/export_graph_json.py

# 6. Frontend
cd kol-intelligence-engine && npm install && npm run dev
```

---

## Architecture

```
X API v2 Basic ──► pipeline/ ──► Supabase Postgres
                   (classify,    (users, follows,
                    score,        tweets, seeds)
                    rebuild)           │
                                       │ export_*.py
                                       ▼
                              kol-intelligence-engine/
                              src/data/*.json (static)
                                       │
                                       ▼
                                 React demo
                                 (11 pages)
```

### Scoring model (v3, redesigned 2026-04-09)

Three **parallel** main-line scores — never fused into a single "overall":

**Layer 1 · Quality Score (0-100)**

| Sub-score | Weight | Source |
|---|---|---|
| Engagement Quality Ratio | 30% | `(Σ replies + Σ quotes) / (Σ likes + Σ retweets)` over last 20 authored posts |
| Content Originality | 25% | Claude Phase 1d classification: `0.6 × class_value + 0.4 × claude_raw` |
| Audience Authenticity | 15% | `unique_repliers / total_replies` from reply-stream sample |
| Sector Relevance | 15% | % of last 20 posts classified as AI+Crypto + specialization bonus |
| Network Position ⭐ | 15% | `0.5 × absolute(t1_mutual_count) + 0.5 × bridge(cross_cluster_ratio)` |

**Layer 2 · On-chain Verification Score (0-100, independent display)** — Wallet-Content Alignment (50%), Activity Depth (25%), Campaign Impact (25%). Currently null in bootstrap (Etherscan integration deferred).

**Layer 3 · Cooperability Score (0-100)**

| Sub-score | Weight | Source |
|---|---|---|
| Contact Signal Strength | 40% | **Deterministic regex on bio text.** email=100 > telegram=80 > collab keyword=60 > website=40 > default DM=10 |
| Promo Willingness | 30% | **Scan cached tweets.** Explicit sponsor disclosure=90 > review content+@mentions=60 > authored only=30 > null if no tweets |
| Accessibility | 30% | Base by tier (Nano=90/Micro=70/Macro=40/Mega=15) + 15 bonus if mutual member, capped at 100 |

---

## Tests

```bash
source pipeline/.venv/bin/activate
python3 -m pytest scoring/test_score_kol.py -v
```

45 unit tests covering all three layers, edge cases, renormalization, and the "no overall_score fusion" architectural invariant.

---

## Methodology note

This project deliberately **only** trusts mutual-follow as ground truth for "this KOL is in the circle". One-way follows (anchor → celebrity) are tracked but visually demoted and excluded from PageRank/cluster computation to prevent celebrity-bias contamination (the "everyone follows Jack Ma, but does he follow you back?" problem). Celebrities are auto-detected by follower count outliers (≥ 5× median anchor followers, or ≥ 2× max anchor followers, or ≥ 250K followers with ≤ 5 anchor follows) and filtered from default views.

See [`supabase/schema.sql`](supabase/schema.sql) for the canonical data model.

## Repo layout

```
.
├── pipeline/              # Python data pipeline
│   ├── x_client.py        # X API v2 httpx wrapper
│   ├── db.py              # Supabase client wrapper
│   ├── classify_and_score.py
│   ├── hub_verify.py
│   ├── rebuild_network_stats.py
│   └── ...
├── scoring/               # Three-layer scoring system
│   ├── schema.py          # Pydantic models (KolRaw, ScoredKol, ScoreTrace)
│   ├── score_kol.py       # 12 sub-score functions + aggregators
│   ├── load_kol.py        # Supabase → KolRaw
│   ├── batch_score.py     # Score all KOLs + write back
│   ├── export_kols_json.py
│   ├── export_graph_json.py
│   └── test_score_kol.py  # 45 unit tests
├── supabase/
│   ├── schema.sql         # Postgres schema
│   └── SETUP.md           # Step-by-step setup
├── kol-intelligence-engine/  # Vite + React demo
│   ├── src/pages/         # Dashboard, NetworkGraph, OutreachPanel, etc.
│   ├── src/components/
│   ├── src/data/          # kols.json, graph.json, agent_responses.json
│   └── README.md
├── .env.example
├── .gitignore
└── README.md              # this file
```
