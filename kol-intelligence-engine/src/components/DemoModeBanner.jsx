// Prominent banner for the 5 "Demo Mode" pages (Guilds, Brief Generator,
// Campaign Simulator, Lighthouse Integration, On-chain Verification).
//
// The point is to signal, before the user scrolls a single pixel, that
// everything on the page is a design mockup — not a real integration.
// This is intentional: the 5 pages are feature wireframes showing what
// the product could do, not what it currently does.

export default function DemoModeBanner({ feature, rationale, effort }) {
  return (
    <div className="border-b border-accent-amber/40 bg-accent-amber/10 px-6 py-3">
      <div className="flex items-start gap-3 max-w-6xl">
        <div className="text-accent-amber text-lg leading-none mt-0.5">◐</div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-mono font-semibold text-accent-amber uppercase tracking-wider">
            Wireframe preview · Not a live feature
          </div>
          <div className="text-[11px] text-text-secondary font-mono mt-1 leading-relaxed">
            This page is a <span className="text-accent-amber">design mockup</span> showing what{" "}
            <span className="text-text-primary">{feature}</span> would look like once built.
            {rationale && <> {rationale}</>}
            {effort && (
              <>
                {" "}
                <span className="text-text-muted">· Production integration: ~{effort}.</span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
