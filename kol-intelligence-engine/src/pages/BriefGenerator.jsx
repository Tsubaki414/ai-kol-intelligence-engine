import { useState } from "react";
import DemoModeBanner from "../components/DemoModeBanner.jsx";

const SAMPLE_BRIEF = {
  project: "Virtuals Protocol",
  campaign_title: "Autonomous AI Agents: Launch Campaign for 中文市场",
  objectives: [
    "建立 Virtuals Protocol 在中文 AI+Crypto 社区的心智定位",
    "驱动 1,500+ 新用户试用 Agent Creator",
    "获取 50+ 技术深度内容（threads, tutorials, 深度评测）",
  ],
  talking_points: [
    "Virtuals 是第一个让任何人都能 launch tradeable AI Agent 的协议",
    "Bonding curve 机制 + Base 链低 gas 让小额资金也能参与 agent economy",
    "中文创作者优势：通过 Virtuals 可以把内容 IP tokenize + monetize",
    "vs 传统 creator economy：真正的 ownership (token holding) + 持续分成",
  ],
  competitor_comparison: [
    { name: "ai16z / Eliza", angle: "社区驱动的开源 agent framework，vs Virtuals 的 launchpad 商业模式" },
    { name: "Bittensor", angle: "专注 decentralized ML training，vs Virtuals 专注 agent economy" },
  ],
  content_angles: [
    "深度技术：Virtuals 的 bonding curve 经济学（threaded by @DeFiTeddy2020）",
    "入门 tutorial：如何用 Virtuals 30 分钟创建你的第一个 AI Agent (by @sanbuphy)",
    "行业对比：Virtuals vs ai16z vs Bittensor — 三种 AI agent 路线（by @tychozzz）",
    "个人故事：我用 Virtuals 把我的 podcast content tokenize 的经历 (by @starzq)",
  ],
  recommended_kol_mix: {
    mega: ["@shawmakesmagic", "@FinanceYF5"],
    macro: ["@lanhubiji", "@starzq", "@defiteddy2020", "@biteyecn"],
    micro: ["@Rav_Hedda", "@0xzagen", "@iamyourchaos", "@sanbuphy"],
  },
  budget_split: {
    content_production: "40% ($6,000)",
    paid_kol_partnerships: "45% ($6,750)",
    community_amplification: "15% ($2,250)",
  },
  timeline: "2 weeks content production + 3 weeks publish + 1 week measurement = 6 weeks total",
  success_metrics: [
    "Reach: 500K+ unique impressions in 中文 crypto Twitter",
    "Engagement rate: >3.5% on sponsored threads",
    "Agent Creator sign-ups from campaign attribution: 1,500+",
    "Earned media: 5+ organic community-generated tutorials",
  ],
};

