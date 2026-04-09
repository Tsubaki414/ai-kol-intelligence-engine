import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import graphData from "../data/graph.json";

// Cluster color palette (one per Louvain cluster)
const CLUSTER_COLORS = [
  "#3B82F6", // blue
  "#10B981", // emerald
  "#F59E0B", // amber
  "#A855F7", // purple
  "#F43F5E", // rose
  "#06B6D4", // cyan
  "#EAB308", // yellow
  "#EC4899", // pink
];

// Tier edge styling
const TIER_STYLE = {
  1: { color: "rgba(16, 185, 129, 0.95)", width: 2.5, dash: null, label: "Confirmed mutual" },
  2: { color: "rgba(59, 130, 246, 0.55)", width: 1.3, dash: [6, 4], label: "One-way follow" },
  3: { color: "rgba(100, 116, 139, 0.22)", width: 0.6, dash: [2, 3], label: "Inferred co-follow" },
};

export default function NetworkGraphPage() {
  const fgRef = useRef(null);
  const containerRef = useRef(null);
  const [hoveredNode, setHoveredNode] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [visibleTiers, setVisibleTiers] = useState({ 1: true, 2: true, 3: false });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [searchQuery, setSearchQuery] = useState("");
  const [sectorFilter, setSectorFilter] = useState([]);
  const [languageFilter, setLanguageFilter] = useState([]);
  const [tierFilter, setTierFilter] = useState([]);
  const [showFiltersPanel, setShowFiltersPanel] = useState(false);
  const [showIsolated, setShowIsolated] = useState(false); // hide isolated nodes by default
  const [showWatched, setShowWatched] = useState(true); // show watched (non-mutual) nodes by default
  const [showCelebrities, setShowCelebrities] = useState(false); // hide celebrity-flagged by default
  const [searchError, setSearchError] = useState("");

  // Responsive sizing via ResizeObserver (works when parent flex resizes)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);

  // Tune physics for large graph (713 nodes)
  useEffect(() => {
    if (!fgRef.current) return;
    const fg = fgRef.current;
    // Stronger repulsion so clusters don't collapse into a hairball
    fg.d3Force("charge")?.strength(-80).distanceMax(300);
    // Shorter links
    fg.d3Force("link")?.distance((link) => {
      if (link.tier === 1) return 30;
      if (link.tier === 2) return 60;
      return 90;
    });
  }, [size]);

  // Derive filter options from node data (only populated if classified)
  const availableSectors = useMemo(
    () =>
      [
        ...new Set(
          graphData.nodes.map((n) => n.sector).filter(Boolean)
        ),
      ].sort(),
    []
  );
  const availableLanguages = useMemo(
    () =>
      [
        ...new Set(
          graphData.nodes.map((n) => n.language).filter(Boolean)
        ),
      ].sort(),
    []
  );
  const availableTiers = useMemo(
    () =>
      ["Mega", "Macro", "Micro", "Nano"].filter((t) =>
        graphData.nodes.some((n) => n.tier === t)
      ),
    []
  );

  // Node matches filters?
  const matchesFilters = useCallback(
    (node) => {
      // CRITICAL: only show mutual_members + watched (non-celebrity) by default
      // Celebrities (>5x median anchor followers) hidden unless user toggles on
      if (node.is_celebrity_outbound && !showCelebrities) return false;
      if (!node.is_mutual_member && !showWatched) return false;
      if (sectorFilter.length > 0 && !sectorFilter.includes(node.sector)) return false;
      if (languageFilter.length > 0 && !languageFilter.includes(node.language)) return false;
      if (tierFilter.length > 0 && !tierFilter.includes(node.tier)) return false;
      return true;
    },
    [showCelebrities, showWatched, sectorFilter, languageFilter, tierFilter]
  );

  // Pre-compute which nodes have at least one visible edge (for "hide isolated" toggle)
  const connectedNodeIds = useMemo(() => {
    const ids = new Set();
    for (const e of graphData.edges) {
      if (visibleTiers[e.tier]) {
        ids.add(e.source);
        ids.add(e.target);
      }
    }
    return ids;
  }, [visibleTiers]);

  // Build filtered graph
  const filteredData = useMemo(() => {
    const passingNodeIds = new Set(
      graphData.nodes
        .filter(matchesFilters)
        .filter((n) => showIsolated || connectedNodeIds.has(n.id))
        .map((n) => n.id)
    );
    const nodes = graphData.nodes
      .filter((n) => passingNodeIds.has(n.id))
      .map((n) => ({ ...n }));
    const links = graphData.edges
      .filter((e) => visibleTiers[e.tier])
      .filter((e) => passingNodeIds.has(e.source) && passingNodeIds.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        tier: e.tier,
        type: e.type,
        kind: e.kind,
        shared_count: e.shared_count,
      }));
    return { nodes, links };
  }, [visibleTiers, matchesFilters, showIsolated, connectedNodeIds]);

  // Cluster summary
  const clusterSummary = graphData.metadata.cluster_summary || [];

  const handleNodeClick = (node) => {
    setSelectedNode(node);
    // Center camera on node
    fgRef.current?.centerAt(node.x, node.y, 800);
    fgRef.current?.zoom(3, 800);
  };

  // Search-to-focus: find node by handle and zoom to it
  const handleSearch = (e) => {
    e.preventDefault();
    setSearchError("");
    const q = searchQuery.trim().toLowerCase().replace(/^@/, "");
    if (!q) return;
    // Try exact match first, then substring (across full graph, not just filtered)
    const allNodes = graphData.nodes;
    const exact = allNodes.find((n) => n.id === q);
    const node = exact || allNodes.find((n) => n.id.includes(q));
    if (!node) {
      setSearchError(`No KOL matching "${searchQuery}" in the graph`);
      return;
    }
    // If node is filtered out, surface a hint
    const visible = filteredData.nodes.find((n) => n.id === node.id);
    if (!visible) {
      setSearchError(
        `@${node.id} exists but is hidden by current filters. Reset filters or enable peripherals.`
      );
      setSelectedNode(node);
      return;
    }
    if (visible.x != null && visible.y != null) {
      fgRef.current?.centerAt(visible.x, visible.y, 800);
      fgRef.current?.zoom(4, 800);
    }
    setSelectedNode(visible);
  };

  // Clear selection if it gets filtered out
  useEffect(() => {
    if (selectedNode && !filteredData.nodes.find((n) => n.id === selectedNode.id)) {
      setSelectedNode(null);
    }
  }, [filteredData, selectedNode]);

  const toggleArray = (arr, setter, val) =>
    setter(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);

  const resetFilters = () => {
    setSectorFilter([]);
    setLanguageFilter([]);
    setTierFilter([]);
    setSearchQuery("");
  };

  const meta = graphData.metadata;
  const totalT2 =
    (meta.edge_breakdown.tier_2a_oneway_anchor || 0) +
    (meta.edge_breakdown.tier_2b_anchor_to_hub || 0) +
    (meta.edge_breakdown.tier_2c_anchor_to_peripheral || 0);
  const totalT3 =
    (meta.edge_breakdown.tier_3_cofollow_inferred || 0) +
    (meta.edge_breakdown.tier_3b_peripheral_cofollow || 0);

  return (
    <div className="flex h-full w-full min-w-0 overflow-hidden">
      {/* Main graph area */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="border-b border-border px-6 py-3 bg-bg-panel flex-shrink-0">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-text-primary">
                Chinese AI+Crypto KOL Network Graph
              </h1>
              <div className="text-[11px] text-text-muted mt-0.5 font-mono truncate">
                <span className="text-accent-emerald">{meta.mutual_members || 16} mutual members</span>
                {" + "}
                <span className="text-text-secondary">{meta.watched_nodes || 0} watched</span>
                {" + "}
                <span className="text-accent-rose">{meta.celebrity_filtered || 0} celebrity-filtered</span>
                {" · "}{filteredData.nodes.length} visible · {filteredData.links.length} edges
                {" · "}{meta.edge_breakdown.tier_1_mutual} T1 / {totalT2} T2 / {totalT3} T3
                {" · "}{meta.connected_clusters || meta.clusters_found} clusters
                {" · "}${meta.input_data.cost_usd_total}
              </div>
            </div>
            <div className="flex gap-2 items-center">
              {/* Search bar */}
              <form onSubmit={handleSearch} className="flex flex-col items-end">
                <div className="flex items-center">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      if (searchError) setSearchError("");
                    }}
                    placeholder="search @handle..."
                    className="bg-bg-card border border-border rounded-l-md px-3 py-1.5 w-48 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-blue font-mono"
                  />
                  <button
                    type="submit"
                    className="px-3 py-1.5 bg-bg-hover border border-l-0 border-border rounded-r-md text-xs text-text-muted hover:text-text-primary font-mono"
                  >
                    ⌕
                  </button>
                </div>
                {searchError && (
                  <div className="text-[10px] text-accent-rose font-mono mt-1 max-w-[280px] text-right">
                    {searchError}
                  </div>
                )}
              </form>
              <button
                onClick={() => setShowFiltersPanel(!showFiltersPanel)}
                className={`px-3 py-1.5 rounded text-xs font-mono border ${
                  showFiltersPanel || sectorFilter.length + languageFilter.length + tierFilter.length > 0
                    ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
                    : "bg-bg-card border-border text-text-muted"
                }`}
              >
                filters
                {sectorFilter.length + languageFilter.length + tierFilter.length > 0 && (
                  <span className="ml-1">
                    ({sectorFilter.length + languageFilter.length + tierFilter.length})
                  </span>
                )}
              </button>
            </div>
          </div>

          {/* Tier edge toggles + node type + show-isolated */}
          <div className="flex gap-2 font-mono text-xs mt-2 items-center flex-wrap">
            <span className="text-[10px] text-text-muted uppercase tracking-wider">
              edges:
            </span>
            {[1, 2, 3].map((tier) => (
              <button
                key={tier}
                onClick={() =>
                  setVisibleTiers((prev) => ({ ...prev, [tier]: !prev[tier] }))
                }
                className={`px-2 py-1 rounded border ${
                  visibleTiers[tier]
                    ? "bg-bg-hover border-accent-blue text-text-primary"
                    : "bg-bg-card border-border text-text-muted"
                }`}
              >
                <span
                  className="inline-block w-2 h-2 rounded-full mr-1"
                  style={{ backgroundColor: TIER_STYLE[tier].color }}
                />
                T{tier}
              </button>
            ))}

            <span className="text-[10px] text-text-muted uppercase tracking-wider ml-3">
              show:
            </span>
            <span
              className="px-2 py-1 rounded border bg-accent-emerald/15 border-accent-emerald text-accent-emerald"
              title="Mutual-confirmed network members (16 anchors, T1+T2a edges) — always shown"
            >
              ● mutual ({meta.mutual_members || 16})
            </span>
            <button
              onClick={() => setShowWatched(!showWatched)}
              className={`px-2 py-1 rounded border ${
                showWatched
                  ? "bg-bg-hover border-text-secondary text-text-secondary"
                  : "bg-bg-card border-border text-text-muted"
              }`}
              title="Watched: anchors follow them but no mutual confirmed (one-way only)"
            >
              {showWatched ? "○" : "✕"} watched ({meta.watched_nodes || 0})
            </button>
            <button
              onClick={() => setShowCelebrities(!showCelebrities)}
              className={`px-2 py-1 rounded border ${
                showCelebrities
                  ? "bg-bg-hover border-accent-rose text-accent-rose"
                  : "bg-bg-card border-border text-text-muted"
              }`}
              title="Auto-flagged celebrities (followers >> typical anchor) — Jack Ma effect, hidden by default"
            >
              {showCelebrities ? "☒" : "☐"} celebs ({meta.celebrity_filtered || 0})
            </button>
            <button
              onClick={() => setShowIsolated(!showIsolated)}
              className={`px-2 py-1 rounded border ${
                showIsolated
                  ? "bg-bg-hover border-accent-amber text-accent-amber"
                  : "bg-bg-card border-border text-text-muted"
              }`}
              title="Show watched nodes with no edges in current view"
            >
              {showIsolated ? "☒" : "☐"} isolated
            </button>
          </div>

          {/* Expandable filter panel */}
          {showFiltersPanel && (
            <div className="mt-3 pt-3 border-t border-border space-y-2 text-[10px] font-mono">
              {availableSectors.length > 0 && (
                <FilterRow
                  label="Sector"
                  options={availableSectors}
                  selected={sectorFilter}
                  onToggle={(v) => toggleArray(sectorFilter, setSectorFilter, v)}
                />
              )}
              {availableTiers.length > 0 && (
                <FilterRow
                  label="Tier"
                  options={availableTiers}
                  selected={tierFilter}
                  onToggle={(v) => toggleArray(tierFilter, setTierFilter, v)}
                />
              )}
              {availableLanguages.length > 0 && (
                <FilterRow
                  label="Lang"
                  options={availableLanguages}
                  selected={languageFilter}
                  onToggle={(v) => toggleArray(languageFilter, setLanguageFilter, v)}
                />
              )}
              {(sectorFilter.length > 0 ||
                tierFilter.length > 0 ||
                languageFilter.length > 0) && (
                <button
                  onClick={resetFilters}
                  className="text-[10px] text-accent-rose hover:underline"
                >
                  clear all filters
                </button>
              )}
            </div>
          )}
        </div>

        {/* Graph canvas */}
        <div
          ref={containerRef}
          id="graph-container"
          className="flex-1 min-h-0 relative bg-bg-base overflow-hidden"
        >
          {size.w > 0 && size.h > 0 && (
            <ForceGraph2D
              ref={fgRef}
              graphData={filteredData}
              width={size.w}
              height={size.h}
              backgroundColor="#0F1117"
              nodeId="id"
              nodeLabel={(n) => `${n.label}`}
              nodeVal={(n) => {
                if (n.is_mutual_member) return Math.max(8, (n.pagerank || 0) * 350);
                // Watched: tiny dots — they're not network members, just being followed
                return 1.5;
              }}
              nodeColor={(n) => {
                if (n.is_mutual_member) {
                  const base = CLUSTER_COLORS[(n.cluster || 0) % CLUSTER_COLORS.length];
                  return base;
                }
                // Watched: dim slate (no cluster — not part of the real network)
                return "rgba(100, 116, 139, 0.45)";
              }}
              nodeCanvasObjectMode={() => "after"}
              nodeCanvasObject={(node, ctx, globalScale) => {
                // Watched nodes: render as hollow ring to clearly distinguish from
                // mutual members (filled circles). This is the visual contract:
                // filled = in the network, hollow = followed by the network.
                if (!node.is_mutual_member) {
                  ctx.beginPath();
                  ctx.arc(node.x, node.y, 1.8, 0, 2 * Math.PI);
                  ctx.strokeStyle = "rgba(148, 163, 184, 0.55)";
                  ctx.lineWidth = 0.8;
                  ctx.stroke();
                }
                // Label only for mutual members + hovered/selected (avoid label spam)
                const shouldLabel =
                  node.is_mutual_member || node === hoveredNode || node === selectedNode;
                if (shouldLabel) {
                  const fontSize = node.is_mutual_member
                    ? Math.max(10, 13 / globalScale)
                    : Math.max(9, 11 / globalScale);
                  ctx.font = `${fontSize}px "JetBrains Mono", monospace`;
                  ctx.textAlign = "center";
                  ctx.textBaseline = "top";
                  ctx.fillStyle = node.is_mutual_member ? "#E6EBF5" : "#94A3B8";
                  ctx.fillText(node.label, node.x, node.y + 9);
                }
                // Bridge ring on mutual members that span multiple circles
                if (node.is_mutual_member && node.is_bridge) {
                  ctx.beginPath();
                  ctx.arc(
                    node.x,
                    node.y,
                    Math.max(5, (node.pagerank || 0) * 350) + 3,
                    0,
                    2 * Math.PI
                  );
                  ctx.strokeStyle = "#F59E0B";
                  ctx.lineWidth = 1.8;
                  ctx.stroke();
                }
              }}
              linkColor={(link) => TIER_STYLE[link.tier]?.color || "rgba(100,116,139,0.2)"}
              linkWidth={(link) => TIER_STYLE[link.tier]?.width || 0.5}
              linkLineDash={(link) => TIER_STYLE[link.tier]?.dash || null}
              linkDirectionalArrowLength={(link) => (link.tier === 2 ? 3 : 0)}
              linkDirectionalArrowRelPos={0.92}
              onNodeHover={setHoveredNode}
              onNodeClick={handleNodeClick}
              cooldownTicks={120}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.35}
              warmupTicks={80}
            />
          )}

          {/* Hover tooltip */}
          {hoveredNode && (
            <div className="absolute top-4 left-4 bg-bg-card border border-border rounded-lg p-4 shadow-xl max-w-xs text-xs font-mono pointer-events-none">
              <div className="text-sm font-semibold text-text-primary">
                {hoveredNode.label}
              </div>
              {hoveredNode.name && hoveredNode.name !== hoveredNode.label && (
                <div className="text-text-secondary text-[11px] mt-0.5">
                  {hoveredNode.name}
                </div>
              )}
              {/* Status badge — the most important field */}
              <div className="mt-2">
                {hoveredNode.is_mutual_member ? (
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30">
                    ● mutual member
                  </span>
                ) : hoveredNode.is_celebrity_outbound ? (
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-accent-rose/15 text-accent-rose border border-accent-rose/30">
                    ✕ celebrity (auto-filtered)
                  </span>
                ) : (
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-bg-hover text-text-muted border border-border">
                    ○ watched (one-way only)
                  </span>
                )}
              </div>
              <div className="mt-2 space-y-0.5 text-text-muted">
                {hoveredNode.is_mutual_member && hoveredNode.circles?.length > 0 && (
                  <div>
                    circles:{" "}
                    <span className="text-accent-emerald">
                      {hoveredNode.circles.join(" + ")}
                    </span>
                    {hoveredNode.is_bridge && " ⭐ bridge"}
                  </div>
                )}
                {hoveredNode.anchor_count != null && hoveredNode.anchor_count > 0 && (
                  <div>
                    followed by:{" "}
                    <span className="text-accent-amber">
                      {hoveredNode.anchor_count}/16 anchors
                    </span>
                    {!hoveredNode.is_mutual_member && (
                      <span className="text-text-muted"> (one-way)</span>
                    )}
                  </div>
                )}
                {hoveredNode.followers_count != null && (
                  <div>
                    followers:{" "}
                    <span className="text-text-secondary">
                      {hoveredNode.followers_count?.toLocaleString() || "—"}
                    </span>
                  </div>
                )}
                {hoveredNode.is_mutual_member && (
                  <>
                    <div>
                      cluster: <span className="text-text-secondary">#{hoveredNode.cluster}</span>
                    </div>
                    <div>
                      PageRank:{" "}
                      <span className="text-text-secondary">
                        {(hoveredNode.pagerank || 0).toFixed(4)}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right-side inspector panel */}
      <div className="w-80 flex-shrink-0 border-l border-border bg-bg-panel overflow-y-auto">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">
            {selectedNode ? "Node Inspector" : "Cluster Overview"}
          </h2>
        </div>

        {!selectedNode && (
          <div className="p-5 space-y-4">
            <div className="text-[11px] text-text-secondary font-mono leading-relaxed bg-accent-emerald/5 border border-accent-emerald/20 rounded p-3">
              <div className="text-accent-emerald font-semibold mb-1">
                ● Filled circles: mutual members
              </div>
              These {meta.mutual_members || 16} accounts have confirmed mutual follows
              with each other (T1 ground truth). They are the real network.
              <div className="text-text-muted font-semibold mt-2 mb-1">
                ○ Hollow rings: watched
              </div>
              These accounts are <strong>followed by</strong> anchors, but mutual
              follow is not verified. Treat as outreach targets, not network members.
              Centrality metrics don't apply.
              <div className="text-accent-rose font-semibold mt-2 mb-1">
                ✕ Celebrities (hidden by default)
              </div>
              Auto-flagged when followers ≥ 5× median anchor followers. Jack Ma
              effect — they don't follow back.
            </div>

            <div className="space-y-3">
              {clusterSummary.map((c) => (
                <div
                  key={c.cluster_id}
                  className="bg-bg-card border border-border rounded-lg p-3"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{
                        backgroundColor: CLUSTER_COLORS[c.cluster_id % CLUSTER_COLORS.length],
                      }}
                    />
                    <div className="text-xs font-semibold text-text-primary font-mono">
                      Cluster #{c.cluster_id}
                    </div>
                    <div className="text-[10px] text-text-muted ml-auto font-mono">
                      {c.size} members
                    </div>
                  </div>

                  {c.circles_touched?.length > 0 && (
                    <div className="text-[10px] text-accent-emerald mb-2 font-mono">
                      spans: {c.circles_touched.join(" + ")}
                    </div>
                  )}

                  <div className="text-[11px] text-text-secondary mb-1">
                    <span className="text-text-muted">entry:</span>{" "}
                    <span className="font-mono text-accent-blue">
                      {c.recommended_entry_point}
                    </span>
                  </div>
                  <div className="text-[11px] text-text-secondary">
                    <span className="text-text-muted">bridges:</span>{" "}
                    <span className="font-mono text-accent-amber">
                      {c.bridge_nodes?.join(", ") || "—"}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Top PageRank */}
            <div>
              <div className="text-[10px] uppercase tracking-widest text-text-muted mb-2 font-mono">
                Top 10 by PageRank
              </div>
              <div className="space-y-1">
                {graphData.metadata.top_pagerank.map((p, i) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-2 text-[11px] font-mono text-text-secondary"
                  >
                    <span className="text-text-muted w-4 text-right">{i + 1}.</span>
                    <span className="text-accent-blue flex-1">@{p.id}</span>
                    <span className="text-text-muted">{p.pagerank.toFixed(4)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {selectedNode && (
          <div className="p-5 space-y-4">
            <button
              onClick={() => setSelectedNode(null)}
              className="text-[11px] text-text-muted hover:text-text-primary font-mono"
            >
              ← back to cluster overview
            </button>

            <div>
              <div className="text-lg font-semibold text-text-primary">
                {selectedNode.label}
              </div>
              {selectedNode.name && (
                <div className="text-sm text-text-secondary mt-0.5">{selectedNode.name}</div>
              )}
              {selectedNode.description && (
                <div className="text-[11px] text-text-muted mt-2 leading-relaxed">
                  {selectedNode.description}
                </div>
              )}
            </div>

            {/* Status badge — the most important field */}
            <div>
              {selectedNode.is_mutual_member ? (
                <span className="inline-block px-2 py-1 text-[10px] rounded bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30 font-mono">
                  ● Mutual member · in the network
                </span>
              ) : selectedNode.is_celebrity_outbound ? (
                <span className="inline-block px-2 py-1 text-[10px] rounded bg-accent-rose/15 text-accent-rose border border-accent-rose/30 font-mono">
                  ✕ Celebrity (auto-filtered) · {selectedNode.followers_count?.toLocaleString()} followers
                </span>
              ) : (
                <span className="inline-block px-2 py-1 text-[10px] rounded bg-bg-hover text-text-muted border border-border font-mono">
                  ○ Watched · followed by anchors but no mutual confirmed
                </span>
              )}
            </div>

            <div className="bg-bg-card border border-border rounded-lg p-3 space-y-2 text-[11px] font-mono">
              {selectedNode.is_mutual_member && selectedNode.circles?.length > 0 && (
                <Metric
                  label="circles"
                  value={selectedNode.circles.join(" + ")}
                  highlight={selectedNode.is_bridge}
                />
              )}
              {selectedNode.anchor_count != null && selectedNode.anchor_count > 0 && (
                <Metric
                  label="followed by"
                  value={
                    selectedNode.is_mutual_member
                      ? `${selectedNode.anchor_count}/16 anchors (mutual)`
                      : `${selectedNode.anchor_count}/16 anchors (one-way)`
                  }
                />
              )}
              {selectedNode.followers_count != null && (
                <Metric
                  label="followers"
                  value={selectedNode.followers_count?.toLocaleString() || "—"}
                />
              )}
              {selectedNode.is_mutual_member ? (
                <>
                  <Metric label="cluster" value={`#${selectedNode.cluster}`} />
                  <Metric
                    label="PageRank"
                    value={(selectedNode.pagerank || 0).toFixed(5)}
                  />
                  <Metric
                    label="Betweenness"
                    value={(selectedNode.betweenness || 0).toFixed(5)}
                  />
                </>
              ) : (
                <div className="text-[10px] text-text-muted italic pt-1">
                  PageRank / cluster computed only on the mutual subgraph
                  (16 anchors). Watched nodes aren't part of it by definition.
                </div>
              )}
              <Metric label="degree" value={selectedNode.degree || 0} />
            </div>

            {/* Classified data (sector, tier, score, cooperability) */}
            {(selectedNode.overall_score != null || selectedNode.sector) && (
              <div className="bg-bg-card border border-border rounded-lg p-3 space-y-2 text-[11px] font-mono">
                <div className="text-[9px] uppercase tracking-widest text-text-muted mb-1">
                  Dual-Layer score
                </div>
                {selectedNode.overall_score != null && (
                  <Metric
                    label="overall"
                    value={
                      <span className="text-accent-emerald font-semibold">
                        {selectedNode.overall_score} / 100
                      </span>
                    }
                  />
                )}
                {selectedNode.sector && <Metric label="sector" value={selectedNode.sector} />}
                {selectedNode.tier && <Metric label="tier" value={selectedNode.tier} />}
                {selectedNode.language && <Metric label="lang" value={selectedNode.language} />}
                {selectedNode.cooperability?.is_contactable != null && (
                  <Metric
                    label="contactable"
                    value={
                      selectedNode.cooperability.is_contactable ? (
                        <span className="text-accent-emerald">YES</span>
                      ) : (
                        <span className="text-text-muted">NO</span>
                      )
                    }
                  />
                )}
                {selectedNode.estimated_price_tier && (
                  <Metric label="price" value={selectedNode.estimated_price_tier} />
                )}
              </div>
            )}

            <div className="space-y-2">
              <Link
                to={`/profile/${selectedNode.id}`}
                className="block text-center py-2 bg-accent-emerald/10 border border-accent-emerald/30 rounded-md text-xs text-accent-emerald hover:bg-accent-emerald/20 transition-colors font-mono"
              >
                View full profile →
              </Link>
              <a
                href={`https://x.com/${selectedNode.id}`}
                target="_blank"
                rel="noreferrer"
                className="block text-center py-2 bg-accent-blue/10 border border-accent-blue/30 rounded-md text-xs text-accent-blue hover:bg-accent-blue/20 transition-colors font-mono"
              >
                Open on x.com ↗
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value, highlight }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-text-muted">{label}:</span>
      <span className={highlight ? "text-accent-amber font-semibold" : "text-text-secondary"}>
        {value}
      </span>
    </div>
  );
}

function FilterRow({ label, options, selected, onToggle }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-text-muted uppercase tracking-wider w-12">{label}:</span>
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
