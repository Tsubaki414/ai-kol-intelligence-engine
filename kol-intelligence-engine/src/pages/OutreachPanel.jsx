import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import kolsData from "../data/kols.json";
import graphData from "../data/graph.json";

/**
 * Outreach Priority Panel — referral-chain action planner.
 *
 * Three-column layout expressing the methodology v3 narrative:
 *
 *   🗝️ Gateway KOLs    → Attack first. High unlock-value + contactable.
 *   🎯 Strategic Targets → Hard to reach, but each row shows which Gateway
 *                         can warm-intro them. "Attack after Gateway."
 *   ⚡ Quick Wins        → Easy bookings for case studies. Limited unlock.
 *
 * All three columns are restricted to mutual members (27 at time of writing).
 * Watched / celebrity-filtered / merely-classified KOLs do NOT appear here —
 * without a confirmed mutual-follow relationship, there is no referral chain
 * to leverage.
 *
 * Rankings are percentile-based over the current 27-member mutual set, NOT
 * absolute thresholds. This keeps the panel usable as the subgraph grows.
 */

// ------- Importance & Unlock-value math -------

function computeImportance(member, maxPr, maxLogF) {
  const pr = (member.pagerank || 0) / (maxPr || 1);
  const logF = Math.log(Math.max(member.followers_count || 1, 1)) / (maxLogF || 1);
  return (0.5 * pr + 0.5 * logF) * 100;
}

function buildT1NeighborMap(graph) {
  const map = new Map();
  for (const e of graph.edges || []) {
    if (e.tier !== 1) continue;
    if (!map.has(e.source)) map.set(e.source, new Set());
    if (!map.has(e.target)) map.set(e.target, new Set());
    map.get(e.source).add(e.target);
    map.get(e.target).add(e.source);
  }
  return map;
}

function percentile(sortedArr, p) {
  if (!sortedArr.length) return 0;
  const idx = Math.min(Math.floor(sortedArr.length * p), sortedArr.length - 1);
  return sortedArr[idx];
}

// Pull network_position sub-score from score_traces when quality_score is null
function effectiveQuality(k) {
  if (k.quality_score != null) return k.quality_score;
  const traces = k.score_traces || {};
  const np = (traces.quality || {}).network_position || {};
  return np.value ?? null;
}

// ------- Main component -------

