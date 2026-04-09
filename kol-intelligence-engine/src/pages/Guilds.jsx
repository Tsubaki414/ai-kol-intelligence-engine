import { useState } from "react";

// Sample guild data — one per ground-truth circle + synthetic S-Tier example.
const GUILDS = [
  {
    id: "g001",
    name: "Virtuals Chinese Builders Guild",
    tier: "S-Tier",
    description:
      "核心中文 Virtuals Protocol 生态 builder 圈。成员构建 AI Agent 产品、推动中文 Virtuals 社区增长。",
    leader: { handle: "@0xmediaco", name: "0xMedia", role: "Guild Leader" },
    members: [
      { handle: "@Rav_Hedda", name: "Hedda🐽", role: "Co-founder", campaigns: 12 },
      { handle: "@starzq", name: "Star / Day1 Podcast", role: "Media Lead", campaigns: 23 },
      { handle: "@lanhubiji", name: "蓝狐 Blue Fox Notes", role: "Content", campaigns: 34 },
      { handle: "@iamyourchaos", name: "小捕手 Chaos🦅", role: "Community", campaigns: 18 },
      { handle: "@0xzagen", name: "zagen扎根", role: "Builder Relations", campaigns: 9 },
    ],
    stats: {
      total_campaigns: 96,
      avg_engagement: "4.2%",
      total_reach: "2.4M",
      response_time_h: 4,
    },
    privileges: [
      "独家 Virtuals ecosystem drops",
      "佣金 +25%",
      "季度战略会议",
      "优先接单权",
    ],
  },
  {
    id: "g002",
    name: "Web3 Media Circle",
    tier: "A-Tier",
    description:
      "XHunt AI+Web3 中文媒体圈。成员为记者、分析师、媒体创始人，擅长深度报道与行业分析。",
    leader: { handle: "@BiteyeCN", name: "Biteye", role: "Guild Leader" },
    members: [
      { handle: "@DeFiTeddy2020", name: "DeFi Teddy", role: "Analyst", campaigns: 15 },
      { handle: "@Web3SisterA", name: "Web3 Sister A", role: "Content", campaigns: 11 },
      { handle: "@0xKevin00", name: "0xKevin", role: "Research", campaigns: 8 },
      { handle: "@colinwu", name: "吴说 Colin Wu", role: "Bridge", campaigns: 28 },
      { handle: "@PhyrexNi", name: "Phyrex", role: "Bridge", campaigns: 19 },
    ],
    stats: {
      total_campaigns: 81,
      avg_engagement: "3.8%",
      total_reach: "1.8M",
      response_time_h: 6,
    },
    privileges: ["佣金 +10%", "优先接单", "月度 newsletter feature"],
  },
  {
    id: "g003",
    name: "华语主流加密分析圈 Guild",
    tier: "A-Tier",
    description:
      "主流华语加密分析师联盟，专注 market analysis, trading signal, technical research。",
    leader: { handle: "@KuiGas", name: "KuiGas", role: "Guild Leader" },
    members: [
      { handle: "@ZKSgu", name: "ZKS gu", role: "Co-Lead", campaigns: 14 },
      { handle: "@jason_chen998", name: "Jason Chen", role: "Analyst", campaigns: 10 },
      { handle: "@BTCdayu", name: "BTC 大鱼", role: "Technical", campaigns: 22 },
      { handle: "@colinwu", name: "吴说 Colin Wu", role: "Shared Bridge", campaigns: 28 },
      { handle: "@PhyrexNi", name: "Phyrex", role: "Shared Bridge", campaigns: 19 },
    ],
    stats: {
      total_campaigns: 73,
      avg_engagement: "3.5%",
      total_reach: "1.5M",
      response_time_h: 8,
    },
    privileges: ["佣金 +10%", "优先接单"],
  },
];

