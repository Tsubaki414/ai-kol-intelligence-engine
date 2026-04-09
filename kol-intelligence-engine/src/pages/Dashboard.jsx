import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import kolsData from "../data/kols.json";

export default function Dashboard() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [sectorFilter, setSectorFilter] = useState([]);
  const [tierFilter, setTierFilter] = useState([]);
  const [languageFilter, setLanguageFilter] = useState([]);
  const [circleFilter, setCircleFilter] = useState([]);
  const [graphOnly, setGraphOnly] = useState(false);
  const [contactableOnly, setContactableOnly] = useState(false);
  const [mutualOnly, setMutualOnly] = useState(false);
  const [hideCelebrities, setHideCelebrities] = useState(true);
  const [sortBy, setSortBy] = useState("quality_score");

  // Derive filter options from actual data
  const allSectors = useMemo(
    () =>
      [
        ...new Set(kolsData.kols.map((k) => k.sector).filter(Boolean)),
      ].sort(),
    []
  );
  const allTiers = useMemo(
    () =>
      ["Mega", "Macro", "Micro", "Nano"].filter((t) =>
        kolsData.kols.some((k) => k.tier === t)
      ),
    []
  );
  const allLanguages = useMemo(
    () =>
      [...new Set(kolsData.kols.map((k) => k.language).filter(Boolean))].sort(),
    []
  );
  const allCircles = useMemo(
    () =>
      [
        ...new Set(
          kolsData.kols.flatMap((k) => k.circles || []).filter(Boolean)
        ),
      ].sort(),
    []
  );

  const filtered = useMemo(() => {
    let list = kolsData.kols;

    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (k) =>
          (k.handle || "").toLowerCase().includes(q) ||
          (k.id || "").toLowerCase().includes(q) ||
          (k.name || "").toLowerCase().includes(q) ||
          (k.bio || "").toLowerCase().includes(q)
      );
    }
    if (sectorFilter.length > 0)
      list = list.filter((k) => sectorFilter.includes(k.sector));
    if (tierFilter.length > 0)
      list = list.filter((k) => tierFilter.includes(k.tier));
    if (languageFilter.length > 0)
      list = list.filter((k) => languageFilter.includes(k.language));
    if (circleFilter.length > 0)
      list = list.filter((k) =>
        (k.circles || []).some((c) => circleFilter.includes(c))
      );
    if (graphOnly) list = list.filter((k) => k.in_graph);
    if (contactableOnly)
      list = list.filter((k) => k.cooperability?.is_contactable);
    if (mutualOnly) list = list.filter((k) => k.is_mutual_member);
    if (hideCelebrities) list = list.filter((k) => !k.is_celebrity_outbound);

    // Helper: pull a trace value from score_traces.<layer>.<sub_score>.value
    const traceVal = (k, layer, sub) =>
      (((k.score_traces || {})[layer] || {})[sub] || {}).value;

    return [...list].sort((a, b) => {
      // Nulls sort to the bottom: treat null as -1 so rows with computed
      // scores always win over null rows, regardless of the sort direction.
      const pull = (k) => {
        switch (sortBy) {
          case "quality_score":
            return a === k ? a.quality_score : b.quality_score; // placeholder
          default:
            return 0;
        }
      };
      void pull;
      const aq = (() => {
        switch (sortBy) {
          case "quality_score":        return a.quality_score;
          case "cooperability_score":  return a.cooperability_score;
          case "followers":            return a.followers_count;
          case "engagement_quality_ratio":
            return traceVal(a, "quality", "engagement_quality_ratio");
          case "content_originality":
            return traceVal(a, "quality", "content_originality");
          case "audience_authenticity":
            return traceVal(a, "quality", "audience_authenticity");
          case "sector_relevance":
            return traceVal(a, "quality", "sector_relevance");
          case "network_position":
            return traceVal(a, "quality", "network_position");
          case "pagerank":             return a.pagerank;
          case "betweenness":          return a.betweenness;
          case "t1_mutual_count":      return a.t1_mutual_count;
          default:                     return a.quality_score;
        }
      })();
      const bq = (() => {
        switch (sortBy) {
          case "quality_score":        return b.quality_score;
          case "cooperability_score":  return b.cooperability_score;
          case "followers":            return b.followers_count;
          case "engagement_quality_ratio":
            return traceVal(b, "quality", "engagement_quality_ratio");
          case "content_originality":
            return traceVal(b, "quality", "content_originality");
          case "audience_authenticity":
            return traceVal(b, "quality", "audience_authenticity");
          case "sector_relevance":
            return traceVal(b, "quality", "sector_relevance");
          case "network_position":
            return traceVal(b, "quality", "network_position");
          case "pagerank":             return b.pagerank;
          case "betweenness":          return b.betweenness;
          case "t1_mutual_count":      return b.t1_mutual_count;
          default:                     return b.quality_score;
        }
      })();
      const av = aq == null ? -1 : aq;
      const bv = bq == null ? -1 : bq;
      return bv - av;
    });
  }, [
    search,
    sectorFilter,
    tierFilter,
    languageFilter,
    circleFilter,
    graphOnly,
    contactableOnly,
    mutualOnly,
    hideCelebrities,
    sortBy,
  ]);

  const toggle = (arr, setter, val) =>
    setter(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);

  // ---- Export helpers ----
  const escapeCsvCell = (v) => {
    if (v == null) return "";
    const s = String(v);
    // Escape if contains comma, quote, newline, or carriage return
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };

  const downloadBlob = (content, filename, mime) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Helper: safely pull a sub-score value from score_traces
  const traceVal = (k, layer, sub) =>
    (((k.score_traces || {})[layer] || {})[sub] || {}).value ?? null;

  const exportCsv = () => {
    const headers = [
      "handle",
      "name",
      "bio",
      "sector",
      "tier",
      "language",
      "region",
      "circles",
      "followers",
      "quality_score",
      "cooperability_score",
      "onchain_score",
      "engagement_quality_ratio",
      "content_originality",
      "audience_authenticity",
      "sector_relevance",
      "network_position",
      "contact_signal_strength",
      "promo_willingness",
      "accessibility",
      "pagerank",
      "betweenness",
      "t1_mutual_count",
      "cross_cluster_mutual_count",
      "is_mutual_member",
      "is_bridge",
      "in_graph",
      "is_contactable",
      "contact_method",
      "public_email",
      "estimated_price_tier",
      "outreach_angle",
      "x_url",
    ];
    const rows = filtered.map((k) => [
      k.id || k.handle,
      k.name,
      k.bio,
      k.sector,
      k.tier,
      k.language,
      k.region,
      (k.circles || []).join("+"),
      k.followers_count,
      k.quality_score,
      k.cooperability_score,
      k.onchain_score,
      traceVal(k, "quality", "engagement_quality_ratio"),
      traceVal(k, "quality", "content_originality"),
      traceVal(k, "quality", "audience_authenticity"),
      traceVal(k, "quality", "sector_relevance"),
      traceVal(k, "quality", "network_position"),
      traceVal(k, "cooperability", "contact_signal_strength"),
      traceVal(k, "cooperability", "promo_willingness"),
      traceVal(k, "cooperability", "accessibility"),
      k.pagerank,
      k.betweenness,
      k.t1_mutual_count,
      k.cross_cluster_mutual_count,
      k.is_mutual_member ? "yes" : "",
      k.is_bridge ? "yes" : "",
      k.in_graph ? "yes" : "",
      k.cooperability?.is_contactable ? "yes" : "",
      k.cooperability?.contact_method,
      k.cooperability?.public_email,
      k.estimated_price_tier,
      k.outreach_angle,
      k.x_url || `https://x.com/${k.id || k.handle}`,
    ]);
    const csv = [
      headers.join(","),
      ...rows.map((r) => r.map(escapeCsvCell).join(",")),
    ].join("\n");
    // UTF-8 BOM so Excel opens Chinese characters correctly
    downloadBlob("\uFEFF" + csv, `kols_export_${filtered.length}.csv`, "text/csv;charset=utf-8");
  };

  const exportJson = () => {
    const doc = {
      exported_at: new Date().toISOString(),
      filter_applied: {
        search: search || null,
        sectors: sectorFilter,
        tiers: tierFilter,
        languages: languageFilter,
        circles: circleFilter,
        graph_only: graphOnly,
        contactable_only: contactableOnly,
        mutual_only: mutualOnly,
        hide_celebrities: hideCelebrities,
        sort_by: sortBy,
      },
      total: filtered.length,
      source: "AI KOL Intelligence Engine (three-layer v3)",
      kols: filtered,
    };
    downloadBlob(
      JSON.stringify(doc, null, 2),
      `kols_export_${filtered.length}.json`,
      "application/json"
    );
  };

  const stats = useMemo(() => {
    const total = kolsData.kols.length;
    const mutual = kolsData.kols.filter((k) => k.is_mutual_member).length;
    const celebFiltered = kolsData.kols.filter((k) => k.is_celebrity_outbound).length;
    const contactable = kolsData.kols.filter(
      (k) => k.cooperability?.is_contactable
    ).length;
    // Quality score is null for KOLs without cached tweets — average over
    // non-null rows only instead of treating null as 0 (the old bug).
    const qualityRows = kolsData.kols.filter((k) => k.quality_score != null);
    const avgQuality =
      qualityRows.length > 0
        ? qualityRows.reduce((s, k) => s + (k.quality_score || 0), 0) /
          qualityRows.length
        : 0;
    const avgCoop =
      kolsData.kols.reduce((s, k) => s + (k.cooperability_score || 0), 0) /
      Math.max(total, 1);
    return {
      total,
      mutual,
      celebFiltered,
      contactable,
      qualityScoredCount: qualityRows.length,
      avgQuality: avgQuality ? avgQuality.toFixed(0) : "—",
      avgCoop: avgCoop.toFixed(0),
    };
  }, []);

  return (
    <div className="h-full flex flex-col">
      {/* Header + stats */}
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-start justify-between mb-4 gap-4">
          <div className="flex-shrink-0">
            <h1 className="text-lg font-semibold text-text-primary">
              KOL Database
            </h1>
            <div className="text-xs text-text-muted font-mono mt-0.5">
              {filtered.length.toLocaleString()} of {stats.total.toLocaleString()} KOLs ·
              Three-layer v3 (Quality ⨯ Cooperability ⨯ On-chain)
            </div>
          </div>
          <div className="flex gap-2 text-[11px] font-mono flex-wrap">
            <StatCard label="Total" value={stats.total} />
            <StatCard label="● Mutual" value={stats.mutual} accent="emerald" />
            <StatCard
              label="Contactable"
              value={stats.contactable}
              accent="blue"
            />
            <StatCard label="✕ Celeb" value={stats.celebFiltered} accent="rose" />
            <StatCard
              label={`Quality Score`}
              value={`${stats.avgQuality} avg`}
              sub={`${stats.qualityScoredCount}/${stats.total} with tweets`}
              accent="emerald"
            />
            <StatCard label="Avg Coop" value={stats.avgCoop} sub="680/680" accent="blue" />
          </div>
        </div>

        {/* Filters row 1: search + scope */}
        <div className="flex gap-2 items-center text-xs font-mono mb-2 flex-wrap">
          <input
            type="text"
            placeholder="Search handle, name, bio..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-bg-card border border-border rounded-md px-3 py-1.5 w-64 text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-blue"
          />
          <button
            onClick={() => setMutualOnly(!mutualOnly)}
            className={`px-2 py-1 rounded border ${
              mutualOnly
                ? "bg-accent-emerald/20 border-accent-emerald text-accent-emerald"
                : "bg-bg-card border-border text-text-muted"
            }`}
            title="Show only the 16 mutual-confirmed network members"
          >
            ● mutual only
          </button>
          <button
            onClick={() => setHideCelebrities(!hideCelebrities)}
            className={`px-2 py-1 rounded border ${
              hideCelebrities
                ? "bg-accent-rose/15 border-accent-rose/40 text-accent-rose"
                : "bg-bg-card border-border text-text-muted"
            }`}
            title="Hide accounts auto-flagged as celebrities (≥5× median anchor followers)"
          >
            {hideCelebrities ? "✕" : "○"} hide celebs
          </button>
          <button
            onClick={() => setGraphOnly(!graphOnly)}
            className={`px-2 py-1 rounded border ${
              graphOnly
                ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
                : "bg-bg-card border-border text-text-muted"
            }`}
          >
            in graph only
          </button>
          <button
            onClick={() => setContactableOnly(!contactableOnly)}
            className={`px-2 py-1 rounded border ${
              contactableOnly
                ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
                : "bg-bg-card border-border text-text-muted"
            }`}
          >
            contactable only
          </button>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={exportCsv}
              disabled={filtered.length === 0}
              className="px-3 py-1.5 bg-accent-emerald/15 border border-accent-emerald/40 rounded text-accent-emerald hover:bg-accent-emerald/25 disabled:opacity-40 disabled:cursor-not-allowed"
              title={`Export ${filtered.length} KOLs as CSV (Excel-ready, UTF-8 BOM)`}
            >
              ↓ CSV
            </button>
            <button
              onClick={exportJson}
              disabled={filtered.length === 0}
              className="px-3 py-1.5 bg-accent-blue/15 border border-accent-blue/40 rounded text-accent-blue hover:bg-accent-blue/25 disabled:opacity-40 disabled:cursor-not-allowed"
              title={`Export ${filtered.length} KOLs as JSON (preserves all fields)`}
            >
              ↓ JSON
            </button>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="bg-bg-card border border-border rounded-md px-3 py-1.5 text-text-primary"
            >
              <option value="quality_score">sort: Quality Score</option>
              <option value="cooperability_score">sort: Cooperability Score</option>
              <option value="followers">sort: Followers</option>
              <option value="t1_mutual_count">sort: T1 mutuals</option>
              <option value="pagerank">sort: PageRank</option>
              <option value="betweenness">sort: Betweenness</option>
              <option value="engagement_quality_ratio">sort: EQR</option>
              <option value="content_originality">sort: Originality</option>
              <option value="audience_authenticity">sort: Authenticity</option>
              <option value="sector_relevance">sort: Sector Rel.</option>
              <option value="network_position">sort: Network Pos.</option>
            </select>
          </div>
        </div>

        {/* Filters row 2: multi-select tags */}
        <div className="flex gap-4 flex-wrap text-[10px] font-mono">
          <FilterGroup
            label="Sector"
            options={allSectors}
            selected={sectorFilter}
            onToggle={(v) => toggle(sectorFilter, setSectorFilter, v)}
          />
          <FilterGroup
            label="Tier"
            options={allTiers}
            selected={tierFilter}
            onToggle={(v) => toggle(tierFilter, setTierFilter, v)}
          />
          <FilterGroup
            label="Lang"
            options={allLanguages}
            selected={languageFilter}
            onToggle={(v) => toggle(languageFilter, setLanguageFilter, v)}
          />
          <FilterGroup
            label="Circle"
            options={allCircles}
            selected={circleFilter}
            onToggle={(v) => toggle(circleFilter, setCircleFilter, v)}
          />
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs font-mono">
          <thead className="bg-bg-panel sticky top-0 border-b border-border">
            <tr className="text-text-muted uppercase text-[10px] tracking-wider">
              <th className="px-4 py-3 text-left">Handle</th>
              <th className="px-3 py-3 text-left">Name</th>
              <th className="px-3 py-3 text-left">Sector</th>
              <th className="px-3 py-3 text-center">Tier</th>
              <th className="px-3 py-3 text-center">Lang</th>
              <th className="px-3 py-3 text-right">Followers</th>
              <th className="px-3 py-3 text-center" title="Quality Score (Layer 1)">
                Quality
              </th>
              <th className="px-3 py-3 text-center" title="Cooperability Score (Layer 3)">
                Coop
              </th>
              <th className="px-3 py-3 text-center" title="T1 mutual follow count">
                T1
              </th>
              <th
                className="px-3 py-3 text-center"
                title="Engagement Quality Ratio (EQR)"
              >
                EQR
              </th>
              <th className="px-3 py-3 text-center">Network</th>
              <th className="px-3 py-3 text-center">Contactable</th>
              <th className="px-3 py-3 text-center">Mutual</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {filtered.map((k) => {
              const eqr = traceVal(k, "quality", "engagement_quality_ratio");
              const netPos = traceVal(k, "quality", "network_position");
              return (
                <tr
                  key={k.id}
                  onClick={() => navigate(`/profile/${k.id}`)}
                  className="hover:bg-bg-hover/60 transition-colors cursor-pointer"
                >
                  <td className="px-4 py-2.5">
                    <div className="text-accent-blue">@{k.id}</div>
                  </td>
                  <td className="px-3 py-2.5 text-text-secondary truncate max-w-[160px]">
                    {k.name || "—"}
                    {k.is_bridge && (
                      <span className="ml-1 text-accent-amber">⭐</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-text-secondary truncate max-w-[120px]">
                    {k.sector || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <TierBadge tier={k.tier} />
                  </td>
                  <td className="px-3 py-2.5 text-center text-text-muted">
                    {k.language || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-text-secondary">
                    {k.followers_count != null
                      ? k.followers_count >= 1000
                        ? `${(k.followers_count / 1000).toFixed(0)}K`
                        : k.followers_count
                      : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <ScorePill value={k.quality_score} />
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <ScorePill value={k.cooperability_score} />
                  </td>
                  <td className="px-3 py-2.5 text-center text-text-muted">
                    {k.t1_mutual_count || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-center text-text-muted">
                    {eqr != null ? Math.round(eqr) : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-center text-text-muted">
                    {netPos != null ? Math.round(netPos) : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {k.cooperability?.is_contactable ? (
                      <span className="text-accent-emerald">●</span>
                    ) : (
                      <span className="text-text-dim">○</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-center text-text-muted">
                    {k.is_mutual_member ? (
                      <span className="text-accent-emerald">●</span>
                    ) : (
                      <span className="text-text-dim">–</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center text-text-muted text-xs p-10 font-mono">
            No KOLs match the current filters.
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, accent }) {
  const accentColors = {
    emerald: "text-accent-emerald",
    blue: "text-accent-blue",
    amber: "text-accent-amber",
    rose: "text-accent-rose",
  };
  return (
    <div className="bg-bg-card border border-border rounded-md px-3 py-2 min-w-[90px]">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">
        {label}
      </div>
      <div
        className={`text-base font-semibold mt-0.5 ${
          accentColors[accent] || "text-text-primary"
        }`}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[9px] text-text-muted mt-0.5">{sub}</div>
      )}
    </div>
  );
}

function FilterGroup({ label, options, selected, onToggle }) {
  if (!options || options.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-text-muted uppercase tracking-wider">{label}:</span>
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onToggle(o)}
          className={`px-2 py-0.5 rounded border ${
            selected.includes(o)
              ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
              : "bg-bg-card border-border text-text-muted hover:text-text-secondary"
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

function ScorePill({ value }) {
  if (value == null) return <span className="text-text-dim">—</span>;
  let color = "text-text-muted";
  if (value >= 75) color = "text-accent-emerald font-semibold";
  else if (value >= 55) color = "text-accent-blue";
  else if (value >= 35) color = "text-accent-amber";
  else color = "text-accent-rose";
  return <span className={color}>{value}</span>;
}

function TierBadge({ tier }) {
  if (!tier) return <span className="text-text-dim">—</span>;
  const map = {
    Mega: "bg-accent-purple/15 text-accent-purple border-accent-purple/30",
    Macro: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
    Micro: "bg-accent-emerald/15 text-accent-emerald border-accent-emerald/30",
    Nano: "bg-text-muted/15 text-text-muted border-border",
  };
  return (
    <span
      className={`px-1.5 py-0.5 text-[9px] rounded border font-semibold ${
        map[tier] || map.Nano
      }`}
    >
      {tier}
    </span>
  );
}
