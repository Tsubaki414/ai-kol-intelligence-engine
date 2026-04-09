import { useState } from "react";
import graphData from "../data/graph.json";

export default function Discovery() {
  const [mode, setMode] = useState("explore"); // explore | import
  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null); // null | "success" | "error"
  const [parsedHandles, setParsedHandles] = useState([]);

  const handleImportRun = () => {
    setImportResult(null);
    const handles = importText
      .split(/[\n,\s]+/)
      .map((h) => h.trim().replace(/^@/, "").toLowerCase())
      .filter((h) => h && /^[a-z0-9_]{1,15}$/i.test(h));
    if (handles.length < 3) {
      setImportResult("too_few");
      return;
    }
    setParsedHandles(handles);
    setImporting(true);
    setTimeout(() => {
      setImporting(false);
      setImportResult("success");
    }, 1800);
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
                  <div
                    key={s.id}
                    className="bg-bg-card border border-border rounded-lg p-4"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-8 h-8 rounded-full bg-accent-blue/20 border border-accent-blue flex items-center justify-center text-accent-blue font-mono font-semibold flex-shrink-0">
                        {s.id}
                      </div>
                      <div className="flex-1">
                        <div className="text-sm font-semibold text-text-primary">
                          {s.title}
                        </div>
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
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Current graph output
              </h3>
              <div className="grid grid-cols-3 gap-3 text-xs font-mono">
                <StatBlock
                  label="Mutual members"
                  value={graphData.metadata.mutual_members || 16}
                  sub="✅ T1 mutual confirmed (the real network)"
                />
                <StatBlock
                  label="Watched"
                  value={(graphData.metadata.watched_nodes || 0).toLocaleString()}
                  sub="◯ followed by anchors, mutual not verified"
                />
                <StatBlock
                  label="Celebrity-filtered"
                  value={graphData.metadata.celebrity_filtered || 0}
                  sub="✕ ≥5× median anchor followers (Jack Ma effect)"
                />
                <StatBlock
                  label="T1 mutual edges"
                  value={graphData.metadata.edge_breakdown.tier_1_mutual}
                  sub="Ground truth between anchors"
                />
                <StatBlock
                  label="Real clusters"
                  value={graphData.metadata.connected_clusters || graphData.metadata.clusters_found}
                  sub="Louvain on mutual subgraph only"
                />
                <StatBlock
                  label="API cost"
                  value={`$${graphData.metadata.input_data.cost_usd_total}`}
                  sub={`${graphData.metadata.input_data.total_raw_following_records_analyzed.toLocaleString()} follow records analyzed`}
                />
              </div>
              <div className="mt-4 text-[11px] text-text-muted leading-relaxed">
                <strong className="text-text-secondary">Honest framing:</strong> only the{" "}
                {graphData.metadata.mutual_members || 16} anchors are confirmed network members
                via mutual follow (T1 ground truth). The {(graphData.metadata.watched_nodes || 0).toLocaleString()}{" "}
                watched accounts are followed BY anchors but we have not verified they
                follow back — they are outreach targets, not network members. PageRank
                and clustering are computed on the mutual subgraph only.
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
                Paste your own KOL handles (3-20 people you know). The pipeline will: (1) fetch their
                /following lists, (2) compute mutual follow matrix, (3) find accounts commonly followed
                by your seeds, (4) build your custom network graph with the same three-tier edge
                methodology. Works on any sector, any region, any time.
              </p>
              <p className="text-[11px] text-text-muted mt-3 font-mono">
                This is NOT a static dashboard. It is a reusable intelligence engine.
              </p>
            </div>

            <div>
              <label className="block text-xs font-mono text-text-muted mb-2 uppercase tracking-widest">
                Your seed handles (one per line)
              </label>
              <textarea
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder={"@handle1\n@handle2\n@handle3\n@handle4\n@handle5"}
                rows={8}
                className="w-full bg-bg-card border border-border rounded-md px-3 py-2 font-mono text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-emerald"
              />
              <div className="mt-3 flex justify-between items-center">
                <div className="text-[11px] text-text-muted font-mono">
                  {importText.split("\n").filter((l) => l.trim()).length} handles
                </div>
                <button
                  onClick={handleImportRun}
                  disabled={importing || importText.trim().length === 0}
                  className="px-5 py-2 bg-accent-emerald/15 border border-accent-emerald rounded-md text-sm font-mono text-accent-emerald hover:bg-accent-emerald/25 disabled:opacity-50 transition-colors"
                >
                  {importing ? "Running pipeline..." : "Build my network graph"}
                </button>
              </div>
            </div>

            {/* Import result panel — inline, not browser alert */}
            {importResult === "too_few" && (
              <div className="bg-accent-rose/5 border border-accent-rose/40 rounded-lg p-4 text-xs font-mono text-accent-rose">
                Need at least 3 valid handles. Handles must match X username rules (letters, digits, underscore, max 15 chars).
              </div>
            )}

            {importing && (
              <div className="bg-bg-card border border-accent-emerald/40 rounded-lg p-5 space-y-2">
                <div className="text-xs font-mono text-accent-emerald uppercase tracking-widest mb-3">
                  ▶ Pipeline running…
                </div>
                {[
                  "Validating handles against X API username format",
                  "Resolving handles → user IDs",
                  "Fetching /following for each seed",
                  "Computing mutual-follow matrix",
                  "Running hub expansion analysis",
                ].map((step, i) => (
                  <div
                    key={i}
                    className="text-[11px] font-mono text-text-secondary flex items-center gap-2 animate-pulse"
                    style={{ animationDelay: `${i * 150}ms` }}
                  >
                    <span className="text-accent-blue">●</span>
                    {step}
                  </div>
                ))}
              </div>
            )}

            {importResult === "success" && !importing && (
              <div className="bg-accent-emerald/5 border border-accent-emerald/40 rounded-lg p-5">
                <div className="flex items-start gap-3">
                  <div className="text-accent-emerald text-xl">✓</div>
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-accent-emerald mb-2">
                      Demo simulation complete — {parsedHandles.length} handles parsed
                    </div>
                    <div className="text-[11px] text-text-secondary leading-relaxed mb-3">
                      <strong>Demo mode limitation:</strong> actually running /following calls from the browser
                      would expose X API credentials and cost real money per query. In production, this would
                      hit a local Python backend. To run the full pipeline on your seeds, clone the repo and:
                    </div>
                    <div className="bg-bg-panel border border-border rounded p-3 font-mono text-[11px] text-text-primary whitespace-pre">
{`# 1. Clone the repo and set credentials
cp .env.example .env   # fill X_BEARER_TOKEN + ANTHROPIC_API_KEY

# 2. Run the pipeline on your seeds
python pipeline/run_custom_seeds.py \\
  --handles ${parsedHandles.slice(0, 8).join(",")}

# 3. Refresh the web app → Network Graph shows your custom graph
# (restore original: git checkout kol-intelligence-engine/src/data/graph.json)`}
                    </div>
                    <div className="mt-3 text-[11px] text-text-muted">
                      Estimated runtime: {parsedHandles.length * 3}s · cost: ~$
                      {(parsedHandles.length * 8.8).toFixed(2)} (Model A: $0.0088/user returned)
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div className="bg-bg-card border border-border rounded-lg p-4">
              <h3 className="text-xs font-mono text-text-muted uppercase tracking-widest mb-3">
                Estimated runtime for 10 seeds
              </h3>
              <ol className="space-y-2 text-xs text-text-secondary font-mono">
                <li>
                  <span className="text-accent-blue">1.</span> Resolve 10 handle IDs — 5s, ~$0.10
                </li>
                <li>
                  <span className="text-accent-blue">2.</span> Fetch /following (10 × up to 1000) — 30s, ~$80
                </li>
                <li>
                  <span className="text-accent-blue">3.</span> Compute mutual matrix (45 pairs) — 1s, free
                </li>
                <li>
                  <span className="text-accent-blue">4.</span> Hub expansion analysis — 2s, free
                </li>
                <li>
                  <span className="text-accent-blue">5.</span> Graph construction + clustering — 3s, free
                </li>
                <li>
                  <span className="text-accent-blue">6.</span> Render graph — 1s, free
                </li>
              </ol>
              <div className="mt-3 pt-3 border-t border-border text-[11px] text-text-muted">
                Demo mode: pipeline execution requires running{" "}
                <code className="font-mono bg-bg-hover px-1 rounded">python pipeline/server.py</code>{" "}
                locally alongside the demo.
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