export default function OutreachPanel() {
  const [selectedHandle, setSelectedHandle] = useState(null);

  const {
    gateway,
    strategic,
    quickWin,
    excludedBrands,
    thresholds,
    totals,
    t1Neighbors,
  } = useMemo(() => {
      const allKols = kolsData.kols || [];
      // Mutual members eligible for Outreach Panel: must be in mutual subgraph
      // AND not flagged as an institutional brand account (is_organization).
      // Institutional brands like @biteyecn stay in the Dashboard and Network
      // Graph (they are real nodes in the community), but Outreach targets
      // them via their human operators (e.g. @defiteddy2020 runs Biteye) so
      // showing the brand handle in the action plan would be misleading.
      const mutualMembers = allKols.filter(
        (k) => k.is_mutual_member && !k.is_organization
      );
      const excludedBrands = allKols.filter(
        (k) => k.is_mutual_member && k.is_organization
      );
      const kolById = Object.fromEntries(allKols.map((k) => [k.id, k]));
      const t1Neighbors = buildT1NeighborMap(graphData);

      // Normalization bases
      const maxPr = Math.max(...mutualMembers.map((k) => k.pagerank || 0), 0.0001);
      const maxLogF = Math.max(
        ...mutualMembers.map((k) =>
          Math.log(Math.max(k.followers_count || 1, 1))
        ),
        1
      );

      // Enrich each mutual member
      const enriched = mutualMembers.map((k) => {
        const importance = computeImportance(k, maxPr, maxLogF);
        const neighbors = [...(t1Neighbors.get(k.id) || [])]
          .map((h) => kolById[h])
          .filter(Boolean);
        let unlock = 0;
        for (const n of neighbors) {
          const nImp = computeImportance(n, maxPr, maxLogF);
          const nCoop = n.cooperability_score || 0;
          unlock += nImp * (1 - nCoop / 100);
        }
        return {
          ...k,
          _importance: importance,
          _unlock: unlock,
          _effectiveQuality: effectiveQuality(k),
          _neighborCount: neighbors.length,
        };
      });

      // Percentile thresholds over current mutual set
      const sortedCoop = [...enriched.map((k) => k.cooperability_score || 0)].sort(
        (a, b) => a - b
      );
      const sortedUnlock = [...enriched.map((k) => k._unlock)].sort((a, b) => a - b);
      const sortedImp = [...enriched.map((k) => k._importance)].sort((a, b) => a - b);

      const P40_coop = percentile(sortedCoop, 0.4);
      const P60_coop = percentile(sortedCoop, 0.6);
      const P50_unlock = percentile(sortedUnlock, 0.5);
      const P70_imp = percentile(sortedImp, 0.7);

      // Classify each member — mutually exclusive
      enriched.forEach((k) => {
        const c = k.cooperability_score || 0;
        const u = k._unlock;
        const i = k._importance;
        if (c >= P40_coop && u >= P50_unlock) {
          k._category = "gateway";
        } else if (i >= P70_imp && c < P40_coop) {
          k._category = "strategic";
        } else if (c >= P60_coop) {
          k._category = "quick_win";
        } else {
          k._category = "other";
        }
      });

      const gateway = enriched
        .filter((k) => k._category === "gateway")
        .sort((a, b) => b._unlock - a._unlock);
      const strategic = enriched
        .filter((k) => k._category === "strategic")
        .sort((a, b) => b._importance - a._importance);
      const quickWin = enriched
        .filter((k) => k._category === "quick_win")
        .sort((a, b) => (b.cooperability_score || 0) - (a.cooperability_score || 0));

      // For each strategic target, find which gateways can warm-intro them
      strategic.forEach((s) => {
        const neighborsOfS = t1Neighbors.get(s.id) || new Set();
        s._reachableVia = gateway
          .filter((g) => neighborsOfS.has(g.id))
          .map((g) => g.id);
      });

      // For each gateway, precompute which strategics they can unlock
      gateway.forEach((g) => {
        const neighborsOfG = t1Neighbors.get(g.id) || new Set();
        g._unlocks = strategic
          .filter((s) => neighborsOfG.has(s.id))
          .map((s) => s.id);
      });

      return {
        gateway,
        strategic,
        quickWin,
        excludedBrands,
        thresholds: { P40_coop, P60_coop, P50_unlock, P70_imp },
        totals: {
          mutualMembers: mutualMembers.length,
          gateway: gateway.length,
          strategic: strategic.length,
          quickWin: quickWin.length,
          fallthrough:
            mutualMembers.length - gateway.length - strategic.length - quickWin.length,
          excludedBrands: excludedBrands.length,
        },
        t1Neighbors,
      };
    }, []);

  // Highlighting logic — when a card is clicked, determine which related
  // cards across columns should light up.
  const highlightedSet = useMemo(() => {
    if (!selectedHandle) return new Set();
    const s = new Set([selectedHandle]);
    const neighbors = t1Neighbors.get(selectedHandle) || new Set();
    for (const n of neighbors) s.add(n);
    return s;
  }, [selectedHandle, t1Neighbors]);

  return (
    <div className="h-full overflow-y-auto">
      {/* Header */}
      <div className="border-b border-border px-6 py-4 bg-bg-panel sticky top-0 z-10">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-text-primary">
              🗝️ Outreach Priority Panel
            </h1>
            <div className="text-xs text-text-muted font-mono mt-0.5">
              Referral-chain action planner · {totals.mutualMembers} mutual members ·
              {" "}percentile-ranked on current subgraph
            </div>
          </div>
          <div className="text-[11px] font-mono text-text-muted text-right">
            <div>Gateways: <span className="text-accent-emerald font-semibold">{totals.gateway}</span></div>
            <div>Strategic: <span className="text-accent-rose font-semibold">{totals.strategic}</span></div>
            <div>Quick Wins: <span className="text-accent-blue font-semibold">{totals.quickWin}</span></div>
          </div>
        </div>

        <div className="mt-3 text-[11px] text-text-secondary font-mono leading-relaxed bg-bg-card border border-border rounded p-3">
          <strong className="text-text-primary">The action plan:</strong> Attack
          🗝️ Gateways first. Each Gateway you win → unlocks warm-intro paths to
          🎯 Strategic Targets via T1 mutual follow. Collect ⚡ Quick Wins in
          parallel for testimonials. <strong>Click any card</strong> to highlight
          its T1-connected peers across columns.
        </div>

        {excludedBrands && excludedBrands.length > 0 && (
          <div className="mt-2 text-[10px] text-text-muted font-mono leading-relaxed bg-accent-amber/5 border border-accent-amber/30 rounded p-2">
            🏢 <strong className="text-accent-amber">Excluded from panel (institutional brand):</strong>{" "}
            {excludedBrands.map((b, i) => (
              <span key={b.id}>
                {i > 0 && ", "}
                <Link
                  to={`/profile/${b.id}`}
                  className="text-accent-blue hover:underline"
                >
                  @{b.id}
                </Link>
              </span>
            ))}
            . These are real mutual-subgraph members but not personal outreach
            targets — contact via their human operators instead (see Profile).
          </div>
        )}

        {selectedHandle && (
          <div className="mt-2 flex items-center gap-3">
            <div className="text-[11px] font-mono text-text-muted">
              Highlighting T1 mutual neighbors of{" "}
              <span className="text-accent-blue">@{selectedHandle}</span>
            </div>
            <button
              onClick={() => setSelectedHandle(null)}
              className="text-[10px] text-accent-rose font-mono hover:underline"
            >
              clear
            </button>
          </div>
        )}
      </div>

      {/* Three columns */}
      <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* --- GATEWAY --- */}
        <ColumnHeader
          icon="🗝️"
          title="Gateway KOLs"
          subtitle="Attack first. High unlock value + contactable."
          count={totals.gateway}
          color="emerald"
        >
          {gateway.map((k) => (
            <KolCard
              key={k.id}
              k={k}
              category="gateway"
              selected={selectedHandle === k.id}
              dimmed={selectedHandle && !highlightedSet.has(k.id)}
              onClick={() =>
                setSelectedHandle(selectedHandle === k.id ? null : k.id)
              }
              extraLine={
                k._unlocks && k._unlocks.length > 0
                  ? `→ unlocks ${k._unlocks.length} strategic: ${k._unlocks
                      .map((h) => "@" + h)
                      .join(", ")}`
                  : null
              }
            />
          ))}
        </ColumnHeader>

        {/* --- STRATEGIC --- */}
        <ColumnHeader
          icon="🎯"
          title="Strategic Targets"
          subtitle="High importance, low cooperability. Unlock via Gateway warm intro."
          count={totals.strategic}
          color="rose"
        >
          {strategic.map((k) => (
            <KolCard
              key={k.id}
              k={k}
              category="strategic"
              selected={selectedHandle === k.id}
              dimmed={selectedHandle && !highlightedSet.has(k.id)}
              onClick={() =>
                setSelectedHandle(selectedHandle === k.id ? null : k.id)
              }
              extraLine={
                k._reachableVia && k._reachableVia.length > 0 ? (
                  <>
                    ↖ reachable via{" "}
                    {k._reachableVia.map((h, i) => (
                      <span key={h}>
                        {i > 0 && ", "}
                        <span className="text-accent-emerald">@{h}</span>
                      </span>
                    ))}
                  </>
                ) : (
                  <span className="text-text-muted">
                    No Gateway has T1 mutual yet — cold outreach only
                  </span>
                )
              }
            />
          ))}
        </ColumnHeader>

        {/* --- QUICK WIN --- */}
        <ColumnHeader
          icon="⚡"
          title="Quick Wins"
          subtitle="Easy bookings for case studies. Limited network unlock."
          count={totals.quickWin}
          color="blue"
        >
          {quickWin.map((k) => (
            <KolCard
              key={k.id}
              k={k}
              category="quick_win"
              selected={selectedHandle === k.id}
              dimmed={selectedHandle && !highlightedSet.has(k.id)}
              onClick={() =>
                setSelectedHandle(selectedHandle === k.id ? null : k.id)
              }
              extraLine={null}
            />
          ))}
        </ColumnHeader>
      </div>

      {/* Methodology footer */}
      <div className="px-6 pb-10 max-w-5xl">
        <div className="bg-bg-card border border-border rounded-lg p-5 text-[11px] font-mono text-text-secondary leading-relaxed">
          <div className="text-text-primary font-semibold mb-2">
            How the panel is built
          </div>
          <div className="space-y-2">
            <div>
              <span className="text-accent-emerald">Importance(K)</span> ={" "}
              <code className="bg-bg-hover px-1 rounded">
                0.5 × pagerank_norm + 0.5 × log(followers)_norm
              </code>{" "}
              — structural weight of a KOL in the mutual subgraph.
            </div>
            <div>
              <span className="text-accent-emerald">UnlockValue(G)</span> ={" "}
              <code className="bg-bg-hover px-1 rounded">
                Σ Importance(N) × (1 − coop(N)/100)
              </code>{" "}
              for each T1 mutual neighbor N of G. Measures "how much hard-to-reach
              network does G open up for you."
            </div>
            <div>
              <span className="text-accent-emerald">Gateway</span>: coop ≥ P
              {Math.round(40)} ({thresholds.P40_coop.toFixed(0)}) AND unlock ≥
              P50 ({thresholds.P50_unlock.toFixed(0)}) — good access AND high
              referral potential.
            </div>
            <div>
              <span className="text-accent-rose">Strategic</span>: importance ≥
              P70 ({thresholds.P70_imp.toFixed(0)}) AND coop &lt; P40 (
              {thresholds.P40_coop.toFixed(0)}) — important but hard. Needs a
              warm intro.
            </div>
            <div>
              <span className="text-accent-blue">Quick Win</span>: coop ≥ P60 (
              {thresholds.P60_coop.toFixed(0)}) AND not Gateway — easy booking,
              limited unlock.
            </div>
            <div className="text-text-muted pt-2">
              Thresholds are percentiles over the current{" "}
              {totals.mutualMembers}-member mutual subgraph and auto-recalibrate
              as it grows. {totals.fallthrough} members fall outside all three
              categories (low coop AND low unlock) — they stay in the{" "}
              <Link to="/dashboard" className="text-accent-blue hover:underline">
                full database
              </Link>{" "}
              but not in this action plan.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ------- Helpers -------

function ColumnHeader({ icon, title, subtitle, count, color, children }) {
  const colorMap = {
    emerald: {
      border: "border-accent-emerald/40",
      text: "text-accent-emerald",
      bg: "bg-accent-emerald/5",
    },
    rose: {
      border: "border-accent-rose/40",
      text: "text-accent-rose",
      bg: "bg-accent-rose/5",
    },
    blue: {
      border: "border-accent-blue/40",
      text: "text-accent-blue",
      bg: "bg-accent-blue/5",
    },
  };
  const c = colorMap[color] || colorMap.emerald;
  return (
    <div className={`flex flex-col`}>
      <div className={`rounded-t-lg border ${c.border} ${c.bg} px-4 py-3`}>
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className={`text-sm font-semibold ${c.text}`}>
              {icon} {title}
            </div>
            <div className="text-[10px] text-text-muted font-mono mt-0.5">
              {subtitle}
            </div>
          </div>
          <div className={`text-2xl font-semibold ${c.text} font-mono`}>
            {count}
          </div>
        </div>
      </div>
      <div className={`border-x border-b ${c.border} rounded-b-lg bg-bg-base p-3 space-y-2 min-h-[200px]`}>
        {children}
        {count === 0 && (
          <div className="text-[11px] text-text-muted font-mono py-4 text-center">
            No members in this category yet.
          </div>
        )}
      </div>
    </div>
  );
}

function KolCard({ k, category, selected, dimmed, onClick, extraLine }) {
  const categoryBorder = {
    gateway: "border-accent-emerald/40 hover:border-accent-emerald",
    strategic: "border-accent-rose/40 hover:border-accent-rose",
    quick_win: "border-accent-blue/40 hover:border-accent-blue",
  };
  const coop = k.cooperability_score;
  const effQuality = k._effectiveQuality;
  const unlock = k._unlock;
  const isQualityMissing = k.quality_score == null;

  return (
    <div
      onClick={onClick}
      className={`bg-bg-card border rounded-lg p-3 cursor-pointer transition-all ${
        categoryBorder[category]
      } ${
        selected
          ? "ring-2 ring-accent-amber ring-offset-1 ring-offset-bg-base"
          : ""
      } ${dimmed ? "opacity-35" : ""}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-mono text-accent-blue truncate">
            @{k.id}
          </div>
          <div className="text-[10px] text-text-muted truncate mt-0.5">
            {k.name || "—"}
          </div>
        </div>
        <div className="flex-shrink-0 text-right font-mono text-[10px]">
          {k.tier && (
            <div className="text-text-muted">{k.tier}</div>
          )}
          {k.is_anchor && (
            <div className="text-accent-amber text-[9px]">⚓ anchor</div>
          )}
        </div>
      </div>

      {/* Score bars */}
      <div className="mt-2 space-y-1.5 font-mono text-[10px]">
        <ScoreRow
          label="Unlock"
          value={unlock}
          max={800}
          color="emerald"
          showValue
        />
        <ScoreRow
          label="Coop"
          value={coop || 0}
          max={100}
          color="blue"
          showValue
        />
        <ScoreRow
          label={isQualityMissing ? "Q (fallback)" : "Quality"}
          value={effQuality || 0}
          max={100}
          color={isQualityMissing ? "amber" : "rose"}
          showValue
          dimmed={isQualityMissing}
        />
      </div>

      {/* Network stats row */}
      <div className="mt-2 flex items-center gap-2 text-[9px] font-mono text-text-muted">
        <span>t1={k.t1_mutual_count}</span>
        <span>cross={k.cross_cluster_mutual_count}</span>
        {k.is_bridge && <span className="text-accent-amber">⭐ bridge</span>}
      </div>

      {/* Extra line (unlocks for Gateway, reachable-via for Strategic) */}
      {extraLine && (
        <div className="mt-2 pt-2 border-t border-border text-[10px] font-mono text-text-secondary leading-relaxed">
          {extraLine}
        </div>
      )}

      {/* Profile link */}
      <div className="mt-2 pt-2 border-t border-border flex justify-between items-center">
        <Link
          to={`/profile/${k.id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-[9px] font-mono text-accent-blue hover:underline"
        >
          full profile →
        </Link>
        {k.estimated_price_tier && (
          <span className="text-[9px] text-text-muted font-mono">
            {k.estimated_price_tier}
          </span>
        )}
      </div>
    </div>
  );
}

function ScoreRow({ label, value, max, color, showValue, dimmed }) {
  const pct = Math.min(100, (value / max) * 100);
  const colorMap = {
    emerald: "bg-accent-emerald",
    blue: "bg-accent-blue",
    rose: "bg-accent-rose",
    amber: "bg-accent-amber",
  };
  return (
    <div className="flex items-center gap-2">
      <div
        className={`w-14 ${dimmed ? "text-text-muted" : "text-text-secondary"}`}
      >
        {label}
      </div>
      <div className="flex-1 h-1 bg-bg-hover rounded-full overflow-hidden">
        <div
          className={`h-full ${colorMap[color] || "bg-text-muted"} ${
            dimmed ? "opacity-40" : ""
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showValue && (
        <div
          className={`w-10 text-right ${
            dimmed ? "text-text-muted" : "text-text-primary"
          }`}
        >
          {value > 100 ? value.toFixed(0) : value.toFixed(1)}
        </div>
      )}
    </div>
  );
}
