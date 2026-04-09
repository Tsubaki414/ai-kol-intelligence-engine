-- KOL Intelligence Engine — Supabase Schema
-- Version: v3_2026-04-09
--
-- Paste this entire file into Supabase SQL Editor and run.
-- It's idempotent: running twice is safe (uses IF NOT EXISTS / DROP IF EXISTS
-- for the view only).
--
-- Design notes:
-- - Handles are lowercase, no @ prefix, stored as TEXT (X handles are case-insensitive)
-- - x_id is TEXT (not BIGINT) to avoid int overflow edge cases and match JSON storage
-- - The `follows` table is the single source of truth for the graph.
--   Mutual follows are derivable via self-join or the `mutual_follows` view.
--   T3 "inferred" edges from co-follow analysis are NOT stored here — they're
--   derived signals, not actual follow relationships.
-- - Network metrics (cluster_id, bridge_ratio, etc.) live on the users row,
--   updated by a periodic graph-rebuild job. Latest-only, no history.
-- - Three-layer scores (quality/cooperability/onchain) also live on users,
--   replacing the fabricated scores that the v1 classifier wrote.
-- - Row Level Security is enabled but not yet configured — defer to Phase 3
--   when we wire the demo to read via anon role.

-- ============================================================
-- Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- Table: users
-- One row per X account we know about.
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
  handle                     TEXT PRIMARY KEY,
  x_id                       TEXT,     -- nullable; backfilled when we see the account via X API

  -- Profile (from X API /users endpoint)
  name                       TEXT,
  bio                        TEXT,
  followers_count            INT,
  following_count            INT,
  tweet_count                INT,
  verified                   BOOLEAN DEFAULT FALSE,
  joined_at                  DATE,
  profile_image_url          TEXT,

  -- Classification (from Phase 1d Claude — classify_and_score.py successor)
  tier                       TEXT CHECK (tier IS NULL OR tier IN ('Nano','Micro','Macro','Mega')),
  sector                     TEXT,
  language                   TEXT,
  region                     TEXT,
  content_type               TEXT[],
  is_real_human              BOOLEAN,
  is_organization            BOOLEAN,
  is_ai_crypto_focused       BOOLEAN,
  is_active                  BOOLEAN,
  has_original_content       BOOLEAN,
  is_anchor                  BOOLEAN DEFAULT FALSE,

  -- Cooperability v3 hard filter
  cooperability              JSONB,
  outreach_angle             TEXT,
  estimated_price_tier       TEXT,

  -- Network metrics (derived from `follows` by a periodic graph rebuild)
  cluster_id                 INT,
  pagerank                   REAL,
  betweenness                REAL,
  t1_mutual_count            INT DEFAULT 0,
  cross_cluster_mutual_count INT DEFAULT 0,
  bridge_ratio               REAL DEFAULT 0.0,
  graph_indexed_at           TIMESTAMPTZ,

  -- Three-layer scores (populated by score_kol.py v3_2026-04-09)
  quality_score              REAL,
  cooperability_score        REAL,
  onchain_score              REAL,
  quality_confidence         TEXT,
  cooperability_confidence   TEXT,
  onchain_confidence         TEXT,
  score_traces               JSONB,
  scored_at                  TIMESTAMPTZ,
  scored_with_version        TEXT,

  -- Provenance
  source                     TEXT,
  classified_at              TIMESTAMPTZ,
  classified_by              TEXT,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_x_id      ON users(x_id) WHERE x_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_tier             ON users(tier);
