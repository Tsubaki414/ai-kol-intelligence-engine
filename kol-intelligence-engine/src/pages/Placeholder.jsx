export default function Placeholder({ title, description, demoMode }) {
  return (
    <div className="h-full flex items-center justify-center p-10">
      <div className="max-w-xl text-center">
        {demoMode && (
          <div className="inline-block mb-4 px-3 py-1 bg-accent-amber/15 border border-accent-amber/40 rounded-full text-[11px] font-mono text-accent-amber">
            🎨 DEMO MODE
          </div>
        )}
        <h1 className="text-2xl font-semibold text-text-primary mb-3">{title}</h1>
        {description && (
          <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
        )}
        {demoMode && (
          <p className="mt-6 text-[11px] text-text-muted font-mono">
            Full UI to be implemented in Phase 3+. Frontend structure and navigation reserved.
          </p>
        )}
      </div>
    </div>
  );
}
