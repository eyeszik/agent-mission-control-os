"use client";

import { useState } from 'react';
import { createAgencyRun } from '../../lib/api/agency';
import { generateIdempotencyKey } from '../../lib/utils/idempotency';
import { useApprovalStore } from '../../lib/stores/approvalStore';
import { useArtifactStore } from '../../lib/stores/artifactStore';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';
import { useDesignStore } from '../../lib/stores/designStore';

export function CommandInputPanel() {
  const [brandName, setBrandName] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [businessIdea, setBusinessIdea] = useState('');
  const [offerSummary, setOfferSummary] = useState('');
  const [productType, setProductType] = useState('app');
  const [workflowIdea, setWorkflowIdea] = useState('');
  const [brandStyleNotes, setBrandStyleNotes] = useState('');
  const [goals, setGoals] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setActiveRun = useRunStore((state) => state.setActiveRun);
  const upsertRun = useRunStore((state) => state.upsertRun);
  const addArtifact = useArtifactStore((state) => state.addArtifact);
  const upsertApproval = useApprovalStore((state) => state.upsertApproval);
  const updateNodeStatus = useNodeStatusStore((state) => state.updateNodeStatus);
  // Stable references: these only change when a direction is attached or detached.
  const styleSelection = useDesignStore((state) => state.attached?.selection ?? null);
  const styleLabel = useDesignStore((state) => state.attached?.label ?? null);
  const styleCompositionId = useDesignStore((state) => state.attached?.compositionId ?? null);
  const detachStyle = useDesignStore((state) => state.detach);

  const handleLaunchCampaign = async () => {
    if (!brandName.trim() || !targetAudience.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const run = await createAgencyRun(
        'proj_1',
        {
          brand_name: brandName.trim(),
          business_idea: businessIdea.trim() || null,
          offer_summary: offerSummary.trim() || null,
          product_type: productType.trim() || null,
          target_audience: targetAudience.trim(),
          workflow_idea: workflowIdea.trim() || null,
          goals: goals.split(',').map((goal) => goal.trim()).filter(Boolean),
          differentiators: [],
          brand_style_notes: brandStyleNotes.split(',').map((note) => note.trim()).filter(Boolean),
          channels: [],
          constraints: [],
          style_selection: styleSelection,
        },
        generateIdempotencyKey()
      );

      upsertRun({
        id: run.run_id,
        tenant_id: 'tenant_1',
        project_id: run.project_id ?? 'proj_1',
        status: run.status === 'needs_approval' ? 'needs_approval' : 'running',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        metadata: { proof: run.proof ?? null },
      });
      setActiveRun(run.run_id);
      for (const stage of run.stages ?? []) {
        if (stage === 'delivery') break;
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
      if (run.pending_approval) upsertApproval(run.pending_approval);

      setBrandName('');
      setTargetAudience('');
      setBusinessIdea('');
      setOfferSummary('');
      setProductType('app');
      setWorkflowIdea('');
      setBrandStyleNotes('');
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
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Campaign Terminal</span>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400">AGENCY</span>
      </div>

      {error && (
        <div role="alert" className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</div>
      )}

      <div className="flex flex-col gap-2">
        <label className="text-xs text-zinc-500" htmlFor="brand-name">Brand name</label>
        <input id="brand-name" value={brandName} onChange={(event) => setBrandName(event.target.value)} disabled={loading} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="business-idea">Business idea</label>
        <textarea id="business-idea" value={businessIdea} onChange={(event) => setBusinessIdea(event.target.value)} disabled={loading} rows={3} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="offer-summary">Offer summary</label>
        <textarea id="offer-summary" value={offerSummary} onChange={(event) => setOfferSummary(event.target.value)} disabled={loading} rows={2} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="target-audience">Target audience</label>
        <input id="target-audience" value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} disabled={loading} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="product-type">Product type</label>
        <input id="product-type" value={productType} onChange={(event) => setProductType(event.target.value)} disabled={loading} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="workflow-idea">Workflow / automation idea</label>
        <textarea id="workflow-idea" value={workflowIdea} onChange={(event) => setWorkflowIdea(event.target.value)} disabled={loading} rows={2} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="campaign-goals">Goals <span className="text-zinc-600">(comma separated, optional)</span></label>
        <input id="campaign-goals" value={goals} onChange={(event) => setGoals(event.target.value)} disabled={loading} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        <label className="text-xs text-zinc-500" htmlFor="brand-style-notes">Brand style notes <span className="text-zinc-600">(comma separated)</span></label>
        <input id="brand-style-notes" value={brandStyleNotes} onChange={(event) => setBrandStyleNotes(event.target.value)} disabled={loading} className="w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60" />

        {styleLabel && (
          <div className="flex items-center justify-between gap-2 text-xs bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2">
            <span className="text-emerald-300 min-w-0 truncate" title={styleCompositionId ?? undefined}>
              Style direction: {styleLabel}
            </span>
            <button
              type="button"
              onClick={detachStyle}
              disabled={loading}
              className="shrink-0 text-[11px] text-zinc-400 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 rounded"
            >
              Detach
            </button>
          </div>
        )}

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={handleLaunchCampaign}
            disabled={loading || !brandName.trim() || !targetAudience.trim()}
            className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 transition-colors"
          >
            {loading ? 'Running pipeline…' : 'Compile Idea Workspace'}
          </button>
        </div>
      </div>
    </div>
  );
}
