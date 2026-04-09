import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";
import kolsData from "../data/kols.json";
import graphData from "../data/graph.json";
import { fetchRecentTweets } from "../lib/supabase.js";

// Layer 1 (Quality) sub-scores per scoring_spec v3 2026-04-09
const QUALITY_LABELS = {
  engagement_quality_ratio: "EQR",
  content_originality: "Originality",
  audience_authenticity: "Authenticity",
  sector_relevance: "Sector Rel.",
  network_position: "Network Pos.",
};

// Layer 3 (Cooperability) sub-scores — redesigned 2026-04-09
const COOP_LABELS = {
  contact_signal_strength: "Contact Signal",
  promo_willingness: "Promo Willing",
  accessibility: "Accessibility",
};

// Pull sub-score value from score_traces JSONB, handling null gracefully.
const getTraceValue = (kol, layer, sub) => {
  const layerTrace = (kol?.score_traces || {})[layer];
  if (!layerTrace) return null;
  const subTrace = layerTrace[sub];
  if (!subTrace) return null;
  return subTrace.value ?? null;
};

// Pull full trace object (with formula / calculation / inputs / notes).
const getTrace = (kol, layer, sub) => {
  const layerTrace = (kol?.score_traces || {})[layer];
  if (!layerTrace) return null;
  return layerTrace[sub] || null;
};

