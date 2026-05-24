export function WorkflowMapPanel() {
  return (
    <div className="flex-1 flex items-center justify-center p-8 relative">
      {/* Node Skeletons */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-20">
        {/* Placeholder SVG Graph */}
        <svg className="w-full h-full" viewBox="0 0 400 200">
          <path d="M 100 100 L 200 100 L 300 100" stroke="currentColor" strokeWidth="2" strokeDasharray="4 4" fill="none" />
          <circle cx="100" cy="100" r="16" fill="currentColor" />
          <circle cx="200" cy="100" r="16" fill="currentColor" />
          <circle cx="300" cy="100" r="16" fill="currentColor" />
        </svg>
      </div>
      <div className="text-center">
        <p className="text-sm text-zinc-500">Graph Idle</p>
        <p className="text-xs text-zinc-600 mt-1">Awaiting execution trace</p>
      </div>
    </div>
  );
}
