// Thin fetch wrapper around the Supabase REST API.
//
// We deliberately avoid the @supabase/supabase-js client (~30KB gzip) since
// the demo only needs a few read-only queries. The anon key is safe to ship
// in the browser bundle — Supabase RLS policies (see supabase/schema.sql)
// gate all writes, and every SELECT-eligible column is public-by-design
// (public X profile data + computed scores we want visible).

const SUPABASE_URL = "https://jsnbkgdivqwfwlqvbotq.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpzbmJrZ2RpdnF3ZndscXZib3RxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU3MTYwNDUsImV4cCI6MjA5MTI5MjA0NX0.dBFvnYifFv-s6V1cDg8E4ayn293DDgHEB-2V-G4maug";

const BASE_HEADERS = {
  apikey: SUPABASE_ANON_KEY,
  Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
};

/**
 * Fetch cached recent tweets for one KOL, newest first.
 * Returns [] if the KOL has no cached tweets yet.
 */
export async function fetchRecentTweets(handle, limit = 10) {
  if (!handle) return [];
  const h = handle.toString().replace(/^@/, "").toLowerCase();
  const url =
    `${SUPABASE_URL}/rest/v1/tweets` +
    `?author_handle=eq.${encodeURIComponent(h)}` +
    `&select=tweet_id,created_at,text,lang,tweet_type,public_metrics,classification` +
    `&order=created_at.desc` +
    `&limit=${limit}`;

  const res = await fetch(url, { headers: BASE_HEADERS });
  if (!res.ok) {
    throw new Error(`tweets fetch failed: HTTP ${res.status}`);
  }
  return await res.json();
}
