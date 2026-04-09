import { NavLink } from "react-router-dom";
import graphMeta from "../data/graph_meta.json";

const FULL_FEATURES = [
  { to: "/dashboard", label: "KOL Database", icon: "📊" },
  { to: "/graph", label: "Network Graph", icon: "🕸️", badge: "CORE" },
  { to: "/outreach", label: "Outreach Panel", icon: "🗝️", badge: "ACTION" },
  { to: "/agent", label: "AI Agent", icon: "🤖" },
  { to: "/discovery", label: "Discovery Pipeline", icon: "🔍" },
  { to: "/profile", label: "KOL Profiles", icon: "👤" },
  { to: "/export", label: "Export", icon: "📥" },
];

const DEMO_MODE = [
  { to: "/guilds", label: "Guild Management", icon: "🏰" },
  { to: "/brief", label: "AI Brief Generator", icon: "📝" },
  { to: "/simulator", label: "Campaign Simulator", icon: "📈" },
  { to: "/lighthouse", label: "Lighthouse Integration", icon: "🔗" },
  { to: "/onchain", label: "On-chain Verification", icon: "⛓️" },
];

function Section({ title, items }) {
  return (
    <div className="mb-6">
      <h3 className="text-[10px] uppercase tracking-widest text-text-muted px-3 mb-2 font-mono">
        {title}
      </h3>
      <nav className="space-y-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-bg-hover text-text-primary font-medium"
                  : "text-text-secondary hover:bg-bg-hover/60 hover:text-text-primary"
              }`
            }
          >
            <span className="text-base">{item.icon}</span>
            <span className="flex-1">{item.label}</span>
            {item.badge && (
              <span className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded bg-accent-blue/20 text-accent-blue">
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export default function Sidebar() {
  return (
    <aside className="w-64 border-r border-border bg-bg-panel flex flex-col h-screen">
      <div className="px-4 py-4 border-b border-border">
        <div className="text-sm font-semibold text-text-primary">
          AI KOL Intelligence Engine
        </div>
        <div className="text-[11px] text-text-muted font-mono mt-0.5">
          Mango Labs · KOL Intelligence
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-4 px-2">
        <Section title="Full Features" items={FULL_FEATURES} />
        <Section title="Demo Mode" items={DEMO_MODE} />
      </div>

      <div className="border-t border-border px-4 py-3 text-[10px] text-text-muted font-mono">
        <div>
          <span className="text-accent-emerald">{graphMeta.mutual_members}</span> mutual ·{" "}
          {graphMeta.watched_nodes} watched ·{" "}
          <span className="text-accent-rose">{graphMeta.celebrity_filtered}</span> filtered
        </div>
        <div className="mt-0.5">
          {graphMeta.total_nodes} nodes ·{" "}
          {graphMeta.total_edges.toLocaleString()} edges ·{" "}
          {graphMeta.connected_clusters} clusters
        </div>
      </div>
    </aside>
  );
}
