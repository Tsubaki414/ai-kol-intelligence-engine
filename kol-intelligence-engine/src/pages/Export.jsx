import { useState } from "react";
import kolsData from "../data/kols.json";
import graphData from "../data/graph.json";

export default function ExportPage() {
  const [format, setFormat] = useState("json");
  const [scope, setScope] = useState("all");

  const handleDownload = (filename, content, mimeType) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // CSV-safe cell escaping (RFC 4180)
  const escapeCsvCell = (v) => {
    if (v == null) return "";
    const s = String(v);
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };

  const downloadKols = () => {
    let filtered = kolsData.kols;
    if (scope === "anchors") filtered = filtered.filter((k) => k.type === "anchor");
    if (scope === "hubs") filtered = filtered.filter((k) => k.type === "hub");
    if (scope === "peripherals") filtered = filtered.filter((k) => k.type === "peripheral");
    if (scope === "bridges") filtered = filtered.filter((k) => k.is_bridge);
    if (scope === "contactable") filtered = filtered.filter((k) => k.cooperability?.is_contactable);

    if (format === "json") {
      handleDownload(
        `kols_${scope}.json`,
        JSON.stringify({ ...kolsData, kols: filtered }, null, 2),
        "application/json"
      );
    } else {
      const headers = [
        "handle", "name", "bio", "type", "sector", "tier", "language", "region",
        "circles", "followers", "overall_score", "view_velocity", "content_originality",
        "audience_authenticity", "sector_relevance", "growth_trend",
        "pagerank", "betweenness", "is_bridge", "in_graph", "is_contactable",
        "contact_method", "public_email", "estimated_price_tier", "outreach_angle", "x_url",
      ];
      const rows = filtered.map((k) => [
        k.handle || "@" + k.id,
        k.name,
        k.bio,
        k.type,
        k.sector,
        k.tier,
        k.language,
        k.region,
        (k.circles || []).join("+"),
        k.followers_count,
        k.overall_score,
        k.scores?.view_velocity,
        k.scores?.content_originality,
        k.scores?.audience_authenticity,
        k.scores?.sector_relevance,
        k.scores?.growth_trend,
        k.pagerank,
        k.betweenness,
        k.is_bridge ? "yes" : "",
        k.in_graph ? "yes" : "",
        k.cooperability?.is_contactable ? "yes" : "",
        k.cooperability?.contact_method,
        k.cooperability?.public_email,
        k.estimated_price_tier,
        k.outreach_angle,
        k.x_url || `https://x.com/${k.id}`,
      ]);
      const csv = [
        headers.join(","),
        ...rows.map((r) => r.map(escapeCsvCell).join(",")),
      ].join("\n");
      // UTF-8 BOM for Excel
      handleDownload(`kols_${scope}.csv`, "\uFEFF" + csv, "text/csv;charset=utf-8");
    }
  };

  const downloadGraph = () => {
    handleDownload("graph.json", JSON.stringify(graphData, null, 2), "application/json");
  };

  return (
    <div className="h-full overflow-y-auto p-6 max-w-3xl">
      <h1 className="text-lg font-semibold text-text-primary mb-6">Export Data</h1>

      <div className="space-y-6">
        <div className="bg-bg-card border border-border rounded-lg p-5">
          <h2 className="text-sm font-semibold text-text-primary mb-4">KOL List</h2>

          <div className="space-y-3">
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-2 font-mono">
                Format
              </label>
              <div className="flex gap-2">
                {["json", "csv"].map((f) => (
                  <button
                    key={f}
                    onClick={() => setFormat(f)}
                    className={`px-3 py-1.5 text-xs font-mono rounded border ${
                      format === f
                        ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
                        : "bg-bg-hover border-border text-text-muted"
                    }`}
                  >
                    {f.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-2 font-mono">
                Scope
              </label>
              <div className="flex gap-2 flex-wrap">
                {[
                  { v: "all", label: `All (${kolsData.kols.length})` },
                  {
                    v: "contactable",
                    label: `Contactable (${kolsData.kols.filter((k) => k.cooperability?.is_contactable).length})`,
                  },
                  {
                    v: "anchors",
                    label: `Anchors (${kolsData.kols.filter((k) => k.type === "anchor").length})`,
                  },
                  {
                    v: "hubs",
                    label: `Hubs (${kolsData.kols.filter((k) => k.type === "hub").length})`,
                  },
                  {
                    v: "peripherals",
                    label: `Peripherals (${kolsData.kols.filter((k) => k.type === "peripheral").length})`,
                  },
                  {
                    v: "bridges",
                    label: `Bridges (${kolsData.kols.filter((k) => k.is_bridge).length})`,
                  },
                ].map((o) => (
                  <button
                    key={o.v}
                    onClick={() => setScope(o.v)}
                    className={`px-3 py-1.5 text-xs font-mono rounded border ${
                      scope === o.v
                        ? "bg-accent-emerald/20 border-accent-emerald text-accent-emerald"
                        : "bg-bg-hover border-border text-text-muted"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={downloadKols}
              className="mt-3 px-4 py-2 bg-accent-blue/15 border border-accent-blue rounded-md text-xs font-mono text-accent-blue hover:bg-accent-blue/25"
            >
              📥 Download kols_{scope}.{format}
            </button>
          </div>
        </div>

        <div className="bg-bg-card border border-border rounded-lg p-5">
          <h2 className="text-sm font-semibold text-text-primary mb-2">Graph Data</h2>
          <div className="text-xs text-text-muted mb-4">
            Full graph.json including nodes, edges (with tiers), and metadata (cluster summary,
            top PageRank, top betweenness).
          </div>
          <button
            onClick={downloadGraph}
            className="px-4 py-2 bg-accent-emerald/15 border border-accent-emerald rounded-md text-xs font-mono text-accent-emerald hover:bg-accent-emerald/25"
          >
            📥 Download graph.json
          </button>
        </div>
      </div>
    </div>
  );
}