export default function Profile() {
  const { id } = useParams();
  const [showScoreBreakdown, setShowScoreBreakdown] = useState(false);
  const [listSearch, setListSearch] = useState("");
  const [listLimit, setListLimit] = useState(48);
  const [tweets, setTweets] = useState([]);
  const [tweetsStatus, setTweetsStatus] = useState("idle"); // idle | loading | ok | error | empty
  const [tweetsError, setTweetsError] = useState(null);

  // Live-fetch recent cached tweets from Supabase when viewing a single KOL.
  // Read-only, anon RLS policy gates access to the `tweets` table.
  useEffect(() => {
    if (!id) {
      setTweets([]);
      setTweetsStatus("idle");
      return;
    }
    let cancelled = false;
    setTweetsStatus("loading");
    setTweetsError(null);
    fetchRecentTweets(id, 10)
      .then((rows) => {
        if (cancelled) return;
        setTweets(rows);
        setTweetsStatus(rows.length === 0 ? "empty" : "ok");
      })
      .catch((err) => {
        if (cancelled) return;
        setTweetsError(err.message || String(err));
        setTweetsStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // --- List view ---
  if (!id) {
    const sorted = [...kolsData.kols].sort((a, b) => {
      // Prefer quality_score, fall back to cooperability_score so KOLs without
      // cached tweets (quality null) still get a sensible ranking.
      const av = a.quality_score ?? a.cooperability_score ?? 0;
      const bv = b.quality_score ?? b.cooperability_score ?? 0;
      return bv - av;
    });
    const q = listSearch.trim().toLowerCase();
    const matched = q
      ? sorted.filter(
          (k) =>
            (k.id || "").includes(q) ||
            (k.name || "").toLowerCase().includes(q) ||
            (k.bio || "").toLowerCase().includes(q) ||
            (k.sector || "").toLowerCase().includes(q)
        )
      : sorted;
    const visible = matched.slice(0, listLimit);
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold mb-1">KOL Profiles</h1>
        <p className="text-xs text-text-muted font-mono mb-4">
          {matched.length.toLocaleString()} of {kolsData.kols.length.toLocaleString()} KOLs · sorted by overall score · click any card for full profile
        </p>
        <input
          type="text"
          value={listSearch}
          onChange={(e) => {
            setListSearch(e.target.value);
            setListLimit(48);
          }}
          placeholder="Search handle, name, bio, sector..."
          className="mb-4 w-full md:w-80 bg-bg-card border border-border rounded-md px-3 py-2 text-xs text-text-primary placeholder-text-muted font-mono focus:outline-none focus:border-accent-blue"
        />
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {visible.map((k) => (
            <Link
              key={k.id}
              to={`/profile/${k.id}`}
              className="bg-bg-card border border-border rounded-lg p-3 hover:border-accent-blue transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-mono text-accent-blue truncate flex-1">
                  @{k.id}
                </div>
                <div className="flex gap-1 text-[10px] font-mono">
                  {k.quality_score != null && (
                    <span
                      className="text-accent-emerald"
                      title={`Quality ${k.quality_score}`}
                    >
                      Q{Math.round(k.quality_score)}
                    </span>
                  )}
                  {k.cooperability_score != null && (
                    <span
                      className="text-accent-blue"
                      title={`Cooperability ${k.cooperability_score}`}
                    >
                      C{Math.round(k.cooperability_score)}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-[11px] text-text-muted mt-1 truncate">
                {k.name || "—"}
              </div>
              <div className="text-[10px] text-text-muted mt-2 font-mono flex gap-1.5 flex-wrap">
                {k.tier && <span>{k.tier}</span>}
                {k.language && <span>/ {k.language}</span>}
                {k.in_graph && <span className="text-accent-emerald">· graph</span>}
              </div>
            </Link>
          ))}
        </div>
        {matched.length > listLimit && (
          <div className="mt-4 flex justify-center">
            <button
              onClick={() => setListLimit((l) => l + 48)}
              className="px-4 py-2 text-xs font-mono bg-bg-card border border-border rounded hover:border-accent-blue text-text-secondary hover:text-text-primary"
            >
              Load more ({matched.length - listLimit} remaining)
            </button>
          </div>
        )}
        {matched.length === 0 && (
          <div className="text-center text-text-muted text-xs font-mono py-12">
            No KOLs match "{listSearch}".
          </div>
        )}
      </div>
    );
  }

  const kol = kolsData.kols.find((k) => k.id === id);
  if (!kol) {
    return (
      <div className="p-6 text-text-muted">
        KOL "{id}" not found.{" "}
        <Link to="/profile" className="text-accent-blue">
          Back to list
        </Link>
      </div>
    );
  }

  // Find connected nodes in the graph (only for in-graph KOLs)
  const neighbors = kol.in_graph
    ? graphData.edges
        .filter((e) => e.source === id || e.target === id)
        .map((e) => ({
          other: e.source === id ? e.target : e.source,
          tier: e.tier,
          type: e.type,
        }))
    : [];

  const t1Neighbors = neighbors.filter((n) => n.tier === 1);
  const t2Neighbors = neighbors.filter((n) => n.tier === 2);

  // Quality radar: 5 Layer 1 sub-scores. Null sub-scores render as a faint
  // dashed outline at 0 (so the dimension is still visible) instead of pulling
  // the polygon to the center as if the KOL legitimately scored zero.
  const qualityRadarData = Object.keys(QUALITY_LABELS).map((k) => {
    const v = getTraceValue(kol, "quality", k);
    return {
      dimension: QUALITY_LABELS[k],
      score: v ?? 0,
      isNull: v == null,
      fullMark: 100,
    };
  });
  const nullSubScoreCount = qualityRadarData.filter((d) => d.isNull).length;
  // Cooperability bars: 3 Layer 3 sub-scores
  const coopBreakdown = Object.keys(COOP_LABELS).map((k) => ({
    key: k,
    label: COOP_LABELS[k],
    value: getTraceValue(kol, "cooperability", k),
    trace: getTrace(kol, "cooperability", k),
  }));
  const qualityBreakdown = Object.keys(QUALITY_LABELS).map((k) => ({
    key: k,
    label: QUALITY_LABELS[k],
    value: getTraceValue(kol, "quality", k),
    trace: getTrace(kol, "quality", k),
  }));
  const anyScoreAvailable =
    kol.quality_score != null || kol.cooperability_score != null;

  return (
    <div className="p-6 max-w-5xl">
      <Link
        to="/profile"
        className="text-xs text-text-muted font-mono hover:text-text-primary"
      >
        ← back to profiles
      </Link>

      {/* Header card */}
      <div className="mt-4 bg-bg-card border border-border rounded-lg p-6">
        <div className="flex items-start justify-between gap-6">
          <div className="flex-1 min-w-0">
            <div className="text-2xl font-semibold text-text-primary font-mono">
              {kol.handle}
            </div>
            {kol.name && (
              <div className="text-sm text-text-secondary mt-1">{kol.name}</div>
            )}

            <div className="flex gap-2 mt-3 flex-wrap">
              {/* Network status — most important badge */}
              {kol.is_mutual_member ? (
                <Tag color="emerald">● mutual member</Tag>
              ) : kol.is_celebrity_outbound ? (
                <Tag color="rose">✕ celebrity (auto-filtered)</Tag>
              ) : kol.in_graph ? (
                <Tag color="gray">○ watched (one-way)</Tag>
              ) : (
                <Tag color="gray">database only</Tag>
              )}
              {kol.sector && <Tag color="blue">{kol.sector}</Tag>}
              {kol.tier && <Tag color="amber">{kol.tier}</Tag>}
              {kol.language && <Tag color="purple">{kol.language}</Tag>}
              {kol.region && <Tag color="rose">{kol.region}</Tag>}
              {kol.circles?.map((c) => (
                <Tag key={c} color="emerald">
                  {c}
                </Tag>
              ))}
              {kol.is_bridge && kol.is_mutual_member && <Tag color="amber">⭐ bridge</Tag>}
              {kol.verified && <Tag color="blue">✓ verified</Tag>}
              {kol.is_mutual_member && kol.cluster != null && (
                <Tag color="emerald">cluster #{kol.cluster}</Tag>
              )}
            </div>
          </div>

          {/* Three parallel scores — never fused into a single "overall" */}
          {anyScoreAvailable && (
            <div className="flex gap-4 flex-shrink-0">
              <div className="text-right" title={kol.quality_score == null ? "Quality score requires tweet analysis. Run Import Your Own Seeds to trigger analysis for this handle." : undefined}>
                <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono">
                  Quality
                </div>
                <div className={`text-3xl font-semibold font-mono ${kol.quality_score != null ? "text-accent-emerald" : "text-text-muted"}`}>
                  {kol.quality_score != null ? kol.quality_score : "—"}
                </div>
                <div className="text-[10px] text-text-muted font-mono">
                  {kol.quality_score != null ? (kol.quality_confidence || "n/a") : "needs tweets"}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono">
                  Coop
                </div>
                <div className="text-3xl font-semibold text-accent-blue font-mono">
                  {kol.cooperability_score != null ? kol.cooperability_score : "—"}
                </div>
                <div className="text-[10px] text-text-muted font-mono">
                  {kol.cooperability_confidence || "n/a"}
                </div>
              </div>
              {kol.onchain_score != null && (
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono">
                    On-chain
                  </div>
                  <div className="text-3xl font-semibold text-accent-amber font-mono">
                    {kol.onchain_score}
                  </div>
                  <div className="text-[10px] text-text-muted font-mono">
                    {kol.onchain_confidence || "n/a"}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {kol.bio && (
          <div className="mt-4 text-xs text-text-secondary leading-relaxed border-t border-border pt-4">
            {kol.bio}
          </div>
        )}

        <div className="mt-4 flex justify-between items-center">
          <a
            href={kol.x_url}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] font-mono text-accent-blue hover:underline"
          >
            open on x.com ↗
          </a>
        </div>
      </div>

      {/* Metric cards */}
      <div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-3">
        <Metric
          label="Followers"
          value={kol.followers_count?.toLocaleString() || "—"}
        />
        <Metric
          label="Following"
          value={kol.following_count?.toLocaleString() || "—"}
        />
        <Metric
          label="Tweets"
          value={kol.tweet_count?.toLocaleString() || "—"}
        />
        {kol.is_mutual_member && (
          <>
            <Metric
              label="PageRank"
              value={(kol.pagerank || 0).toFixed(4)}
            />
            <Metric
              label="Betweenness"
              value={(kol.betweenness || 0).toFixed(4)}
            />
          </>
        )}
      </div>

      {/* Layer 1: Quality Score — radar + breakdown */}
      {kol.quality_score != null && (
        <div className="mt-6 bg-bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-text-primary">
              Layer 1 · Quality Score Breakdown
            </h3>
            <button
              onClick={() => setShowScoreBreakdown(!showScoreBreakdown)}
              className="text-[11px] font-mono text-accent-blue hover:underline"
            >
              {showScoreBreakdown ? "hide" : "see"} calculation
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Radar */}
            <div className="h-64 relative">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={qualityRadarData}>
                  <PolarGrid stroke="#2A3040" />
                  <PolarAngleAxis
                    dataKey="dimension"
                    tick={{
                      fill: "#94A3B8",
                      fontSize: 10,
                      fontFamily: "JetBrains Mono",
                    }}
                  />
                  <PolarRadiusAxis
                    angle={90}
                    domain={[0, 100]}
                    tick={{ fill: "#64748B", fontSize: 9 }}
                  />
                  <Radar
                    name="Quality"
                    dataKey="score"
                    stroke="#10B981"
                    fill="#10B981"
                    fillOpacity={0.35}
                    strokeWidth={2}
                  />
                </RadarChart>
              </ResponsiveContainer>
              {nullSubScoreCount > 0 && (
                <div className="absolute bottom-1 left-1 right-1 text-center text-[9px] font-mono text-text-muted italic">
                  {nullSubScoreCount}/5 sub-score{nullSubScoreCount === 1 ? "" : "s"} unavailable — drawn at zero
                </div>
              )}
            </div>

            {/* Breakdown table */}
            <div className="space-y-2 font-mono text-[11px]">
              {qualityBreakdown.map((row) => {
                const val = row.value;
                const pct = val != null ? val : 0;
                return (
                  <div key={row.key}>
                    <div className="flex justify-between text-text-secondary">
                      <span>{row.label}</span>
                      <span
                        className={
                          val != null
                            ? "text-text-primary"
                            : "text-text-muted italic"
                        }
                      >
                        {val != null ? Math.round(val) : "null"}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 bg-bg-hover rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-accent-blue to-accent-emerald rounded-full"
                        style={{ width: `${pct}%`, opacity: val != null ? 1 : 0.3 }}
                      />
                    </div>
                    {showScoreBreakdown && row.trace && (
                      <div className="text-[9px] text-text-muted mt-1 pl-2 border-l border-border">
                        {row.trace.calculation || row.trace.notes || "—"}
                      </div>
                    )}
                  </div>
                );
              })}
              <div className="flex justify-between pt-3 border-t border-border mt-3">
                <span className="text-text-muted">
                  Quality (weighted avg of non-null)
                </span>
                <span className="text-accent-emerald font-semibold">
                  {kol.quality_score}
                </span>
              </div>
            </div>
          </div>

          {showScoreBreakdown && (
            <div className="mt-4 pt-4 border-t border-border text-[11px] text-text-muted font-mono leading-relaxed">
              <div>
                <span className="text-text-secondary">Formula (Layer 1):</span>{" "}
                <code className="bg-bg-hover px-1 rounded">
                  Σ(weight × value) / Σ(weight) over non-null sub-scores
                </code>
              </div>
              <div className="mt-1">
                <span className="text-text-secondary">Weights:</span>{" "}
                EQR 30% · Originality 25% · Authenticity 15% · Sector 15% · Network 15%
              </div>
            </div>
          )}
        </div>
      )}

      {/* Layer 3: Cooperability Score — bars only (no radar) */}
      {kol.cooperability_score != null && (
        <div className="mt-4 bg-bg-card border border-border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-text-primary">
              Layer 3 · Cooperability Score Breakdown
            </h3>
            <div className="text-[10px] font-mono text-text-muted">
              redesigned 2026-04-09
            </div>
          </div>
          <div className="space-y-3 font-mono text-[11px]">
            {coopBreakdown.map((row) => {
              const val = row.value;
              return (
                <div key={row.key}>
                  <div className="flex justify-between text-text-secondary">
                    <span>{row.label}</span>
                    <span
                      className={
                        val != null
                          ? "text-text-primary"
                          : "text-text-muted italic"
                      }
                    >
                      {val != null ? Math.round(val) : "null"}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 bg-bg-hover rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-accent-blue to-accent-blue rounded-full"
                      style={{
                        width: `${val != null ? val : 0}%`,
                        opacity: val != null ? 1 : 0.3,
                      }}
                    />
                  </div>
                  {row.trace && row.trace.calculation && (
                    <div className="text-[9px] text-text-muted mt-1 pl-2 border-l border-border">
                      {row.trace.calculation}
                      {row.trace.notes && (
                        <div className="text-accent-amber mt-0.5">
                          note: {row.trace.notes}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="flex justify-between pt-3 border-t border-border mt-3">
              <span className="text-text-muted">
                Cooperability (40% contact + 30% promo + 30% accessibility)
              </span>
              <span className="text-accent-blue font-semibold">
                {kol.cooperability_score}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Cooperability */}
      {kol.cooperability && (
        <div className="mt-4 bg-bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            Cooperability
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px] font-mono">
            <div className="space-y-1.5">
              <Metric
                label="Contactable"
                value={
                  kol.cooperability.is_contactable ? (
                    <span className="text-accent-emerald">YES</span>
                  ) : (
                    <span className="text-text-muted">NO</span>
                  )
                }
              />
              <Metric
                label="Accepts paid promos"
                value={
                  kol.cooperability.accepts_paid_promos ? (
                    <span className="text-accent-emerald">YES</span>
                  ) : (
                    <span className="text-text-muted">NO</span>
                  )
                }
              />
              <Metric
                label="Contact method"
                value={kol.cooperability.contact_method || "—"}
              />
              {kol.cooperability.public_email && (
                <Metric label="Email" value={kol.cooperability.public_email} />
              )}
              {kol.cooperability.public_telegram && (
                <Metric
                  label="Telegram"
                  value={kol.cooperability.public_telegram}
                />
              )}
            </div>
            <div className="space-y-2 text-text-secondary">
              {kol.outreach_angle && (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-muted mb-1">
                    Outreach angle
                  </div>
                  <div className="text-[11px] leading-relaxed">
                    {kol.outreach_angle}
                  </div>
                </div>
              )}
              {kol.estimated_price_tier && (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-muted mb-1">
                    Estimated price
                  </div>
                  <div className="text-[11px]">{kol.estimated_price_tier}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Recent tweets — live-fetched from Supabase tweets cache */}
      <div className="mt-4 bg-bg-card border border-border rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-mono text-accent-blue uppercase tracking-widest">
            Recent cached tweets
          </h3>
          <div className="text-[10px] font-mono text-text-muted">
            live from Supabase · tweets table
          </div>
        </div>
        {tweetsStatus === "loading" && (
          <div className="text-[11px] font-mono text-text-muted animate-pulse">
            Loading tweets…
          </div>
        )}
        {tweetsStatus === "error" && (
          <div className="text-[11px] font-mono text-accent-rose">
            Failed to load tweets: {tweetsError}
          </div>
        )}
        {tweetsStatus === "empty" && (
          <div className="text-[11px] font-mono text-text-muted">
            No cached tweets for @{id} yet. Run the Phase 1d classifier to fetch and
            analyze their last 20 posts.
          </div>
        )}
        {tweetsStatus === "ok" && (
          <div className="space-y-3">
            {tweets.map((t) => {
              const pm = t.public_metrics || {};
              const cls = t.classification || null;
              return (
                <div
                  key={t.tweet_id}
                  className="border-l-2 border-border pl-3 py-1"
                >
                  <div className="text-[12px] text-text-primary leading-relaxed whitespace-pre-wrap break-words">
                    {t.text}
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-[10px] font-mono text-text-muted flex-wrap">
                    <span>
                      {t.created_at
                        ? new Date(t.created_at).toLocaleDateString()
                        : "—"}
                    </span>
                    <span>· {t.lang || "??"}</span>
                    {t.tweet_type && <span>· {t.tweet_type}</span>}
                    <span className="text-accent-blue">
                      ♥ {pm.like_count ?? 0}
                    </span>
                    <span className="text-accent-emerald">
                      ↻ {pm.retweet_count ?? 0}
                    </span>
                    <span className="text-accent-amber">
                      💬 {pm.reply_count ?? 0}
                    </span>
                    {cls?.content_class && (
                      <span className="ml-auto px-1.5 py-0.5 rounded bg-bg-hover border border-border text-text-secondary">
                        {cls.content_class}
                      </span>
                    )}
                    {cls?.is_ai_crypto_related && (
                      <span className="px-1.5 py-0.5 rounded bg-accent-emerald/10 border border-accent-emerald/30 text-accent-emerald">
                        AI+crypto
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Network connections — only meaningful for mutual members */}
      {kol.is_mutual_member && (t1Neighbors.length > 0 || t2Neighbors.length > 0) && (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-bg-card border border-border rounded-lg p-4">
            <h3 className="text-xs font-mono text-accent-emerald uppercase tracking-widest mb-3">
              ✅ T1 Confirmed mutual ({t1Neighbors.length})
            </h3>
            {t1Neighbors.length === 0 ? (
              <div className="text-[11px] text-text-muted font-mono">
                No confirmed mutual follows in the current dataset.
              </div>
            ) : (
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {t1Neighbors.map((n, i) => (
                  <Link
                    key={i}
                    to={`/profile/${n.other}`}
                    className="block text-[11px] font-mono text-accent-blue hover:underline"
                  >
                    @{n.other}
                  </Link>
                ))}
              </div>
            )}
          </div>

          <div className="bg-bg-card border border-border rounded-lg p-4">
            <h3 className="text-xs font-mono text-accent-blue uppercase tracking-widest mb-3">
              → T2 One-way connections ({t2Neighbors.length})
            </h3>
            {t2Neighbors.length === 0 ? (
              <div className="text-[11px] text-text-muted font-mono">None.</div>
            ) : (
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {t2Neighbors.slice(0, 30).map((n, i) => (
                  <Link
                    key={i}
                    to={`/profile/${n.other}`}
                    className="block text-[11px] font-mono text-text-secondary hover:text-accent-blue"
                  >
                    @{n.other}
                  </Link>
                ))}
                {t2Neighbors.length > 30 && (
                  <div className="text-[10px] text-text-muted pt-1">
                    ... +{t2Neighbors.length - 30} more
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Honest notice for non-mutual KOLs */}
      {!kol.is_mutual_member && (
        <div className="mt-4 bg-bg-card border border-border rounded-lg p-5">
          <div className="text-xs text-text-secondary leading-relaxed">
            <span className="font-semibold text-text-primary">
              {kol.is_celebrity_outbound
                ? "Celebrity (auto-filtered):"
                : kol.in_graph
                ? "Watched (one-way only):"
                : "Database-only KOL:"}
            </span>{" "}
            {kol.is_celebrity_outbound ? (
              <>
                This account is auto-flagged as a celebrity ({kol.followers_count?.toLocaleString()}{" "}
                followers, ≥5× median anchor followers). Anchors follow them, but they
                almost certainly don't follow back. They are an external megaphone, not
                a network member, and are excluded from PageRank / cluster computation.
              </>
            ) : kol.in_graph ? (
              <>
                {kol.anchor_count || 0}/16 anchors follow this account, but we have NOT
                verified mutual follow. <strong>Asymmetric follow ≠ in the circle</strong> —
                this is not a network member, just an outreach target. To verify mutual,
                paste this handle into{" "}
                <Link to="/discovery" className="text-accent-blue hover:underline">
                  Discovery → Mode B
                </Link>{" "}
                and run the pipeline.
              </>
            ) : (
              <>
                This KOL is classified and scored from their profile, but no anchor in
                our seed set follows them. They can still be contacted directly.
                Paste their handle into{" "}
                <Link to="/discovery" className="text-accent-blue hover:underline">
                  Discovery → Mode B
                </Link>{" "}
                to grow their network.
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="bg-bg-panel border border-border rounded px-3 py-2">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">
        {label}
      </div>
      <div className="text-sm text-text-primary mt-0.5 break-all">{value}</div>
    </div>
  );
}

function Tag({ color, children }) {
  const colorMap = {
    blue: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
    emerald: "bg-accent-emerald/15 text-accent-emerald border-accent-emerald/30",
    amber: "bg-accent-amber/15 text-accent-amber border-accent-amber/30",
    rose: "bg-accent-rose/15 text-accent-rose border-accent-rose/30",
    purple: "bg-accent-purple/15 text-accent-purple border-accent-purple/30",
    gray: "bg-bg-hover text-text-muted border-border",
  };
  return (
    <span
      className={`text-[10px] font-mono px-2 py-0.5 rounded border ${colorMap[color] || colorMap.gray}`}
    >
      {children}
    </span>
  );
}
