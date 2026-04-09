"""
Pre-compute 5 AI Agent responses using Claude with REAL kols.json + graph.json data.

Output: kol-intelligence-engine/src/data/agent_responses.json

The frontend Agent.jsx reads this for demo mode. Live mode (user provides API key)
re-generates on demand.
"""

import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AsyncAnthropic

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GRAPH_FILE = ROOT / "kol-intelligence-engine" / "src" / "data" / "graph.json"
KOLS_FILE = ROOT / "kol-intelligence-engine" / "src" / "data" / "kols.json"
OUTPUT = ROOT / "kol-intelligence-engine" / "src" / "data" / "agent_responses.json"

# 5 preset prompts matching the Agent.jsx UI
PROMPTS = [
    "帮我找 5 个适合推广 AI Agent 项目的中文 KOL",
    "Generate an outreach email for @starzq about our AI infrastructure project",
    "Which KOLs have the highest cross-circle influence in the graph?",
    "推荐一个 $5,000 预算的 campaign 方案，target 中文 AI 圈",
    "Compare the Virtuals circle (C1) vs Biteye circle (C2) for a product launch",
]


def build_context() -> str:
    """Build a compact KOL context string for Claude."""
    graph = json.loads(GRAPH_FILE.read_text())
    kols = json.loads(KOLS_FILE.read_text())

    meta = graph["metadata"]
    cluster_summary = meta.get("cluster_summary", [])
    top_pr = meta.get("top_pagerank", [])
    top_bc = meta.get("top_betweenness", [])

    # Top 20 KOLs by overall_score
    top_kols = sorted(
        [k for k in kols["kols"] if k.get("overall_score")],
        key=lambda k: -(k.get("overall_score") or 0),
    )[:25]

    ctx = f"""# Chinese AI+Crypto KOL Network Database

## Database overview
- Total KOLs: {len(kols['kols'])}
- In network graph: {meta.get('total_nodes')} nodes, {meta.get('total_edges')} edges
- 3 ground-truth circles:
  * C1 (Virtuals Chinese Builders): 6 anchors
  * C2 (XHunt/Biteye Web3 Media): 6 anchors (colinwu, phyrexni are bridges to C3)
  * C3 (華語主流加密分析圈): 6 anchors
- Edge tiers: T1={meta['edge_breakdown']['tier_1_mutual']} mutual, T2={meta['edge_breakdown']['tier_2a_oneway_anchor'] + meta['edge_breakdown']['tier_2b_anchor_to_hub']} one-way, T3={meta['edge_breakdown']['tier_3_cofollow_inferred']} inferred
- Total API cost so far: ${meta['input_data']['cost_usd_total']}

## Clusters (Louvain communities)
"""
    for c in cluster_summary:
        ctx += f"- Cluster {c['cluster_id']}: {c['size']} members, spans {','.join(c.get('circles_touched', [])) or '—'}, entry={c.get('recommended_entry_point')}, bridges={','.join(c.get('bridge_nodes', []))}\n"

    ctx += "\n## Top 10 by PageRank (network centrality)\n"
    for p in top_pr[:10]:
        node = next((n for n in graph["nodes"] if n["id"] == p["id"]), None)
        if node:
            ctx += f"- @{p['id']} (PR {p['pagerank']}, cluster #{node.get('cluster')}, circles {','.join(node.get('circles', [])) or 'hub'})\n"

    ctx += "\n## Top 10 by Betweenness (cross-cluster bridges)\n"
    for p in top_bc[:10]:
        ctx += f"- @{p['id']} (BC {p['betweenness']})\n"

    ctx += "\n## Top 25 KOLs by overall_score\n"
    for k in top_kols:
        c = k.get("cooperability", {}) or {}
        handle = k.get("id") or k.get("username") or "?"
        followers = k.get("followers_count") or 0
        ctx += (
            f"- @{handle} ({k.get('name', '—')}) "
            f"score={k.get('overall_score')} "
            f"[{k.get('tier')}/{k.get('language')}/{k.get('sector')}] "
            f"followers={followers:,} "
            f"circles={','.join(k.get('circles', [])) or 'hub'} "
            f"contactable={c.get('is_contactable', False)}\n"
            f"  bio: {(k.get('bio') or '')[:120]}\n"
        )
    return ctx


async def generate_response(client: AsyncAnthropic, prompt: str, context: str) -> dict:
    system = (
        "You are an expert crypto marketing strategist analyzing a KOL database for an AI+Crypto marketing agency. "
        "You have access to a detailed Chinese AI+Crypto KOL network with real data (scores, cluster membership, "
        "centrality metrics, cooperability info). When asked for recommendations, cite SPECIFIC KOLs from the "
        "provided data — never fabricate. When asked for strategy, ground it in the actual network structure "
        "(e.g., 'reach out to @lanhubiji first because of her #1 PageRank and C1↔C3 bridge role'). "
        "Respond in the same language as the user's prompt (Chinese or English). "
        "Be concrete, data-backed, and actionable. Format with clear headings and bullets."
    )
    user = f"{context}\n\n---\n\nUser question: {prompt}\n\nRespond in 250-450 words. Use markdown formatting with headings."

    response = await client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return {
        "prompt": prompt,
        "response": response.content[0].text,
        "model": "claude-sonnet-4-5",
        "tokens_in": response.usage.input_tokens,
        "tokens_out": response.usage.output_tokens,
    }


async def main():
    print("=" * 72)
    print("Pre-compute AI Agent responses (Claude Sonnet 4.5 + real KOL data)")
    print("=" * 72)

    context = build_context()
    print(f"\nContext size: {len(context)} chars")
    print(f"\nGenerating {len(PROMPTS)} responses...")

    client = AsyncAnthropic()

    # Run in parallel (5 requests)
    tasks = [generate_response(client, p, context) for p in PROMPTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    good = []
    for p, r in zip(PROMPTS, results):
        if isinstance(r, Exception):
            print(f"  ✗ {p[:40]}... — {r}")
            good.append({
                "prompt": p,
                "response": f"Error generating response: {r}",
                "error": True,
            })
        else:
            print(
                f"  ✓ {p[:50]}... ({r['tokens_in']}→{r['tokens_out']} tokens)"
            )
            good.append(r)

    total_in = sum(r.get("tokens_in", 0) for r in good if isinstance(r, dict))
    total_out = sum(r.get("tokens_out", 0) for r in good if isinstance(r, dict))
    # Sonnet 4.5 pricing: $3/M input, $15/M output
    cost = (total_in / 1_000_000) * 3 + (total_out / 1_000_000) * 15

    output_doc = {
        "metadata": {
            "generated_at": "2026-04-08",
            "model": "claude-sonnet-4-5",
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "estimated_cost_usd": round(cost, 3),
            "data_sources": ["graph.json", "kols.json"],
            "prompt_count": len(PROMPTS),
        },
        "responses": good,
    }

    OUTPUT.write_text(json.dumps(output_doc, indent=2, ensure_ascii=False))
    print(f"\n✅ Saved: {OUTPUT}")
    print(f"   Total cost: ~${cost:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
