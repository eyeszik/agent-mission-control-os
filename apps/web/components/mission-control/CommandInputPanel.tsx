"use client";

import { useState } from 'react';
import { createRun } from '../../lib/api/runs';
import { createAgencyRun } from '../../lib/api/agency';
import { generateIdempotencyKey } from '../../lib/utils/idempotency';
import { useRunStore } from '../../lib/stores/runStore';
import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';

type Mode = 'general' | 'agency';

export function CommandInputPanel() {
  const [mode, setMode] = useState<Mode>('agency');
  const [input, setInput] = useState('');
  const [brandName, setBrandName] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [goals, setGoals] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setActiveRun = useRunStore((state) => state.setActiveRun);
  const addArtifact = useArtifactStore((state) => state.addArtifact);
  const upsertApproval = useApprovalStore((state) => state.upsertApproval);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);

  const handleExecuteGeneral = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const run = await createRun('proj_1', 'tenant_1', { command: input }, generateIdempotencyKey());
      setActiveRun(run.id);
      setInput('');
    } catch (err) {
      console.error('Failed to create run', err);
      setError(err instanceof Error ? err.message : 'Failed to create run');
    } finally {
      setLoading(false);
    }
  };

  const handleLaunchCampaign = async () => {
    if (!brandName.trim() || !targetAudience.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const run = await createAgencyRun(
        'tenant_1',
        'proj_1',
        {
          brand_name: brandName.trim(),
          target_audience: targetAudience.trim(),
          goals: goals.split(',').map((g) => g.trim()).filter(Boolean),
          channels: [],
          constraints: [],
        },
        generateIdempotencyKey()
      );

      setActiveRun(run.run_id);

      // The agency pipeline runs synchronously server-side up to the HITL
      // gate (no incremental SSE events are emitted per node yet), so mark
      // everything through hitl_gate as completed based on the response we
      // actually got back rather than leaving the map inert or faking a
      // live animation the backend doesn't produce.
      const stages = run.stages ?? [];
      const preGateStages = stages.slice(0, stages.indexOf('delivery'));
      for (const stage of preGateStages) {
        updateNodeStatus(run.run_id, stage, 'completed');
      }

      if (run.campaign_package) {
        addArtifact(run.run_id, {
          id: crypto.randomUUID(),
          run_id: run.run_id,
          node_id: 'campaign_assembly',
          type: 'spec',
          content: JSON.stringify(run.campaign_package, null, 2),
          created_at: new Date().toISOString(),
        });
      }
      if (run.pending_approval) {
        upsertApproval(run.pending_approval);
      }

      setBrandName('');
      setTargetAudience('');
      setGoals('');
    } catch (err) {
      console.error('Failed to launch campaign', err);
      setError(err instanceof Error ? err.message : 'Failed to launch campaign');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Terminal</span>
        <div className="flex gap-1 text-[10px] font-mono">
          <button
            onClick={() => setMode('agency')}
            className={`px-2 py-0.5 rounded ${mode === 'agency' ? 'bg-emerald-500/20 text-emerald-400' : 'text-zinc-600 hover:text-zinc-400'}`}
          >
            CAMPAIGN
          </button>
          <button
            onClick={() => setMode('general')}
            className={`px-2 py-0.5 rounded ${mode === 'general' ? 'bg-emerald-500/20 text-emerald-400' : 'text-zinc-600 hover:text-zinc-400'}`}
          >
            GENERAL
          </button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</div>
      )}

      {mode === 'agency' ? (
        <div className="flex flex-col gap-2">
          <input
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            disabled={loading}
            placeholder="Brand name"
            className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors"
          />
          <input
            value={targetAudience}
            onChange={(e) => setTargetAudience(e.target.value)}
            disabled={loading}
            placeholder="Target audience"
            className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors"
          />
          <input
            value={goals}
            onChange={(e) => setGoals(e.target.value)}
            disabled={loading}
            placeholder="Goals (comma separated, optional)"
            className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors"
          />
          <div className="flex justify-end">
            <button
              onClick={handleLaunchCampaign}
              disabled={loading || !brandName.trim() || !targetAudience.trim()}
              className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white transition-colors"
            >
              {loading ? 'Running pipeline…' : 'Launch Campaign'}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              placeholder="Enter directive..."
              className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-3 text-sm text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 transition-colors resize-none h-24"
            />
            {loading && <div className="absolute top-4 left-3 w-1.5 h-4 bg-emerald-500/80 animate-pulse" />}
          </div>
          <div className="flex justify-end">
            <button
              onClick={handleExecuteGeneral}
              disabled={loading || !input.trim()}
              className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white transition-colors"
            >
              {loading ? 'Executing...' : 'Execute'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