CREATE INDEX IF NOT EXISTS idx_users_sector           ON users(sector);
CREATE INDEX IF NOT EXISTS idx_users_cluster          ON users(cluster_id);
CREATE INDEX IF NOT EXISTS idx_users_language         ON users(language);
CREATE INDEX IF NOT EXISTS idx_users_quality_desc     ON users(quality_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_users_coop_desc        ON users(cooperability_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_users_is_anchor        ON users(is_anchor) WHERE is_anchor = TRUE;

-- Auto-update `updated_at` on row modification
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ============================================================
-- Table: follows
-- Raw directed follow edges. One row per (follower, followee) pair.
-- A mutual follow = two rows (A→B and B→A).
-- ============================================================

CREATE TABLE IF NOT EXISTS follows (
  follower_handle TEXT NOT NULL REFERENCES users(handle) ON DELETE CASCADE,
  followee_handle TEXT NOT NULL REFERENCES users(handle) ON DELETE CASCADE,
  fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source          TEXT,
  PRIMARY KEY (follower_handle, followee_handle),
  CHECK (follower_handle <> followee_handle)
);

CREATE INDEX IF NOT EXISTS idx_follows_follower ON follows(follower_handle);
CREATE INDEX IF NOT EXISTS idx_follows_followee ON follows(followee_handle);

-- Convenience view: mutual follows (A follows B AND B follows A).
-- Each mutual pair appears ONCE with handles in lexicographic order.
DROP VIEW IF EXISTS mutual_follows;
CREATE VIEW mutual_follows AS
SELECT
  f1.follower_handle AS handle_a,
  f1.followee_handle AS handle_b,
  GREATEST(f1.fetched_at, f2.fetched_at) AS confirmed_at
FROM follows f1
JOIN follows f2
  ON f2.follower_handle = f1.followee_handle
 AND f2.followee_handle = f1.follower_handle
WHERE f1.follower_handle < f1.followee_handle;

-- ============================================================
-- Table: tweets
-- Cached tweet data with public_metrics and optional classification.
-- ============================================================

CREATE TABLE IF NOT EXISTS tweets (
  tweet_id          TEXT PRIMARY KEY,
  author_handle     TEXT NOT NULL REFERENCES users(handle) ON DELETE CASCADE,
  created_at        TIMESTAMPTZ,
  text              TEXT,
  lang              TEXT,
  tweet_type        TEXT CHECK (tweet_type IS NULL OR tweet_type IN ('original','retweet','quote','reply')),
  referenced_tweets JSONB,
  public_metrics    JSONB,
  classification    JSONB,
  fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tweets_author  ON tweets(author_handle);
CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_type    ON tweets(tweet_type);

-- ============================================================
-- Table: seeds
-- Tracks which handles have been used as expansion seeds.
-- When user adds a new seed via Mode B demo, this is where it lands.
-- ============================================================

CREATE TABLE IF NOT EXISTS seeds (
  handle     TEXT PRIMARY KEY REFERENCES users(handle) ON DELETE CASCADE,
  added_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  added_by   TEXT,        -- 'pipeline_v1', 'mode_b_user_input', etc.
  circle     TEXT,        -- 'chinese_crypto_analysis', 'virtuals_chinese_builders', ...
  notes      TEXT
);

CREATE INDEX IF NOT EXISTS idx_seeds_circle ON seeds(circle);

-- ============================================================
-- Row Level Security
-- Deferred: configure policies in Phase 3 when the React demo connects.
-- For now, enable RLS on all tables so we don't accidentally expose writes.
-- ============================================================

ALTER TABLE users   ENABLE ROW LEVEL SECURITY;
ALTER TABLE follows ENABLE ROW LEVEL SECURITY;
ALTER TABLE tweets  ENABLE ROW LEVEL SECURITY;
ALTER TABLE seeds   ENABLE ROW LEVEL SECURITY;

-- Temporary: allow service_role to do everything (the Python pipeline uses this role).
-- The anon role (React demo) has NO access until Phase 3 policies are added.
-- service_role bypasses RLS automatically, so no explicit policy needed for pipeline writes.

-- ============================================================
-- Sanity check: confirm schema ready
-- ============================================================

DO $$
BEGIN
  RAISE NOTICE 'Schema deployed. Tables: users, follows, tweets, seeds. View: mutual_follows.';
  RAISE NOTICE 'RLS enabled on all tables. Use SERVICE_ROLE key from the pipeline.';
END $$;
