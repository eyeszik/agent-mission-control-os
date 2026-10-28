"use client";

import { useEffect, useMemo, useState } from 'react';
import type { AvicAssetView, AvicEditOp } from '@amc/shared';
import {
  compileAsset, editAsset, fetchPreview, getAsset, getAvicCapabilities, listAssets, recompileAsset, releaseLocal, requestApproval,
} from '../../lib/api/avic';
import { ServiceError } from '../../lib/api/client';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, Hash, KeyValue, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../agency/ui';

// Visual compiler (ACE x AVIC): brief -> native SVG -> local Chromium preview -> independent evaluation
// -> edits that conflict instead of overwriting -> human approval -> local release record.
// Every control calls a real authorized route or is disabled with its reason. Nothing publishes.

const RESULT_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  PASS: 'success', FAIL: 'danger', BLOCKED: 'warning', NOT_MEASURED: 'neutral',
};

function Preview({ view }: { view: AvicAssetView }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasPreview = Boolean(view.stages.preview);
  useEffect(() => {
    let disposed = false;
    let made: string | null = null;
    setUrl(null); setError(null);
    if (!hasPreview) return;
    fetchPreview(view.project_id, view.asset_id)
      .then(({ blob }) => { if (disposed) return; made = URL.createObjectURL(blob); setUrl(made); })
      .catch(() => { if (!disposed) setError('Preview unavailable.'); });
    return () => { disposed = true; if (made) URL.revokeObjectURL(made); };
  }, [view.project_id, view.asset_id, view.evaluation.png_sha256, hasPreview]);
  if (!hasPreview) return <Empty title="No preview">The renderer was unavailable when this asset was compiled.</Empty>;
  if (error) return <ErrorNote error={error} />;
  if (!url) return <Skeleton lines={6} />;
  // A PNG rendered by the server's isolated Chromium; the SVG source itself is never injected into the page.
  return <img src={url} alt={`Rendered preview of ${view.asset_id}: ${view.exact_text.join(' / ')}`}
    width={view.width} height={view.height} className="h-auto w-full max-w-md rounded-md border border-line" />;
}

