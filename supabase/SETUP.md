# Supabase Setup — Step by Step

> You do steps 1-5 in your browser + local `.env` file.
> I'll do step 6 (migration) once you confirm the credentials are in place.

---

## 1. Sign up and create a project

1. Go to **https://supabase.com** and click **Start your project**
2. Sign in (GitHub OAuth is fastest)
3. Click **New project**
4. Fill in:
   - **Project name**: `kol-intelligence` (or anything)
   - **Database Password**: generate a strong one, save it in your password manager
   - **Region**: pick the one closest to you (e.g., `Northeast Asia (Tokyo)` or `Southeast Asia (Singapore)` for best latency from your location)
   - **Pricing Plan**: Free (500MB DB, 5GB bandwidth/mo — way more than we need)
5. Wait ~2 minutes for the project to provision

---

## 2. Run the schema

1. In the Supabase project dashboard, click **SQL Editor** (left sidebar)
2. Click **New query**
3. Open [`supabase/schema.sql`](schema.sql) from this repo, copy the entire contents
4. Paste into the SQL Editor
5. Click **Run** (or Cmd+Enter)
6. You should see `NOTICE: Schema deployed. Tables: users, follows, tweets, seeds.`

Verify tables exist: click **Table Editor** in the sidebar — you should see `users`, `follows`, `tweets`, `seeds`.

---

## 3. Grab the credentials

1. In the project dashboard, go to **Project Settings** → **API** (left sidebar, gear icon)
2. Copy these three values:

   | Field | Location | What it is |
   |---|---|---|
   | **Project URL** | Top of the API page | `https://<project-ref>.supabase.co` |
   | **anon public key** | "Project API keys" section | Read-only key for browser/React demo (safe to expose) |
   | **service_role secret** | Same section, has a red "secret" badge — click "Reveal" | Full-access key for the Python pipeline (**NEVER commit, NEVER expose in browser**) |

---

## 4. Add to `.env`

Open `.env` in the project root and add these three lines (replace the placeholders with your actual values):

```bash
# Supabase
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Double-check that `.env` is in `.gitignore`** (it already should be, but verify):

```bash
grep -q '^\.env$' .gitignore && echo "✓ .env is gitignored" || echo "⚠️  ADD .env to .gitignore"
```

---

## 5. Confirm the pipeline can connect

Run this quick check:

```bash
cd /path/to/repo
source pipeline/.venv/bin/activate
python3 -c "
from pipeline.db import get_client
c = get_client()
print('Connected. Users table row count:', c.table('users').select('handle', count='exact').limit(0).execute().count)
"
```

Expected output: `Connected. Users table row count: 0` (empty table is correct — migration hasn't run yet).

If you see an error about missing env vars, double-check `.env` has all three SUPABASE_* lines.

---

## 6. Tell me you're done

Once steps 1-5 are complete, tell me in chat and I'll run the migration:

```
pipeline/migrate_to_supabase.py
```

This will ingest:
- **classified_kols.json** → `users` table (674 rows)
- **raw_expansion.json** + **circles/graph_v1.json** → `follows` table (~2,700+ edges)
- **core_tweets.json** → `tweets` table (~1,280 rows)

Idempotent — safe to re-run if anything fails partway through.

---

## Troubleshooting

**"Invalid API key"** — make sure you copied the `service_role` key for `SUPABASE_SERVICE_KEY`, not the `anon` key. They look similar but are different.

**"Could not connect to the database"** — the free tier pauses projects after a week of inactivity. Go to the dashboard, click the project, and it'll auto-resume (takes ~30 seconds).

**"relation 'users' does not exist"** — the schema didn't run. Go back to step 2 and re-run `schema.sql` in the SQL Editor.

**"permission denied for table users"** — you're using the `anon` key instead of `service_role`. Anon is RLS-locked; service_role bypasses RLS.

---

## What's next after migration

Once the data is in Supabase, all subsequent pipeline scripts read from the DB instead of JSON files:

- **score_kol.py** — reads `users` + `tweets` + derives `network_stats` from `follows` → writes back `quality_score`, `cooperability_score` columns
- **graph rebuild job** — recomputes `cluster_id`, `bridge_ratio`, `pagerank` from current `follows` table → updates `users` in place
- **Phase 1d Claude classifier** — writes classification JSON into `tweets.classification` and `users.cooperability`
- **Mode B demo (React)** — uses the Supabase JS client + anon key to run the 4-query fast-lookup against the DB

The JSON files in `pipeline/` remain as backup/history but stop being the source of truth.