export default function BriefGenerator() {
  const [form, setForm] = useState({
    project: "",
    url: "",
    sector: "AI Agent",
    budget: "",
    audience: "",
  });
  const [generated, setGenerated] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleGenerate = () => {
    setLoading(true);
    setTimeout(() => {
      setGenerated(SAMPLE_BRIEF);
      setLoading(false);
    }, 1200);
  };

  return (
    <div className="h-full overflow-y-auto">
      <DemoModeBanner
        feature="automated project-brief generation"
        rationale="Clicking Generate returns a hardcoded sample — real version would stream Claude output from project URL + brand voice."
        effort="2 engineer-days"
      />
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <h1 className="text-lg font-semibold text-text-primary">AI Brief Generator</h1>
        <div className="text-xs text-text-muted font-mono mt-0.5">
          项目方输入信息 → Claude 自动生成 campaign brief · talking points · KOL 组合建议
        </div>
      </div>

      <div className="p-6 max-w-5xl">
        {/* Input form */}
        <div className="bg-bg-card border border-border rounded-lg p-5 mb-4">
          <h3 className="text-sm font-semibold text-text-primary mb-4">Project Input</h3>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <Input
              label="Project Name"
              value={form.project}
              onChange={(v) => setForm({ ...form, project: v })}
              placeholder="Virtuals Protocol"
            />
            <Input
              label="Project URL"
              value={form.url}
              onChange={(v) => setForm({ ...form, url: v })}
              placeholder="https://virtuals.io"
            />
            <Select
              label="Sector"
              value={form.sector}
              onChange={(v) => setForm({ ...form, sector: v })}
              options={[
                "AI Agent",
                "AI Infra",
                "AI + DeFi",
                "AI + Gaming",
                "AI Dev Tools",
                "AI Research",
              ]}
            />
            <Input
              label="Budget (USD)"
              value={form.budget}
              onChange={(v) => setForm({ ...form, budget: v })}
              placeholder="$15,000"
            />
            <div className="col-span-2">
              <Input
                label="Target Audience"
                value={form.audience}
                onChange={(v) => setForm({ ...form, audience: v })}
                placeholder="中文 AI Agent builders + early adopters"
              />
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              onClick={handleGenerate}
              disabled={loading}
              className="px-5 py-2 bg-accent-emerald/15 border border-accent-emerald rounded-md text-xs font-mono text-accent-emerald hover:bg-accent-emerald/25 disabled:opacity-50"
            >
              {loading ? "Generating with Claude..." : "Generate Brief"}
            </button>
          </div>
        </div>

        {/* Output */}
        {generated && (
          <div className="bg-bg-card border border-border rounded-lg p-6 space-y-5">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-accent-emerald font-mono">
                Generated Campaign Brief
              </div>
              <h2 className="text-lg font-semibold text-text-primary mt-1">
                {generated.campaign_title}
              </h2>
              <div className="text-xs text-text-muted font-mono mt-0.5">
                for {generated.project}
              </div>
            </div>

            <Section title="Objectives">
              <ul className="space-y-1 text-xs text-text-secondary">
                {generated.objectives.map((o, i) => (
                  <li key={i}>
                    <span className="text-accent-blue mr-2">{i + 1}.</span>
                    {o}
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Talking Points">
              <ul className="space-y-1 text-xs text-text-secondary">
                {generated.talking_points.map((t, i) => (
                  <li key={i}>
                    <span className="text-accent-emerald mr-2">✓</span>
                    {t}
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Competitor Comparison">
              <div className="space-y-2">
                {generated.competitor_comparison.map((c, i) => (
                  <div key={i} className="text-xs">
                    <span className="text-accent-amber font-mono">{c.name}:</span>{" "}
                    <span className="text-text-secondary">{c.angle}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Content Angles">
              <ol className="space-y-1 text-xs text-text-secondary font-mono">
                {generated.content_angles.map((a, i) => (
                  <li key={i}>
                    <span className="text-text-muted mr-1">{i + 1}.</span> {a}
                  </li>
                ))}
              </ol>
            </Section>

            <Section title="Recommended KOL Mix">
              <div className="grid grid-cols-3 gap-3">
                <KolBucket label="Mega (100K+)" handles={generated.recommended_kol_mix.mega} color="purple" />
                <KolBucket label="Macro (10K-100K)" handles={generated.recommended_kol_mix.macro} color="blue" />
                <KolBucket label="Micro (1K-10K)" handles={generated.recommended_kol_mix.micro} color="emerald" />
              </div>
            </Section>

            <Section title="Budget Split">
              <div className="space-y-1 text-xs text-text-secondary font-mono">
                {Object.entries(generated.budget_split).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span>{k.replace(/_/g, " ")}</span>
                    <span className="text-accent-blue">{v}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Timeline">
              <div className="text-xs text-text-secondary">{generated.timeline}</div>
            </Section>

            <Section title="Success Metrics">
              <ul className="space-y-1 text-xs text-text-secondary">
                {generated.success_metrics.map((m, i) => (
                  <li key={i}>
                    <span className="text-accent-emerald mr-2">→</span>
                    {m}
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Input({ label, value, onChange, placeholder }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase text-text-muted mb-1">{label}</div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-bg-panel border border-border rounded px-3 py-1.5 text-text-primary placeholder-text-muted font-mono focus:outline-none focus:border-accent-blue"
      />
    </div>
  );
}

function Select({ label, value, onChange, options }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase text-text-muted mb-1">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-bg-panel border border-border rounded px-3 py-1.5 text-text-primary font-mono focus:outline-none focus:border-accent-blue"
      >
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono mb-2">
        {title}
      </div>
      {children}
    </div>
  );
}

function KolBucket({ label, handles, color }) {
  const colors = {
    purple: "border-accent-purple/30 text-accent-purple",
    blue: "border-accent-blue/30 text-accent-blue",
    emerald: "border-accent-emerald/30 text-accent-emerald",
  };
  return (
    <div className={`border rounded-md p-3 ${colors[color]}`}>
      <div className="text-[9px] uppercase tracking-widest mb-2">{label}</div>
      <div className="space-y-0.5 text-[11px] font-mono text-text-secondary">
        {handles.map((h) => (
          <div key={h}>{h}</div>
        ))}
      </div>
    </div>
  );
}
