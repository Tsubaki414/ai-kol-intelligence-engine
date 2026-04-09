import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const COST_PER_USER = 0.0088;
const HUB_MIN_ANCHORS = 2;
const HUB_MAX_SHOW = 200;
const MAX_FOLLOWING_PER_SEED = 1000;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// ---------------------------------------------------------------------------
// X API helpers
// ---------------------------------------------------------------------------

async function xGet(path: string, token: string) {
  const res = await fetch(`https://api.x.com/2${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 429) {
    const reset = res.headers.get("x-rate-limit-reset");
    return { error: `rate_limited`, reset };
  }
  if (!res.ok) {
    return { error: `http_${res.status}` };
  }
  return await res.json();
}

async function resolveHandle(handle: string, token: string) {
  const data = await xGet(
    `/users/by/username/${handle}?user.fields=public_metrics,description,name`,
    token
  );
  return data?.data ?? null;
}

async function fetchFollowing(userId: string, token: string): Promise<string[]> {
  const handles: string[] = [];
  let paginationToken: string | null = null;
  let pages = 0;
  const maxPages = Math.ceil(MAX_FOLLOWING_PER_SEED / 1000);

  while (pages < maxPages) {
    const qs = new URLSearchParams({
      max_results: "1000",
      "user.fields": "public_metrics,description,name",
    });
    if (paginationToken) qs.set("pagination_token", paginationToken);

    const data = await xGet(`/users/${userId}/following?${qs}`, token);
    if (data?.error) break;

    for (const u of data?.data ?? []) {
      handles.push(u.username.toLowerCase());
    }
    paginationToken = data?.meta?.next_token ?? null;
    pages++;
    if (!paginationToken) break;
  }
  return handles;
}

// ---------------------------------------------------------------------------
// Supabase helpers
// ---------------------------------------------------------------------------

function getSupabase() {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
}

async function loadCachedFollowing(
  db: ReturnType<typeof getSupabase>,
  handles: string[]
): Promise<Record<string, Set<string>>> {
  const { data } = await db
    .from("follows")
    .select("follower_handle,followee_handle")
    .in("follower_handle", handles);

  const result: Record<string, Set<string>> = {};
  for (const row of data ?? []) {
    if (!result[row.follower_handle]) result[row.follower_handle] = new Set();
    result[row.follower_handle].add(row.followee_handle);
  }
  return result;
}

async function loadProfiles(
  db: ReturnType<typeof getSupabase>,
  handles: string[]
): Promise<Record<string, Record<string, unknown>>> {
  const { data } = await db
    .from("users")
    .select("handle,name,bio,followers_count,following_count,tier")
    .in("handle", handles);
  const result: Record<string, Record<string, unknown>> = {};
  for (const row of data ?? []) result[row.handle] = row;
  return result;
}

async function queryMutualFollows(
  db: ReturnType<typeof getSupabase>,
  handles: string[]
): Promise<[string, string][]> {
  const { data } = await db
    .from("mutual_follows")
    .select("handle_a,handle_b")
    .in("handle_a", handles)
    .in("handle_b", handles);
  return (data ?? []).map((r) => [r.handle_a, r.handle_b]);
}

async function queryHubMutualConfirmation(
  db: ReturnType<typeof getSupabase>,
  hubHandles: string[],
  seedHandles: string[]
): Promise<Set<string>> {
  if (!hubHandles.length) return new Set();
  const { data } = await db
    .from("follows")
    .select("follower_handle")
    .in("follower_handle", hubHandles)
    .in("followee_handle", seedHandles);
  return new Set((data ?? []).map((r) => r.follower_handle));
}

async function saveToSupabase(
  db: ReturnType<typeof getSupabase>,
  handle: string,
  profile: Record<string, unknown>,
  followedHandles: string[]
) {
  // Upsert seed user
  await db.from("users").upsert({
    handle,
    name: profile.name,
    bio: profile.description,
    followers_count: (profile.public_metrics as Record<string,number>)?.followers_count,
    following_count: (profile.public_metrics as Record<string,number>)?.following_count,
    x_id: profile.id,
    source: "custom_seed_import",
  }, { onConflict: "handle" });

  // Upsert follow edges in batches
  const rows = followedHandles.map((f) => ({
    follower_handle: handle,
    followee_handle: f,
    source: "custom_seed_import",
  }));
  for (let i = 0; i < rows.length; i += 200) {
    await db.from("follows").upsert(rows.slice(i, i + 200), {
      onConflict: "follower_handle,followee_handle",
    });
  }
}

// ---------------------------------------------------------------------------
// Graph builder (mirrors run_custom_seeds.py logic)
// ---------------------------------------------------------------------------

function buildGraph(
  seedHandles: string[],
  seedProfiles: Record<string, Record<string, unknown>>,
  allFollowings: Record<string, Set<string>>,
  mutualPairs: [string, string][],
  confirmedHubs: Set<string>,
  hubCounts: Record<string, number>
) {
  const seedSet = new Set(seedHandles);
  const confirmedPairs = new Set(mutualPairs.map(([a, b]) => `${a}|${b}`));

  const edges: Record<string, unknown>[] = [];

  // Seed↔seed T1 mutual
  for (const [a, b] of mutualPairs) {
    edges.push({ source: a, target: b, tier: 1, type: "mutual", kind: "confirmed" });
  }
  // Seed↔seed T2 one-way
  for (const s of seedHandles) {
    for (const other of seedHandles) {
      if (s === other) continue;
      if (confirmedPairs.has(`${s}|${other}`) || confirmedPairs.has(`${other}|${s}`)) continue;
      if (allFollowings[s]?.has(other)) {
        edges.push({ source: s, target: other, tier: 2, type: "oneway", kind: "one_way" });
      }
    }
  }

  // Top hubs
  const topHubs = Object.entries(hubCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, HUB_MAX_SHOW);
  const hubSet = new Set(topHubs.map(([h]) => h));

  // Seed→hub edges
  for (const seed of seedHandles) {
    for (const [hub] of topHubs) {
      if (allFollowings[seed]?.has(hub)) {
        const tier = confirmedHubs.has(hub) ? 1 : 2;
        edges.push({ source: seed, target: hub, tier, type: tier === 1 ? "mutual" : "oneway", kind: tier === 1 ? "confirmed" : "seed_to_hub" });
      }
    }
  }

  const tier = (f: number) => f >= 100000 ? "Mega" : f >= 10000 ? "Macro" : f >= 1000 ? "Micro" : "Nano";

  const nodes: Record<string, unknown>[] = [];

  for (const handle of seedHandles) {
    const p = seedProfiles[handle] ?? {};
    const followers = (p.followers_count as number) ?? 0;
    const t1 = mutualPairs.filter(([a, b]) => a === handle || b === handle).length
      + [...confirmedHubs].filter((h) => allFollowings[handle]?.has(h)).length;
    nodes.push({
      id: handle, label: handle,
      name: p.name ?? handle,
      description: p.bio ?? "",
      followers_count: followers,
      following_count: p.following_count ?? 0,
      is_mutual_member: true,
      is_celebrity_outbound: false,
      is_bridge: t1 >= 2,
      type: "anchor",
      t1_mutual_count: t1,
      cluster: 0,
      circles: ["Custom Seeds"],
      tier: (p.tier as string) ?? tier(followers),
      in_graph: true,
      pagerank: null,
      betweenness: null,
    });
  }

  for (const [hub, count] of topHubs) {
    const isConfirmed = confirmedHubs.has(hub);
    nodes.push({
      id: hub, label: hub, name: hub,
      is_mutual_member: isConfirmed,
      is_celebrity_outbound: false,
      is_bridge: false,
      type: "hub",
      anchor_count: count,
      in_graph: true,
      cluster: isConfirmed ? 0 : null,
      circles: isConfirmed ? ["Custom Seeds"] : [],
      tier: null, pagerank: null, betweenness: null,
    });
  }

  const mutualCount = edges.filter((e) => e.tier === 1).length;
  const onewayCount = edges.filter((e) => e.tier === 2).length;
  const totalFetched = Object.values(allFollowings).reduce((s, f) => s + f.size, 0);

  return {
    nodes, edges,
    metadata: {
      source: "custom_seeds",
      total_nodes: nodes.length,
      total_edges: edges.length,
      mutual_members: seedHandles.length + confirmedHubs.size,
      watched_nodes: topHubs.length - confirmedHubs.size,
      celebrity_filtered: 0,
      connected_clusters: 1, clusters_found: 1, isolated_nodes: 0,
      cluster_summary: [{
        cluster_id: 0,
        size: seedHandles.length,
        members: seedHandles,
        recommended_entry_point: `@${seedHandles[0]}`,
        bridge_nodes: nodes.filter((n) => n.is_bridge && n.is_mutual_member).map((n) => `@${n.id}`).slice(0, 3),
        circles_touched: ["Custom Seeds"],
      }],
      top_pagerank: [], top_betweenness: [],
      edge_breakdown: {
        tier_1_mutual: mutualCount,
        tier_2a_oneway_anchor: onewayCount,
        tier_2b_anchor_to_hub: 0, tier_2c_anchor_to_peripheral: 0,
        tier_3_cofollow_inferred: 0, tier_3b_peripheral_cofollow: 0,
      },
      input_data: {
        circles: 1,
        anchors_from_circles: seedHandles.length,
        total_raw_following_records_analyzed: totalFetched,
        cost_usd_total: Math.round(totalFetched * COST_PER_USER * 100) / 100,
      },
    },
  };
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { handles } = await req.json();
    if (!Array.isArray(handles) || handles.length < 2) {
      return new Response(JSON.stringify({ error: "Need at least 2 handles" }), {
        status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    const cleanHandles: string[] = [...new Set(
      handles.map((h: string) => h.trim().replace(/^@/, "").toLowerCase())
        .filter((h: string) => /^[a-z0-9_]{1,15}$/.test(h))
    )].slice(0, 20);

    const db = getSupabase();
    const xToken = Deno.env.get("X_BEARER_TOKEN")!;

    // 1. Load cached following from Supabase
    const cached = await loadCachedFollowing(db, cleanHandles);
    const missing = cleanHandles.filter((h) => !cached[h]);

    const progress: string[] = [];
    if (Object.keys(cached).length > 0) {
      progress.push(`✓ ${Object.keys(cached).length} seeds loaded from cache`);
    }

    // 2. Fetch missing seeds from X API
    const apiFollowings: Record<string, Set<string>> = {};
    const apiProfiles: Record<string, Record<string, unknown>> = {};

    for (const handle of missing) {
      progress.push(`→ Fetching @${handle} from X API…`);
      const user = await resolveHandle(handle, xToken);
      if (!user) { progress.push(`✗ @${handle} not found`); continue; }

      const followedHandles = await fetchFollowing(user.id, xToken);
      apiFollowings[handle] = new Set(followedHandles);
      apiProfiles[handle] = user;
      await saveToSupabase(db, handle, user, followedHandles);
      progress.push(`✓ @${handle}: ${followedHandles.length} followings fetched & cached`);
    }

    const allFollowings: Record<string, Set<string>> = { ...cached, ...apiFollowings };
    const availableSeeds = cleanHandles.filter((h) => allFollowings[h]);

    // 3. Hub candidates
    const hubCounts: Record<string, number> = {};
    const seedSet = new Set(availableSeeds);
    for (const seed of availableSeeds) {
      for (const f of allFollowings[seed]) {
        if (!seedSet.has(f)) hubCounts[f] = (hubCounts[f] ?? 0) + 1;
      }
    }
    const filteredHubs = Object.fromEntries(
      Object.entries(hubCounts).filter(([, c]) => c >= HUB_MIN_ANCHORS)
    );

    // 4. Mutual verification from Supabase
    const mutualPairs = await queryMutualFollows(db, availableSeeds);
    const topHubHandles = Object.entries(filteredHubs)
      .sort((a, b) => b[1] - a[1]).slice(0, HUB_MAX_SHOW).map(([h]) => h);
    const confirmedHubs = await queryHubMutualConfirmation(db, topHubHandles, availableSeeds);

    // 5. Load seed profiles
    const dbProfiles = await loadProfiles(db, availableSeeds);
    const seedProfiles = { ...dbProfiles, ...apiProfiles };

    // 6. Build graph
    const graph = buildGraph(availableSeeds, seedProfiles, allFollowings, mutualPairs, confirmedHubs, filteredHubs);

    return new Response(
      JSON.stringify({ graph, progress }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (err) {
    return new Response(
      JSON.stringify({ error: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
