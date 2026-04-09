import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import graphData from "../data/graph.json";

const EDGE_FUNCTION_URL =
  "https://jsnbkgdivqwfwlqvbotq.supabase.co/functions/v1/build-graph";

export default function Discovery() {
  const [mode, setMode] = useState("explore"); // explore | import
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState([]); // live progress lines
  const [result, setResult] = useState(null);   // null | { graph } | { error }
  const navigate = useNavigate();

  const parseHandles = (text) =>
    [...new Set(
      text.split(/[\n,\s]+/)
        .map((h) => h.trim().replace(/^@/, "").toLowerCase())
        .filter((h) => h && /^[a-z0-9_]{1,15}$/i.test(h))
    )];

  const handleImportRun = async () => {
    const handles = parseHandles(importText);
    if (handles.length < 3) {
      setResult({ error: "too_few" });
      return;
    }

    setResult(null);
    setProgress([]);
    setImporting(true);

    try {
      setProgress(["Connecting to pipeline…"]);

      const res = await fetch(EDGE_FUNCTION_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handles }),
      });

      const data = await res.json();

      if (!res.ok || data.error) {
        setResult({ error: data.error || `HTTP ${res.status}` });
        setProgress((p) => [...p, `✗ Error: ${data.error || res.status}`]);
        return;
      }

      setProgress(data.progress ?? []);
      setResult({ graph: data.graph });
    } catch (err) {
      setResult({ error: String(err) });
      setProgress((p) => [...p, `✗ ${err}`]);
    } finally {
      setImporting(false);
    }
  };

  const stages = [
    {
      id: "A",
      title: "Method A: Following Graph Expansion",
      desc: "Fetch /following for anchors → accumulate candidates followed by ≥3 anchors",
      cost: "~$0.0088/user returned (Model A)",
      runs: "Circle 1 + 2 + 3: 16 anchors → 13,217 follow records",
    },
    {
      id: "B",
      title: "Method B: Keyword Search",
      desc: "/tweets/search/recent on 中英文 keywords (AI Agent, 链上 AI, Virtuals, Bittensor...)",
      cost: "Separate X API credit pool",
      runs: "Status: ready to run (not yet executed)",
    },
    {
      id: "C",
      title: "Method C: Interaction Mining",
      desc: "Extract mentions / replies / quotes from anchors' recent tweets",
      cost: "Free byproduct of /users/{id}/tweets fetches",
      runs: "Status: zero-cost, runs during Phase 2 quality filter",
    },
  ];

  return (
    <div className="h-full overflow-y-auto">
      {/* Header */}
      <div className="border-b border-border px-6 py-4 bg-bg-panel sticky top-0 z-10">
        <h1 className="text-lg font-semibold text-text-primary">KOL Discovery Pipeline</h1>
        <div className="text-xs text-text-muted font-mono mt-0.5">
          From anchors to network: how we grow the graph
        </div>

        {/* Mode toggle */}
        <div className="flex gap-2 mt-4">
          <button
            onClick={() => setMode("explore")}
            className={`px-4 py-2 rounded-md text-sm font-mono transition-colors ${
              mode === "explore"
                ? "bg-bg-hover border border-accent-blue text-text-primary"
                : "bg-bg-card border border-border text-text-muted"
            }`}
          >
            📊 Mode A — Explore preset data
          </button>
          <button
            onClick={() => setMode("import")}
            className={`px-4 py-2 rounded-md text-sm font-mono transition-colors ${
              mode === "import"
                ? "bg-bg-hover border border-accent-emerald text-text-primary"
                : "bg-bg-card border border-border text-text-muted"
            }`}
          >
            ⭐ Mode B — Import Your Own Seeds
          </button>
        </div>
      </div>

      <div className="p-6 max-w-5xl">
        {mode === "explore" && (
          <>
            <div className="mb-6">
              <h2 className="text-sm font-semibold text-text-primary mb-2">
                Pipeline stages (executed)
              </h2>
              <div className="space-y-3">
                {stages.map((s) => (
                  <div key={s.id} className="bg-bg-card border border-border rounded-lg p-4">
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-accent-blue/20 border border-accent-blue flex items-center justify-center text-accent-blue font-mono font-semibold flex-shrink-0">
                        {s.id}
                      </div>
                      <div className="flex-1">
                        <div className="text-sm font-semibold text-text-primary">{s.title}</div>
                        <div className="text-xs text-text-secondary mt-1">{s.desc}</div>
                        <div className="flex gap-4 mt-2 text-[11px] font-mono text-text-muted">
                          <div>cost: {s.cost}</div>
                          <div>{s.runs}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-bg-card border border-border rounded-lg p-4">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Current graph output</h3>
              <div className="grid grid-cols-3 gap-3 text-xs font-mono">
                <StatBlock label="Mutual members" value={graphData.metadata.mutual_members || 16} sub="✅ T1 mutual confirmed (the real network)" />
                <StatBlock label="Watched" value={(graphData.metadata.watched_nodes || 0).toLocaleString()} sub="◯ followed by anchors, mutual not verified" />
                <StatBlock label="Celebrity-filtered" value={graphData.metadata.celebrity_filtered || 0} sub="✕ ≥5× median anchor followers" />
                <StatBlock label="T1 mutual edges" value={graphData.metadata.edge_breakdown.tier_1_mutual} sub="Ground truth between anchors" />
                <StatBlock label="Real clusters" value={graphData.metadata.connected_clusters || graphData.metadata.clusters_found} sub="Louvain on mutual subgraph only" />
                <StatBlock label="API cost" value={`$${graphData.metadata.input_data.cost_usd_total}`} sub={`${graphData.metadata.input_data.total_raw_following_records_analyzed.toLocaleString()} follow records analyzed`} />
              </div>
            </div>
          </>
        )}

        {mode === "import" && (
          <div className="space-y-6">
            <div className="bg-accent-emerald/5 border border-accent-emerald/30 rounded-lg p-5">
              <h2 className="text-sm font-semibold text-accent-emerald mb-2">
                ⭐ Import Your Own Seeds
              </h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                Paste your own KOL handles (3–20 people you know). The pipeline will: (1) check
                our Supabase cache for existing follow data (free), (2) fetch any missing seeds
                from X API and cache the results, (3) compute mutual-follow matrix, (4) build
                your custom network graph with the same three-tier edge methodology.
              </p>
              <p className="text-[11px] text-text-muted mt-3 font-mono">
                Cached seeds return instantly at $0. Uncached seeds are fetched live from X API.
              </p>
            </div>

            <div>
              <label className="block text-xs font-mono text-text-muted mb-2 uppercase tracking-widest">
                Your seed handles (one per line or comma-separated)
              </label>
              <textarea
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder={"@handle1\n@handle2\n@handle3"}
                rows={8}
                className="w-full bg-bg-card border border-border rounded-md px-3 py-2 font-mono text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-emerald"
              />
              <div className="mt-3 flex justify-between items-center">
                <div className="text-[11px] text-text-muted font-mono">
                  {parseHandles(importText).length} valid handles
                </div>
                <button
                  onClick={handleImportRun}
                  disabled={importing || importText.trim().length === 0}
                  className="px-5 py-2 bg-accent-emerald/15 border border-accent-emerald rounded-md text-sm font-mono text-accent-emerald hover:bg-accent-emerald/25 disabled:opacity-50 transition-colors"
                >
                  {importing ? "Running pipeline…" : "Build my network graph"}
                </button>
              </div>
            </div>

            {/* Validation error */}
            {result?.error === "too_few" && (
              <div className="bg-accent-rose/5 border border-accent-rose/40 rounded-lg p-4 text-xs font-mono text-accent-rose">
                Need at least 3 valid handles.
              </div>
            )}

            {/* Live progress */}
            {(importing || progress.length > 0) && result?.error !== "too_few" && (
              <div className="bg-bg-card border border-accent-emerald/40 rounded-lg p-5 space-y-2">
                <div className="text-xs font-mono text-accent-emerald uppercase tracking-widest mb-3">
                  ▶ Pipeline {importing ? "running…" : "complete"}
                </div>
                {progress.map((line, i) => (
                  <div key={i} className="text-[11px] font-mono text-text-secondary flex items-start gap-2">
                    <span className={line.startsWith("✗") ? "text-accent-rose" : "text-accent-blue"}>●</span>
                    {line}
                  </div>
                ))}
                {importing && (
                  <div className="text-[11px] font-mono text-text-muted animate-pulse flex items-center gap-2">
                    <span className="text-accent-emerald">●</span> Processing…
                  </div>
                )}
              </div>
            )}

            {/* API error */}
            {result?.error && result.error !== "too_few" && (
              <div className="bg-accent-rose/5 border border-accent-rose/40 rounded-lg p-4 text-xs font-mono text-accent-rose">
                ✗ Error: {result.error}
              </div>
            )}

            {/* Success */}
            {result?.graph && !importing && (
              <div className="bg-accent-emerald/5 border border-accent-emerald/40 rounded-lg p-5">
                <div className="flex items-start gap-3">
                  <div className="text-accent-emerald text-xl">✓</div>
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-accent-emerald mb-3">
                      Graph built — {result.graph.metadata.total_nodes} nodes · {result.graph.metadata.total_edges} edges
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[11px] font-mono mb-4">
                      <div className="bg-bg-panel rounded p-2">
                        <div className="text-text-muted">Mutual (T1)</div>
                        <div className="text-accent-emerald font-semibold text-lg">{result.graph.metadata.edge_breakdown.tier_1_mutual}</div>
                      </div>
                      <div className="bg-bg-panel rounded p-2">
                        <div className="text-text-muted">Hubs found</div>
                        <div className="text-accent-blue font-semibold text-lg">{result.graph.metadata.watched_nodes}</div>
                      </div>
                      <div className="bg-bg-panel rounded p-2">
                        <div className="text-text-muted">API cost</div>
                        <div className="text-text-secondary font-semibold text-lg">${result.graph.metadata.input_data.cost_usd_total}</div>
                      </div>
                    </div>
                    <button
                      onClick={() => navigate("/graph", { state: { customGraph: result.graph } })}
                      className="w-full py-2 bg-accent-emerald/20 border border-accent-emerald rounded-md text-sm font-mono text-accent-emerald hover:bg-accent-emerald/30 transition-colors"
                    >
                      View in Network Graph →
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Cost reference */}
            <div className="bg-bg-card border border-border rounded-lg p-4">
              <h3 className="text-xs font-mono text-text-muted uppercase tracking-widest mb-3">
                Estimated runtime for 10 seeds
              </h3>
              <ol className="space-y-2 text-xs text-text-secondary font-mono">
                <li><span className="text-accent-blue">1.</span> Resolve 10 handle IDs — 5s, ~$0.10</li>
                <li><span className="text-accent-blue">2.</span> Fetch /following (10 seeds × avg 300 followings) — 30s, ~$26</li>
                <li><span className="text-accent-blue">3.</span> Compute mutual matrix (45 pairs) — 1s, free</li>
                <li><span className="text-accent-blue">4.</span> Hub expansion analysis — 2s, free</li>
                <li><span className="text-accent-blue">5.</span> Graph construction + clustering — 3s, free</li>
              </ol>
              <div className="mt-3 pt-3 border-t border-border text-[11px] text-text-muted">
                Seeds already in our database return instantly at $0 — no X API call needed.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatBlock({ label, value, sub }) {
  return (
    <div className="bg-bg-panel border border-border rounded-md p-3">
      <div className="text-[10px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className="text-2xl font-semibold text-text-primary mt-0.5">{value}</div>
      <div className="text-[10px] text-text-muted mt-1">{sub}</div>
    </div>
  );
}