export default function Guilds() {
  const [selectedId, setSelectedId] = useState(GUILDS[0].id);
  const [showCreate, setShowCreate] = useState(false);

  const selected = GUILDS.find((g) => g.id === selectedId) || GUILDS[0];

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold text-text-primary">Guild Management</h1>
              <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">
                🎨 DEMO MODE
              </span>
            </div>
            <div className="text-xs text-text-muted font-mono mt-0.5">
              KOL 组织化管理 — Guild leader 负责招募 / 质控 / 任务分配。S-Tier Guild 享独家权益。
            </div>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-accent-blue/15 border border-accent-blue rounded-md text-xs font-mono text-accent-blue hover:bg-accent-blue/25"
          >
            + Create Guild
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Guild list */}
        <div className="w-80 border-r border-border overflow-y-auto bg-bg-panel">
          {GUILDS.map((g) => (
            <button
              key={g.id}
              onClick={() => setSelectedId(g.id)}
              className={`w-full text-left px-5 py-4 border-b border-border transition-colors ${
                selectedId === g.id ? "bg-bg-hover" : "hover:bg-bg-hover/60"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-semibold text-text-primary truncate">
                  {g.name}
                </div>
                <TierTag tier={g.tier} />
              </div>
              <div className="text-[10px] text-text-muted font-mono mt-1">
                {g.members.length + 1} members · {g.stats.total_campaigns} campaigns
              </div>
              <div className="text-[10px] text-text-secondary mt-1 line-clamp-2">
                {g.description}
              </div>
            </button>
          ))}
        </div>

        {/* Guild detail */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex items-start justify-between mb-4">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-semibold text-text-primary">{selected.name}</h2>
                <TierTag tier={selected.tier} />
              </div>
              <div className="text-xs text-text-secondary mt-1 max-w-3xl">
                {selected.description}
              </div>
            </div>
          </div>

          {/* Leader card */}
          <div className="bg-accent-emerald/5 border border-accent-emerald/30 rounded-lg p-4 mb-4">
            <div className="text-[10px] uppercase tracking-widest text-accent-emerald font-mono mb-1">
              Guild Leader
            </div>
            <div className="text-lg text-text-primary font-mono">{selected.leader.handle}</div>
            <div className="text-xs text-text-secondary">{selected.leader.name} — {selected.leader.role}</div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-4 gap-3 mb-5">
            <StatCard label="Total Campaigns" value={selected.stats.total_campaigns} />
            <StatCard label="Avg Engagement" value={selected.stats.avg_engagement} accent="emerald" />
            <StatCard label="Total Reach" value={selected.stats.total_reach} accent="blue" />
            <StatCard label="Avg Response" value={`${selected.stats.response_time_h}h`} accent="amber" />
          </div>

          {/* Members */}
          <div className="bg-bg-card border border-border rounded-lg p-5 mb-4">
            <h3 className="text-sm font-semibold text-text-primary mb-3">
              Members ({selected.members.length + 1} including Leader)
            </h3>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-text-muted text-[10px] uppercase tracking-wider border-b border-border">
                  <th className="py-2 text-left">Handle</th>
                  <th className="py-2 text-left">Name</th>
                  <th className="py-2 text-left">Role</th>
                  <th className="py-2 text-right">Campaigns</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                <tr>
                  <td className="py-2 text-accent-emerald">{selected.leader.handle}</td>
                  <td className="py-2 text-text-secondary">{selected.leader.name}</td>
                  <td className="py-2 text-text-muted">{selected.leader.role}</td>
                  <td className="py-2 text-right text-text-muted">—</td>
                </tr>
                {selected.members.map((m) => (
                  <tr key={m.handle}>
                    <td className="py-2 text-accent-blue">{m.handle}</td>
                    <td className="py-2 text-text-secondary">{m.name}</td>
                    <td className="py-2 text-text-muted">{m.role}</td>
                    <td className="py-2 text-right text-text-muted">{m.campaigns}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Privileges */}
          <div className="bg-bg-card border border-border rounded-lg p-5">
            <h3 className="text-sm font-semibold text-text-primary mb-3">Privileges</h3>
            <ul className="space-y-1 text-xs text-text-secondary">
              {selected.privileges.map((p, i) => (
                <li key={i}>
                  <span className="text-accent-emerald mr-2">✓</span>
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Create Guild modal */}
      {showCreate && (
        <Modal onClose={() => setShowCreate(false)}>
          <h2 className="text-lg font-semibold text-text-primary mb-1">Create New Guild</h2>
          <div className="text-xs text-text-muted font-mono mb-4">
            Demo mode — form is for UI preview only.
          </div>
          <div className="space-y-3 text-xs">
            <Input label="Guild Name" placeholder="AI+Crypto Bridge Network" />
            <Input label="Description" placeholder="Describe the guild's focus area..." />
            <Input label="Leader handle" placeholder="@handle" />
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setShowCreate(false)}
                className="px-4 py-1.5 text-[11px] font-mono bg-bg-hover border border-border rounded text-text-muted"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowCreate(false);
                  alert("Demo mode: guild creation requires backend.");
                }}
                className="px-4 py-1.5 text-[11px] font-mono bg-accent-blue/20 border border-accent-blue rounded text-accent-blue"
              >
                Create
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function TierTag({ tier }) {
  const color =
    tier === "S-Tier"
      ? "bg-accent-amber/15 text-accent-amber border-accent-amber/30"
      : "bg-accent-blue/15 text-accent-blue border-accent-blue/30";
  return (
    <span className={`px-2 py-0.5 text-[9px] font-mono rounded border ${color}`}>
      {tier}
    </span>
  );
}

function StatCard({ label, value, accent = "default" }) {
  const colors = {
    emerald: "text-accent-emerald",
    blue: "text-accent-blue",
    amber: "text-accent-amber",
    default: "text-text-primary",
  };
  return (
    <div className="bg-bg-card border border-border rounded-md p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className={`text-xl font-semibold mt-0.5 font-mono ${colors[accent]}`}>{value}</div>
    </div>
  );
}

function Input({ label, placeholder }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase text-text-muted mb-1">{label}</div>
      <input
        type="text"
        placeholder={placeholder}
        className="w-full bg-bg-card border border-border rounded px-3 py-1.5 text-text-primary placeholder-text-muted font-mono"
      />
    </div>
  );
}

function Modal({ children, onClose }) {
  return (
    <div
      className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-6"
      onClick={onClose}
    >
      <div
        className="bg-bg-panel border border-border rounded-lg p-6 max-w-md w-full"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
