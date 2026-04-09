import { useState } from "react";
import kolsData from "../data/kols.json";

const FIELD_MAPPING = [
  { ours: "id", lighthouse: "handle", type: "primary_key" },
  { ours: "name", lighthouse: "display_name", type: "string" },
  { ours: "sector", lighthouse: "category", type: "enum" },
  { ours: "tier", lighthouse: "tier_level", type: "enum" },
  { ours: "language", lighthouse: "primary_language", type: "enum" },
  { ours: "region", lighthouse: "region", type: "enum" },
  { ours: "followers_count", lighthouse: "follower_count", type: "integer" },
  { ours: "overall_score", lighthouse: "quality_score", type: "float" },
  { ours: "scores.view_velocity", lighthouse: "engagement_score", type: "float" },
  { ours: "scores.audience_authenticity", lighthouse: "authenticity_score", type: "float" },
  { ours: "cooperability.is_contactable", lighthouse: "is_onboardable", type: "boolean" },
  { ours: "cooperability.contact_method", lighthouse: "preferred_channel", type: "enum" },
  { ours: "outreach_angle", lighthouse: "custom_pitch", type: "text" },
  { ours: "estimated_price_tier", lighthouse: "price_range", type: "string" },
];

export default function LighthouseIntegration() {
  const [importing, setImporting] = useState(false);
  const [done, setDone] = useState(false);
  const [scope, setScope] = useState("contactable"); // all | contactable | in_graph

  const count =
    scope === "all"
      ? kolsData.kols.length
      : scope === "contactable"
      ? kolsData.kols.filter((k) => k.cooperability?.is_contactable).length
      : kolsData.kols.filter((k) => k.in_graph).length;

  const handleImport = () => {
    setImporting(true);
    setTimeout(() => {
      setImporting(false);
      setDone(true);
    }, 2500);
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text-primary">Lighthouse Integration</h1>
          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">
            🎨 DEMO MODE
          </span>
        </div>
        <div className="text-xs text-text-muted font-mono mt-0.5">
          Push KOL database → app.lhdao.top · Task 2 ↔ Demo bridge
        </div>
      </div>

      <div className="p-6 max-w-4xl">
        {done ? (
          <div className="bg-accent-emerald/10 border border-accent-emerald/40 rounded-lg p-8 text-center">
            <div className="text-5xl mb-3">✅</div>
            <h2 className="text-xl font-semibold text-text-primary mb-2">
              Successfully imported {count.toLocaleString()} KOLs to Lighthouse
            </h2>
            <p className="text-xs text-text-secondary font-mono max-w-md mx-auto">
              All classified KOLs are now available in the Lighthouse platform for campaign
              creation. Field mappings applied per the schema below.
            </p>
            <div className="mt-6 flex justify-center gap-3">
              <a
                href="https://app.lhdao.top"
                target="_blank"
                rel="noreferrer"
                className="px-4 py-2 bg-accent-blue/15 border border-accent-blue rounded-md text-xs font-mono text-accent-blue"
              >
                Open Lighthouse →
              </a>
              <button
                onClick={() => setDone(false)}
                className="px-4 py-2 bg-bg-hover border border-border rounded-md text-xs font-mono text-text-muted"
              >
                Import again
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="bg-bg-card border border-border rounded-lg p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Select Scope
              </h3>
              <div className="flex gap-2 text-xs font-mono">
                {[
                  { v: "all", label: `All KOLs (${kolsData.kols.length})` },
                  {
                    v: "contactable",
                    label: `Contactable only (${
                      kolsData.kols.filter((k) => k.cooperability?.is_contactable)
                        .length
                    })`,
                  },
                  {
                    v: "in_graph",
                    label: `In network graph (${
                      kolsData.kols.filter((k) => k.in_graph).length
                    })`,
                  },
                ].map((o) => (
                  <button
                    key={o.v}
                    onClick={() => setScope(o.v)}
                    className={`px-3 py-1.5 rounded border ${
                      scope === o.v
                        ? "bg-accent-blue/20 border-accent-blue text-accent-blue"
                        : "bg-bg-hover border-border text-text-muted"
                    }`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="bg-bg-card border border-border rounded-lg p-5">
              <h3 className="text-sm font-semibold text-text-primary mb-3">
                Field Mapping Preview
              </h3>
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="text-text-muted text-[10px] uppercase tracking-wider border-b border-border">
                    <th className="py-2 text-left">Our Field</th>
                    <th className="py-2 text-center">→</th>
                    <th className="py-2 text-left">Lighthouse Field</th>
                    <th className="py-2 text-right">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {FIELD_MAPPING.map((m, i) => (
                    <tr key={i}>
                      <td className="py-2 text-accent-blue">{m.ours}</td>
                      <td className="py-2 text-center text-text-muted">→</td>
                      <td className="py-2 text-accent-emerald">{m.lighthouse}</td>
                      <td className="py-2 text-right text-text-muted">{m.type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex justify-end">
              <button
                onClick={handleImport}
                disabled={importing}
                className="px-6 py-2.5 bg-accent-emerald/15 border border-accent-emerald rounded-md text-sm font-mono text-accent-emerald hover:bg-accent-emerald/25 disabled:opacity-50"
              >
                {importing
                  ? `Importing ${count.toLocaleString()} KOLs...`
                  : `Import ${count.toLocaleString()} KOLs to Lighthouse`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
