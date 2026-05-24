"use client";

import { useState } from 'react';
import { createRun } from '../../lib/api/runs';
import { generateIdempotencyKey } from '../../lib/utils/idempotency';
import { useRunStore } from '../../lib/stores/runStore';

export function CommandInputPanel() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const setActiveRun = useRunStore((state) => state.setActiveRun);

  const handleExecute = async () => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      const run = await createRun('proj_1', 'tenant_1', { command: input }, generateIdempotencyKey());
      setActiveRun(run.id);
      setInput('');
    } catch (err) {
      console.error('Failed to create run', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Terminal</span>
      </div>
      <div className="relative">
        <textarea 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
          placeholder="Enter directive..."
          className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-3 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors resize-none h-24"
        />
        {/* Typewriter cursor style when focused */}
        {loading && <div className="absolute top-4 left-3 w-1.5 h-4 bg-emerald-500/80 animate-pulse" />}
      </div>
      <div className="flex justify-end">
        <button 
          onClick={handleExecute}
          disabled={loading || !input.trim()} 
          className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white transition-colors"
        >
          {loading ? 'Executing...' : 'Execute'}
        </button>
      </div>
    </div>
  );
}
