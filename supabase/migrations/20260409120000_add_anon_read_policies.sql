-- Add SELECT-only RLS policies for the anon role.
-- See supabase/schema.sql for the full design rationale.
--
-- Safe to rerun: drops existing policies first.

DROP POLICY IF EXISTS "anon_read_users"   ON users;
DROP POLICY IF EXISTS "anon_read_follows" ON follows;
DROP POLICY IF EXISTS "anon_read_tweets"  ON tweets;
DROP POLICY IF EXISTS "anon_read_seeds"   ON seeds;

CREATE POLICY "anon_read_users"   ON users   FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon_read_follows" ON follows FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon_read_tweets"  ON tweets  FOR SELECT TO anon USING (TRUE);
CREATE POLICY "anon_read_seeds"   ON seeds   FOR SELECT TO anon USING (TRUE);
