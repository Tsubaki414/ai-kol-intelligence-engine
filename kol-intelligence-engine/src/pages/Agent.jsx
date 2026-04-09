import { useState, useEffect, useRef } from "react";
import agentData from "../data/agent_responses.json";

const LS_KEY = "kol_engine_anthropic_key";

export default function Agent() {
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [displayedText, setDisplayedText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [liveMode, setLiveMode] = useState(false);
  const [liveResponse, setLiveResponse] = useState("");
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveError, setLiveError] = useState("");
  const typingRef = useRef(null);

  const presets = agentData.responses || [];

  // Load saved key from localStorage
  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY);
    if (saved) {
      setApiKey(saved);
      setLiveMode(true);
    }
  }, []);

  // Typing animation for preset responses
  useEffect(() => {
    if (selectedIdx === null) {
      setDisplayedText("");
      return;
    }
    const fullText = presets[selectedIdx]?.response || "";
    setDisplayedText("");
    setIsStreaming(true);
    let i = 0;
    const chunkSize = 3;
    const interval = setInterval(() => {
      if (i >= fullText.length) {
        clearInterval(interval);
        setIsStreaming(false);
        return;
      }
      setDisplayedText(fullText.slice(0, i + chunkSize));
      i += chunkSize;
    }, 8);
    typingRef.current = interval;
    return () => clearInterval(interval);
  }, [selectedIdx]);

  const saveKey = () => {
    if (apiKey && apiKey.startsWith("sk-ant-")) {
      localStorage.setItem(LS_KEY, apiKey);
      setLiveMode(true);
      setLiveError("");
    } else {
      setLiveError("Key should start with sk-ant-");
    }
  };

  const clearKey = () => {
    localStorage.removeItem(LS_KEY);
    setApiKey("");
    setLiveMode(false);
    setLiveResponse("");
  };

  const handleLiveQuery = async () => {
    if (!customPrompt.trim()) return;
    if (!liveMode || !apiKey) {
      setLiveError("Enter your Anthropic API key first, or click a preset question.");
      return;
    }
    setLiveLoading(true);
    setLiveError("");
    setLiveResponse("");
    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 1500,
          system:
            "You are a crypto marketing strategist analyzing the Chinese AI+Crypto KOL network. " +
            "Ground answers in specific KOL handles when possible. Be concrete and actionable.",
          messages: [{ role: "user", content: customPrompt }],
        }),
      });
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Claude API ${response.status}: ${errText.slice(0, 200)}`);
      }
      const data = await response.json();
      setLiveResponse(data.content?.[0]?.text || "(empty response)");
    } catch (e) {
      setLiveError(e.message || "Request failed");
    } finally {
      setLiveLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Live-mode warning — only rendered when the user has saved their
          own API key, so we're actually spending their quota on each query. */}
      {liveMode && (
        <div className="border-b border-accent-emerald/40 bg-accent-emerald/10 px-6 py-2 flex items-center gap-3">
          <div className="text-accent-emerald text-sm leading-none">●</div>
          <div className="flex-1 text-[11px] font-mono text-text-secondary leading-relaxed">
            <span className="text-accent-emerald font-semibold">LIVE MODE.</span>{" "}
            Custom queries will spend tokens on your Anthropic account until you clear the key.
            Preset queries still return cached responses for free.
          </div>
          <button
            onClick={clearKey}
            className="text-[10px] font-mono text-accent-rose hover:underline whitespace-nowrap"
          >
            clear key →
          </button>
        </div>
      )}

      {/* Header */}
      <div className="border-b border-border px-6 py-4 bg-bg-panel">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-lg font-semibold text-text-primary">AI Agent</h1>
          <span
            className={`px-2 py-0.5 text-[10px] font-mono rounded border ${
              liveMode
                ? "bg-accent-emerald/15 text-accent-emerald border-accent-emerald/30"
                : "bg-accent-amber/15 text-accent-amber border-accent-amber/30"
            }`}
          >
            {liveMode ? "🟢 LIVE (your key)" : "🎭 DEMO MODE (preset responses)"}
          </span>
        </div>
        <div className="text-xs text-text-muted font-mono">
          Claude Sonnet 4.5 grounded on real KOL database · {presets.length} preset queries + live mode
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 max-w-4xl">
        {/* API key configuration */}
        <div className="mb-5 bg-bg-card border border-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-semibold text-text-primary">🔑 API Key (optional)</div>
            {liveMode && (
              <button
                onClick={clearKey}
                className="text-[10px] text-accent-rose hover:underline font-mono"
              >
                clear key
              </button>
            )}
          </div>
          <p className="text-[11px] text-text-muted mb-3 leading-relaxed">
            Demo mode shows 5 pre-computed responses (zero cost). Paste your own{" "}
            <a
              href="https://console.anthropic.com/settings/keys"
              target="_blank"
              rel="noreferrer"
              className="text-accent-blue hover:underline"
            >
              Anthropic API key
            </a>{" "}
            to unlock live queries. Key stays in your browser localStorage, never sent anywhere except
            api.anthropic.com directly.
          </p>
          <div className="flex gap-2">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-ant-api03-..."
              className="flex-1 bg-bg-panel border border-border rounded px-3 py-1.5 text-xs text-text-primary placeholder-text-muted font-mono focus:outline-none focus:border-accent-emerald"
            />
            <button
              onClick={saveKey}
              className="px-3 py-1.5 bg-accent-emerald/15 border border-accent-emerald rounded text-xs font-mono text-accent-emerald hover:bg-accent-emerald/25"
            >
              save → live mode
            </button>
          </div>
          {liveError && (
            <div className="mt-2 text-[11px] text-accent-rose font-mono">{liveError}</div>
          )}
        </div>

        {/* Preset prompts */}
        <div className="mb-5">
          <div className="text-[10px] uppercase tracking-widest text-text-muted mb-2 font-mono">
            Preset queries (instant pre-computed responses)
          </div>
          <div className="space-y-2">
            {presets.map((p, i) => (
              <button
                key={i}
                onClick={() => setSelectedIdx(i)}
                className={`block w-full text-left px-4 py-3 rounded-md text-xs transition-colors ${
                  selectedIdx === i
                    ? "bg-bg-hover border border-accent-blue text-text-primary"
                    : "bg-bg-card border border-border text-text-secondary hover:border-accent-blue/50"
                }`}
              >
                <span className="text-accent-blue mr-2">{i + 1}.</span>
                {p.prompt}
              </button>
            ))}
          </div>
        </div>

        {/* Custom prompt input */}
        <div className="mb-5 border-t border-border pt-5">
          <div className="text-[10px] uppercase tracking-widest text-text-muted mb-2 font-mono">
            Or ask your own question {!liveMode && "(requires API key above)"}
          </div>
          <textarea
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            placeholder="e.g., Who are the top 3 AI Agent KOLs in Taiwan?"
            rows={3}
            className="w-full bg-bg-card border border-border rounded-md px-3 py-2 text-xs text-text-primary placeholder-text-muted font-mono focus:outline-none focus:border-accent-blue"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              onClick={handleLiveQuery}
              disabled={liveLoading || !customPrompt.trim() || !liveMode}
              className="px-4 py-1.5 bg-accent-blue/15 border border-accent-blue rounded text-xs font-mono text-accent-blue hover:bg-accent-blue/25 disabled:opacity-50"
            >
              {liveLoading ? "Thinking..." : "Send (live Claude)"}
            </button>
          </div>
        </div>

        {/* Display response */}
        {(selectedIdx !== null || liveResponse || liveError) && (
          <div className="bg-bg-card border border-border rounded-lg p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[10px] uppercase tracking-widest text-text-muted font-mono">
                {liveResponse ? "Live Response" : `Preset #${selectedIdx + 1}`}
              </div>
              {isStreaming && (
                <div className="text-[10px] text-accent-blue font-mono animate-pulse">
                  ▊ streaming...
                </div>
              )}
            </div>
            {liveError && !liveResponse && (
              <div className="text-xs text-accent-rose font-mono whitespace-pre-wrap">
                {liveError}
              </div>
            )}
            {liveResponse && (
              <div className="text-xs text-text-secondary whitespace-pre-wrap leading-relaxed">
                {liveResponse}
              </div>
            )}
            {selectedIdx !== null && !liveResponse && (
              <div className="text-xs text-text-secondary whitespace-pre-wrap leading-relaxed">
                {displayedText}
                {isStreaming && <span className="text-accent-blue">▊</span>}
              </div>
            )}
            {selectedIdx !== null && !isStreaming && (
              <div className="mt-4 pt-3 border-t border-border text-[10px] font-mono text-text-muted flex justify-between">
                <span>
                  Model: {presets[selectedIdx]?.model || "claude-sonnet-4-5"}
                </span>
                <span>
                  {presets[selectedIdx]?.tokens_in ?? 0} →{" "}
                  {presets[selectedIdx]?.tokens_out ?? 0} tokens
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