function Overview({ view, onChanged }: { view: AvicAssetView; onChanged: () => void }) {
  const runner = useRunner();
  const stale = view.consistency.stale;
  return (
    <Card title={`Asset ${view.asset_id}`} id="avic-overview"
      description="The SVG is the source of truth; the PNG is a preview. Every stage is a Project OS artifact with its exact version.">
      <Preview view={view} />
      <KeyValue items={[
        ['Evaluation', <Badge key="e" label={view.evaluation.passed ? 'Passed' : 'Not passed'} tone={view.evaluation.passed ? 'success' : 'danger'} />],
        ['Stages', view.consistency.consistent ? 'Consistent with the scene'
          : <span key="s"><Badge label="Stale" tone="warning" /> {stale.join(', ')}: approval and release are blocked until recompiled</span>],
        ['Profile', `${view.style_profile} · ${view.output_profile} · ${view.width}×${view.height}`],
        ['Brand', `${view.brand_source}${view.brand_approved ? ' (approved)' : ' (projection, not approved)'}`],
        ['SVG', <Hash key="h" value={view.svg_sha256} />],
      ]} />
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={runner.busy || view.consistency.consistent} onClick={() => runner.run('Recompile', async () => {
          const r = await recompileAsset(view.project_id, view.asset_id);
          onChanged();
          return r.status === 'EVALUATED' ? 'Derived stages re-derived from the stored scene.' : `Recompile ${r.status}: ${(r.reasons ?? []).join('; ')}`;
        })}>Recompile from scene</Button>
        {view.consistency.consistent && <span className="text-sm text-fg" role="note">Nothing to recover: every stage matches the scene.</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Stage artifacts</caption>
        <thead><tr><th scope="col">Stage</th><th scope="col">Version</th><th scope="col">Hash</th></tr></thead>
        <tbody>
          {Object.entries(view.stages).map(([stage, s]) => (
            <tr key={stage} className="border-t border-line"><th scope="row" className="py-1 font-mono text-xs">{stage}</th>
              <td>v{s.version}</td><td><Hash value={s.content_hash} /></td></tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Evaluation({ view }: { view: AvicAssetView }) {
  const checks = [...view.evaluation.checks].sort((a, b) => Number(a.result === 'PASS') - Number(b.result === 'PASS'));
  // ⚡ Bolt: Use zero-allocation reduce instead of .filter().length
  const failing = checks.reduce((acc, c) => acc + (c.result !== 'PASS' ? 1 : 0), 0);
  return (
    <Card title="Independent evaluation" id="avic-evaluation"
      description={`${checks.length} checks read from the stored SVG and PNG bytes · ${failing} not passing · renderer ${view.evaluation.renderer ?? 'none'} ${view.evaluation.renderer_version ?? ''}`}>
      <ul className="flex flex-col gap-1">
        {checks.map((c) => (
          <li key={c.check} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge label={c.result} tone={RESULT_TONE[c.result]} /> <span className="font-mono text-xs">{c.check}</span>
            <span className="min-w-0 break-words text-fg">{c.detail}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Editor({ view, onChanged }: { view: AvicAssetView; onChanged: () => void }) {
  const runner = useRunner();
  const editable = useMemo(() => view.objects.filter((o) => o.operations.length > 0), [view.objects]);
  const [objectId, setObjectId] = useState(editable[0]?.object_id ?? '');
  const target = editable.find((o) => o.object_id === objectId) ?? editable[0];
  const [op, setOp] = useState<AvicEditOp>('recolor');
  const [paletteKey, setPaletteKey] = useState(Object.keys(view.palette)[0] ?? '');
  const [field, setField] = useState<'fill' | 'stroke'>('fill');
  const [text, setText] = useState('');
  const [params, setParams] = useState('{}');
  // After a 409 the base that conflicted is remembered; Apply stays off until a newer version has loaded.
  const [conflictedBase, setConflictedBase] = useState<string | null>(null);
  if (!target) return <Empty title="Nothing editable">This scene has no editable objects.</Empty>;
  const ops = target.operations;
  const activeOp = ops.includes(op) ? op : ops[0];
  let args: Record<string, unknown> | null = null;
  let reason: string | null = null;
  if (activeOp === 'recolor') args = { object_id: target.object_id, palette_key: paletteKey, field };
  else if (activeOp === 'change_text') {
    if (!text.trim()) reason = 'Enter the new text.'; else args = { object_id: target.object_id, text };
  } else {
    try { args = { object_id: target.object_id, params: JSON.parse(params) as unknown }; } catch (e) { reason = `Geometry is not valid JSON: ${(e as Error).message}`; }
  }
  if (conflictedBase === view.svg_sha256) reason = 'Loading the latest version…';
  return (
    <Card title="Edit" id="avic-edit"
      description="Each edit is re-rendered and re-evaluated; a failing edit keeps the stored version. Brief text and protected geometry cannot change.">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Object" htmlFor="avic-object">
          <select id="avic-object" className={inputClass} value={target.object_id} onChange={(e) => setObjectId(e.target.value)}>
            {editable.map((o) => <option key={o.object_id} value={o.object_id}>{o.object_id} ({o.semantic_role}{o.protected ? ', protected' : ''})</option>)}
          </select>
        </Field>
        <Field label="Operation" htmlFor="avic-op">
          <select id="avic-op" className={inputClass} value={activeOp} onChange={(e) => setOp(e.target.value as AvicEditOp)}>
            {ops.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </Field>
        {activeOp === 'recolor' && (<>
          <Field label="Palette colour" htmlFor="avic-palette" hint="Only colours from the brand projection are allowed.">
            <select id="avic-palette" className={inputClass} value={paletteKey} onChange={(e) => setPaletteKey(e.target.value)}>
              {Object.entries(view.palette).map(([k, v]) => <option key={k} value={k}>{k} {v}</option>)}
            </select>
          </Field>
          <Field label="Paint" htmlFor="avic-field">
            <select id="avic-field" className={inputClass} value={field} onChange={(e) => setField(e.target.value as 'fill' | 'stroke')}>
              <option value="fill">fill</option><option value="stroke">stroke</option>
            </select>
          </Field>
        </>)}
        {activeOp === 'change_text' && (
          <Field label="Text" htmlFor="avic-text" hint="Text fixed by the brief is refused.">
            <input id="avic-text" className={inputClass} value={text} maxLength={300} onChange={(e) => setText(e.target.value)} />
          </Field>
        )}
        {activeOp === 'set_geometry' && (
          <Field label="Geometry params (JSON)" htmlFor="avic-params">
            <textarea id="avic-params" className={`${inputClass} min-h-24 font-mono text-xs`} value={params} spellCheck={false}
              onChange={(e) => setParams(e.target.value)} />
          </Field>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={runner.busy || reason !== null || args === null} onClick={() => runner.run('Apply edit', async () => {
          try {
            const r = await editAsset(view.project_id, view.asset_id, activeOp, args ?? {}, view.svg_sha256);
            onChanged();
            return r.status === 'EVALUATED' ? `Applied: ${(r.transformations ?? []).length} change(s), re-evaluated and stored.`
              : `Rejected, stored version kept: ${(r.reasons ?? []).join('; ')}`;
          } catch (e) {
            if (e instanceof ServiceError && e.status === 409) {
              setConflictedBase(view.svg_sha256);
              onChanged();
              throw new Error('This asset changed after you opened it. The latest version is now loaded; review it and apply your edit again.');
            }
            throw e;
          }
        })}>Apply edit</Button>
        {reason && <span className="text-sm text-fg" role="note">{reason}</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function ApprovalAndRelease({ view, onChanged, onApprovals }: { view: AvicAssetView; onChanged: () => void; onApprovals: () => void }) {
  const runner = useRunner();
  const approved = view.approvals.find((a) => a.current && a.decision === 'approve');
  const pending = view.approvals.find((a) => a.current && a.status === 'pending');
  const approvalReason = !view.evaluation.passed ? 'Evaluation has not passed.'
    : !view.consistency.consistent ? 'Stages are stale: recompile first.'
    : approved ? 'The current version is already approved.' : null;
  return (
    <Card title="Approval and local release" id="avic-release"
      description="Approval binds the exact SVG bytes and is decided in the approval queue by someone other than the requester. Release writes a local record only; nothing is published.">
      <KeyValue items={[
        ['Approval', approved ? `Approved by ${approved.reviewer ?? 'reviewer'}` : pending ? 'Pending in the approval queue' : 'Not requested for this version'],
        ['Last release', view.release ? `${view.release.release_allowed ? 'Released locally' : 'Blocked'}${view.release.reasons.length ? `: ${view.release.reasons.join('; ')}` : ''}` : 'none'],
        ['External effects', 'none'],
      ]} />
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={runner.busy || approvalReason !== null} onClick={() => runner.run('Request approval', async () => {
          const r = await requestApproval(view.project_id, view.asset_id);
          onChanged();
          return r.status === 'PENDING' ? 'Approval requested. A reviewer decides it in the approval queue.' : `Blocked: ${r.reasons.join('; ')}`;
        })}>Request approval</Button>
        <Button disabled={!pending} onClick={onApprovals}>Open approval queue</Button>
        <Button variant="primary" disabled={runner.busy || !approved} onClick={() => runner.run('Release locally', async () => {
          const r = await releaseLocal(view.project_id, view.asset_id, approved?.approval_id ?? null);
          onChanged();
          return r.status === 'RELEASED_LOCAL' ? 'Released locally (no external effect).' : `Blocked: ${r.reasons.join('; ')}`;
        })}>Release locally</Button>
        {approvalReason && <span className="text-sm text-fg" role="note">{approvalReason}</span>}
        {!approved && <span className="text-sm text-fg" role="note">Release needs an approval of the current version.</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function BriefIntake({ projectId, onCompiled }: { projectId: string; onCompiled: (assetId: string) => void }) {
  const runner = useRunner();
  const caps = useLoad(() => getAvicCapabilities(), []);
  const profiles = (caps.data?.style_profiles ?? []).filter((p) => p.state === 'IMPLEMENTED_VERIFIED');
  const [profile, setProfile] = useState('');
  const [seed, setSeed] = useState('0');
  const [requirement, setRequirement] = useState('');
  let parsed: unknown = null;
  let parseError: string | null = null;
  if (requirement.trim()) {
    try { parsed = JSON.parse(requirement); } catch (e) { parseError = (e as Error).message; }
  }
  const chosen = profile || profiles[0]?.profile_id || '';
  const seedValue = Number.parseInt(seed, 10);
  const reason = !requirement.trim() ? 'Paste an AssetRequirement JSON (the "requirement" in sample_avic_request.json).'
    : parseError ? `The requirement is not valid JSON: ${parseError}`
    : !chosen ? 'No implemented style profile is available.'
    : !Number.isInteger(seedValue) || seedValue < 0 ? 'Seed must be a whole number of 0 or more.'
    : caps.data && caps.data.renderer.state !== 'IMPLEMENTED_VERIFIED' ? `Renderer unavailable on the API host: ${caps.data.renderer.blockers.join('; ')}` : null;
  return (
    <Card title="Compile a visual" id="avic-intake"
      description="Brief text is data: instructions, publish/send/spend requests and third-party marks are refused. Colours come only from the server's brand projection.">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Style profile" htmlFor="avic-profile">
          <select id="avic-profile" className={inputClass} value={chosen} onChange={(e) => setProfile(e.target.value)}>
            {profiles.map((p) => <option key={p.profile_id} value={p.profile_id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Seed" htmlFor="avic-seed">
          <input id="avic-seed" className={inputClass} inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.trim())} />
        </Field>
      </div>
      <Field label="AssetRequirement (JSON)" htmlFor="avic-requirement">
        <textarea id="avic-requirement" className={`${inputClass} min-h-48 font-mono text-xs`} value={requirement} spellCheck={false}
          onChange={(e) => setRequirement(e.target.value)} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={runner.busy || reason !== null} onClick={() => runner.run('Compile', async () => {
          const r = await compileAsset(projectId, parsed, chosen, seedValue);
          if (r.status !== 'BLOCKED' || r.artifacts) onCompiled(r.asset_id);
          return r.status === 'EVALUATED' ? 'Compiled, rendered and evaluated.' : `${r.status}: ${(r.reasons ?? []).slice(0, 4).join('; ')}`;
        })}>Compile</Button>
        {reason && <span className="text-sm text-fg" role="note">{reason}</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function Capabilities() {
  const caps = useLoad(() => getAvicCapabilities(), []);
  if (caps.error) return <ErrorNote error={caps.error} onRetry={caps.reload} />;
  if (!caps.data) return <Skeleton lines={4} />;
  return (
    <Card title="Capabilities" id="avic-capabilities"
      description={`Each verified claim names the tests behind it. Renderer: ${caps.data.renderer.state} (at most ${caps.data.renderer.concurrency} at once).`}>
      <ul className="flex flex-col gap-1 text-sm">
        {caps.data.capabilities.map((c) => (
          <li key={c.name} className="flex flex-wrap items-center gap-2">
            <Badge label={c.state} tone={c.state === 'IMPLEMENTED_VERIFIED' ? 'success' : c.state === 'PARTIAL' ? 'warning' : 'neutral'} />
            <span className="min-w-0 break-words">{c.name}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Project-scoped visual compiler. */
export function VisualCompilerView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const setSection = useAgencyStore((s) => s.setSection);
  const [assetId, setAssetId] = useState<string | null>(null);
  const list = useLoad(() => (projectId ? listAssets(projectId) : Promise.resolve([])), [projectId]);
  const active = assetId ?? list.data?.[0]?.asset_id ?? null;
  const view = useLoad(() => (projectId && active ? getAsset(projectId, active) : Promise.resolve(null)), [projectId, active]);
  if (!projectId) return <Empty title="Choose a project">Visual assets are compiled inside a project. Select one above.</Empty>;
  if (list.error) return <ErrorNote error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Skeleton lines={6} />;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      {list.data.length > 0 && (
        <Field label="Asset" htmlFor="avic-asset-select">
          <select id="avic-asset-select" className={inputClass} value={active ?? ''} onChange={(e) => setAssetId(e.target.value)}>
            {list.data.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.asset_id} (scene v{a.version})</option>)}
          </select>
        </Field>
      )}
      {view.error && <ErrorNote error={view.error} onRetry={view.reload} />}
      {view.data && (
        <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-2">
          <Overview view={view.data} onChanged={view.reload} />
          <Evaluation view={view.data} />
          <Editor view={view.data} onChanged={view.reload} />
          <ApprovalAndRelease view={view.data} onChanged={view.reload} onApprovals={() => setSection('approvals')} />
        </div>
      )}
      <BriefIntake projectId={projectId} onCompiled={(id) => { setAssetId(id); list.reload(); view.reload(); }} />
      <Capabilities />
    </div>
  );
}
