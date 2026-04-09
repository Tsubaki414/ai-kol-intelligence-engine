import { useState } from "react";

// Mock wallet data for one example KOL (demo)
const SAMPLE = {
  kol: {
    handle: "@brucexu_eth",
    name: "Bruce Xu",
    wallet: "0x1B89...F92c",
    chain: "Ethereum",
    verified_on: "2026-04-05",
  },
  holdings: [
    { token: "ETH", amount: "12.4", usd: 34_200, promoted_recently: false },
    { token: "VIRTUAL", amount: "4,820", usd: 9_640, promoted_recently: true },
    { token: "AI16Z", amount: "15,000", usd: 6_750, promoted_recently: true },
    { token: "TAO", amount: "8.2", usd: 3_100, promoted_recently: true },
    { token: "FET", amount: "1,200", usd: 1_056, promoted_recently: false },
    { token: "USDC", amount: "5,200", usd: 5_200, promoted_recently: false },
  ],
  recent_activity: [
    { date: "2026-04-06", action: "Bought 200 VIRTUAL", value: "$440", type: "trade" },
    {
      date: "2026-04-04",
      action: "Voted on LXDAO proposal #47",
      value: "—",
      type: "governance",
    },
    {
      date: "2026-04-01",
      action: "Staked 5,000 AI16Z in Eliza validator",
      value: "$2,250",
      type: "staking",
    },
    {
      date: "2026-03-28",
      action: "Swapped ETH → VIRTUAL via Aerodrome",
      value: "$1,200",
      type: "trade",
    },
    {
      date: "2026-03-22",
      action: "Provided LP to VIRTUAL/ETH pool",
      value: "$3,400",
      type: "liquidity",
    },
  ],
  alignment: {
    tokens_promoted: ["VIRTUAL", "AI16Z", "TAO", "RENDER"],
    tokens_held: ["VIRTUAL", "AI16Z", "TAO", "FET"],
    aligned_count: 3,
    promoted_count: 4,
    score: 75, // 3/4 tokens held = 75%
  },
  protocols: [
    { name: "Aerodrome", category: "DEX", interactions: 18 },
    { name: "Virtuals Protocol", category: "AI Agent", interactions: 12 },
    { name: "ElizaOS", category: "AI Agent", interactions: 9 },
    { name: "LXDAO", category: "Governance", interactions: 5 },
    { name: "Uniswap", category: "DEX", interactions: 22 },
  ],
};

export default function OnChainVerification() {
  const [selectedKol] = useState(SAMPLE);

  return (
    <div className="h-full overflow-y-auto">
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-text-primary">On-chain Verification</h1>
          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">
            🎨 DEMO MODE
          </span>
        </div>
        <div className="text-xs text-text-muted font-mono mt-0.5">
          Dual-Layer Layer 2: Wallet-Content Alignment · Activity Depth · Campaign Impact
        </div>
      </div>

      <div className="p-6 max-w-5xl space-y-4">
        {/* KOL header */}
        <div className="bg-bg-card border border-border rounded-lg p-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xl font-mono text-text-primary">
                {selectedKol.kol.handle}
              </div>
              <div className="text-sm text-text-secondary">{selectedKol.kol.name}</div>
              <div className="mt-3 space-y-1 text-xs text-text-muted font-mono">
                <div>
                  Wallet:{" "}
                  <span className="text-accent-blue">{selectedKol.kol.wallet}</span>
                </div>
                <div>Chain: {selectedKol.kol.chain}</div>
                <div>Verified on: {selectedKol.kol.verified_on}</div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono">
                Alignment Score
              </div>
              <div className="text-4xl font-semibold text-accent-emerald font-mono mt-1">
                {selectedKol.alignment.score}
              </div>
              <div className="text-[10px] text-text-muted font-mono">/ 100</div>
              <div className="text-[11px] text-text-secondary mt-1 font-mono">
                {selectedKol.alignment.aligned_count} / {selectedKol.alignment.promoted_count} promoted
                tokens held
              </div>
            </div>
          </div>
        </div>

        {/* Holdings vs promoted */}
        <div className="bg-bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            Holdings vs Promoted Tokens
          </h3>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-text-muted text-[10px] uppercase tracking-wider border-b border-border">
                <th className="py-2 text-left">Token</th>
                <th className="py-2 text-right">Amount</th>
                <th className="py-2 text-right">USD Value</th>
                <th className="py-2 text-center">Promoted in Tweets</th>
                <th className="py-2 text-center">Alignment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {selectedKol.holdings.map((h) => (
                <tr key={h.token}>
                  <td className="py-2 text-accent-blue">{h.token}</td>
                  <td className="py-2 text-right text-text-secondary">{h.amount}</td>
                  <td className="py-2 text-right text-text-secondary">
                    ${h.usd.toLocaleString()}
                  </td>
                  <td className="py-2 text-center">
                    {h.promoted_recently ? (
                      <span className="text-accent-emerald">● Yes</span>
                    ) : (
                      <span className="text-text-muted">— No</span>
                    )}
                  </td>
                  <td className="py-2 text-center">
                    {h.promoted_recently ? (
                      <span className="text-accent-emerald">✓ walks the talk</span>
                    ) : (
                      <span className="text-text-muted">not relevant</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Activity timeline */}
        <div className="bg-bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            Recent On-chain Activity
          </h3>
          <div className="space-y-2">
            {selectedKol.recent_activity.map((a, i) => (
              <div
                key={i}
                className="flex items-center gap-3 text-xs font-mono py-2 border-b border-border-subtle last:border-0"
              >
                <div className="text-text-muted w-24">{a.date}</div>
                <div className="flex-1 text-text-secondary">{a.action}</div>
                <div className="text-accent-blue">{a.value}</div>
                <div className="w-24 text-right">
                  <TypeTag type={a.type} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Protocols */}
        <div className="bg-bg-card border border-border rounded-lg p-5">
          <h3 className="text-sm font-semibold text-text-primary mb-3">
            Protocol Interactions ({selectedKol.protocols.length} unique)
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs font-mono">
            {selectedKol.protocols.map((p) => (
              <div
                key={p.name}
                className="bg-bg-hover border border-border rounded px-3 py-2 flex justify-between items-center"
              >
                <div>
                  <div className="text-text-primary">{p.name}</div>
                  <div className="text-[10px] text-text-muted">{p.category}</div>
                </div>
                <div className="text-accent-blue">{p.interactions}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="text-[11px] text-text-muted font-mono leading-relaxed bg-bg-hover border border-border rounded p-3">
          <span className="text-accent-amber">⚠️</span> Demo mode uses mocked on-chain data.
          Production version will use Etherscan + Arkham + Dune APIs for real-time Layer 2 scoring.
          Only KOLs with public wallets get this analysis; others show "On-chain data unavailable".
        </div>
      </div>
    </div>
  );
}

function TypeTag({ type }) {
  const map = {
    trade: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
    staking: "bg-accent-emerald/15 text-accent-emerald border-accent-emerald/30",
    liquidity: "bg-accent-purple/15 text-accent-purple border-accent-purple/30",
    governance: "bg-accent-amber/15 text-accent-amber border-accent-amber/30",
  };
  return (
    <span
      className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${
        map[type] || map.trade
      }`}
    >
      {type}
    </span>
  );
}
