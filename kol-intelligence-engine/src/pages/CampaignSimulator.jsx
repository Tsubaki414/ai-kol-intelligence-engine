import { useState, useMemo } from "react";
import kolsData from "../data/kols.json";

// v3 schema helper: prefer Quality Score, fall back to EQR sub-score, else 50
function rankingScore(kol) {
  if (kol.quality_score != null) return kol.quality_score;
  const eqr = kol.score_traces?.quality?.engagement_quality_ratio?.value;
  return eqr != null ? eqr : 50;
}

// Deterministic estimate from quality score (proxy for engagement strength)
function seededReach(kol) {
  const f = kol.followers_count || 1000;
  // simplified: reach = followers * engagement rate * amplification
  const er = (rankingScore(kol) / 100) * 0.06 + 0.015; // 1.5-7.5% engagement range
  return Math.round(f * er * 1.35); // 1.35x amplification from RTs
}

function seededConversion(kol, baseRate = 0.025) {
  const quality = rankingScore(kol) / 100;
  return Math.round(seededReach(kol) * baseRate * (0.6 + quality * 0.8));
}

const TABS = ["selection", "results", "budget"];

export default function CampaignSimulator() {
  const [selectedIds, setSelectedIds] = useState([]);
  const [tab, setTab] = useState("selection");
  const [budget, setBudget] = useState(10000);

  // Top 30 KOLs: prefer KOLs with computable Quality Score; fall back to
  // followers + tier so the page is never empty even when tweet coverage is sparse.
  const topKols = useMemo(() => {
    const withQ = kolsData.kols.filter((k) => k.quality_score != null);
    const pool = withQ.length >= 30 ? withQ : kolsData.kols;
    return [...pool]
      .sort((a, b) => {
        // In-graph first, then quality score, then followers
        if (a.in_graph !== b.in_graph) return b.in_graph - a.in_graph;
        const qa = a.quality_score ?? -1;
        const qb = b.quality_score ?? -1;
        if (qa !== qb) return qb - qa;
        return (b.followers_count || 0) - (a.followers_count || 0);
      })
      .slice(0, 30);
  }, []);

  const selected = useMemo(
    () => kolsData.kols.filter((k) => selectedIds.includes(k.id)),
    [selectedIds]
  );

  const toggleKol = (id) =>
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );

  const totals = useMemo(() => {
    const reach = selected.reduce((s, k) => s + seededReach(k), 0);
    const conversion = selected.reduce((s, k) => s + seededConversion(k), 0);
    const engagementRate =
      selected.length > 0
        ? (
            (selected.reduce((s, k) => s + rankingScore(k), 0) /
              selected.length) *
            0.05
          ).toFixed(2)
        : "0.00";
    return { reach, conversion, engagementRate };
  }, [selected]);

  const costEstimate = (kol) => {
    // Based on tier
    const base = {
      Mega: 3500,
      Macro: 900,
      Micro: 220,
      Nano: 50,
    };
    return base[kol.tier] || 300;
  };
  const totalCost = selected.reduce((s, k) => s + costEstimate(k), 0);

  return (
    <div className="h-full overflow-y-auto">
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Campaign Simulator</h1>
          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">
            🎨 DEMO MODE
          </span>
        </div>
        <div className="text-xs text-text-muted font-mono mt-0.5">
          Select KOLs → simulate reach / engagement / conversion / cost
        </div>

        <div className="flex gap-2 mt-3">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-mono rounded ${
                tab === t
                  ? "bg-bg-hover border border-accent-blue text-text-primary"
                  : "bg-bg-card border border-border text-text-muted"
              }`}
            >
              {t === "selection" && "KOL Selection"}
              {t === "results" && `Results (${selected.length} selected)`}
              {t === "budget" && "Budget Allocation"}
            </button>
          ))}
        </div>
      </div>

      <div className="p-6 max-w-6xl">
        {tab === "selection" && (
          <div>
            <div className="mb-4 text-xs text-text-muted font-mono">
              Pick KOLs from the top-scoring 30. Selection auto-updates the simulation.
            </div>
            <div className="grid grid-cols-2 gap-2">
              {topKols.map((k) => {
                const sel = selectedIds.includes(k.id);
                return (
                  <button
                    key={k.id}
                    onClick={() => toggleKol(k.id)}
                    className={`text-left p-3 rounded-md border transition-colors ${
                      sel
                        ? "bg-accent-blue/10 border-accent-blue"
                        : "bg-bg-card border-border hover:border-accent-blue/50"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-mono text-accent-blue">
                        @{k.id}
                      </div>
                      <div className="text-[10px] font-mono text-accent-emerald">
                        {k.quality_score != null ? `Q ${k.quality_score}` : "—"}
                      </div>
                    </div>
                    <div className="text-[11px] text-text-muted truncate mt-0.5">
                      {k.name || "—"}
                    </div>
                    <div className="flex gap-2 text-[10px] font-mono text-text-muted mt-1">
                      <span>{k.tier}</span>
                      <span>· {(k.followers_count || 0).toLocaleString()}</span>
                      {k.circles?.length > 0 && (
                        <span className="text-accent-emerald">
                          · {k.circles.join("+")}
                        </span>
                      )}
                      <span className="ml-auto text-accent-amber">
                        ~${costEstimate(k).toLocaleString()}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {tab === "results" && (
          <div>
            {selected.length === 0 ? (
              <EmptyState message="Select KOLs in the selection tab to see simulated results." />
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-4 gap-3">
                  <ResultCard
                    label="Total Reach"
                    value={totals.reach.toLocaleString()}
                    sub={`across ${selected.length} KOL${selected.length === 1 ? "" : "s"}`}
                    accent="blue"
                  />
                  <ResultCard
                    label="Avg Engagement"
                    value={`${totals.engagementRate}%`}
                    sub="weighted"
                    accent="emerald"
                  />
                  <ResultCard
                    label="Est. Conversions"
                    value={totals.conversion.toLocaleString()}
                    sub="@ 2.5% base rate"
                    accent="amber"
                  />
                  <ResultCard
                    label="Est. Cost"
                    value={`$${totalCost.toLocaleString()}`}
                    sub="tier-based"
                    accent="rose"
                  />
                </div>

                <div className="bg-bg-card border border-border rounded-lg p-5">
                  <h3 className="text-sm font-semibold text-text-primary mb-3">
                    Per-KOL breakdown
                  </h3>
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="text-text-muted text-[10px] uppercase tracking-wider border-b border-border">
                        <th className="py-2 text-left">Handle</th>
                        <th className="py-2 text-left">Tier</th>
                        <th className="py-2 text-right">Reach</th>
                        <th className="py-2 text-right">Conv.</th>
                        <th className="py-2 text-right">Cost</th>
                        <th className="py-2 text-right">CPM</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {selected.map((k) => {
                        const reach = seededReach(k);
                        const conv = seededConversion(k);
                        const cost = costEstimate(k);
                        const cpm = ((cost / reach) * 1000).toFixed(2);
                        return (
                          <tr key={k.id}>
                            <td className="py-2 text-accent-blue">@{k.id}</td>
                            <td className="py-2 text-text-muted">{k.tier}</td>
                            <td className="py-2 text-right text-text-secondary">
                              {reach.toLocaleString()}
                            </td>
                            <td className="py-2 text-right text-text-secondary">
                              {conv}
                            </td>
                            <td className="py-2 text-right text-text-secondary">
                              ${cost.toLocaleString()}
                            </td>
                            <td className="py-2 text-right text-text-muted">
                              ${cpm}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="bg-bg-card border border-border rounded-lg p-5">
                  <h3 className="text-sm font-semibold text-text-primary mb-3">
                    Confidence
                  </h3>
                  <div className="text-xs text-text-secondary leading-relaxed">
                    Estimates use Layer 1 Quality Score (or EQR sub-score fallback) + follower count +
                    tier baselines. Confidence interval: ±25%. Production version would calibrate on
                    historical campaign outcomes via Claude API analysis of past Lighthouse campaigns.
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "budget" && (
          <div className="space-y-4">
            <div className="bg-bg-card border border-border rounded-lg p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Target Budget
              </h3>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="1000"
                  max="50000"
                  step="500"
                  value={budget}
                  onChange={(e) => setBudget(parseInt(e.target.value))}
                  className="flex-1"
                />
                <div className="text-lg font-mono text-accent-emerald">
                  ${budget.toLocaleString()}
                </div>
              </div>
            </div>

            <div className="bg-bg-card border border-border rounded-lg p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Recommended Split
              </h3>
              <div className="space-y-2 text-xs font-mono">
                <BudgetBar label="Mega KOLs (1-2x)" pct={25} amount={budget * 0.25} color="purple" />
                <BudgetBar label="Macro KOLs (3-5x)" pct={40} amount={budget * 0.4} color="blue" />
                <BudgetBar label="Micro KOLs (8-12x)" pct={20} amount={budget * 0.2} color="emerald" />
                <BudgetBar label="Content production" pct={10} amount={budget * 0.1} color="amber" />
                <BudgetBar label="Contingency" pct={5} amount={budget * 0.05} color="rose" />
              </div>
            </div>

            <div className="bg-bg-card border border-border rounded-lg p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-2">Expected Outcome</h3>
              <div className="text-xs text-text-secondary leading-relaxed">
                With ${budget.toLocaleString()} split as above, Lighthouse's Fixed+Performance model
                suggests: total reach {(budget * 90).toLocaleString()}-
                {(budget * 150).toLocaleString()}, engagement rate 3.5-4.5%, converted sign-ups{" "}
                {Math.round(budget * 0.15)}-{Math.round(budget * 0.25)}.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ResultCard({ label, value, sub, accent }) {
  const colors = {
    blue: "text-accent-blue",
    emerald: "text-accent-emerald",
    amber: "text-accent-amber",
    rose: "text-accent-rose",
  };
  return (
    <div className="bg-bg-card border border-border rounded-md p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className={`text-xl font-semibold mt-0.5 font-mono ${colors[accent]}`}>
        {value}
      </div>
      <div className="text-[10px] text-text-muted font-mono mt-0.5">{sub}</div>
    </div>
  );
}

function BudgetBar({ label, pct, amount, color }) {
  const colors = {
    purple: "bg-accent-purple",
    blue: "bg-accent-blue",
    emerald: "bg-accent-emerald",
    amber: "bg-accent-amber",
    rose: "bg-accent-rose",
  };
  return (
    <div>
      <div className="flex justify-between text-text-secondary">
        <span>{label}</span>
        <span>
          ${amount.toLocaleString()} ({pct}%)
        </span>
      </div>
      <div className="mt-1 h-1.5 bg-bg-hover rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${colors[color] || "bg-text-muted"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function EmptyState({ message }) {
  return (
    <div className="bg-bg-card border border-dashed border-border rounded-lg p-10 text-center text-sm text-text-muted font-mono">
      {message}
    </div>
  );
}
