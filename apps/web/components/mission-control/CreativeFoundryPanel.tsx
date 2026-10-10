"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DELIVERABLES,
  clampZoom,
  createFoundryVariant,
  directionWeights,
  fetchFoundryContent,
  getFoundryCapabilities,
  isPreviewable,
  proofTone,
  requestFoundryApproval,
  runFoundryMission,
  uploadReference,
  type CapabilitiesResponse,
  type DeliverableType,
  type FoundryBrief,
  type MissionArtifact,
  type MissionResponse,
} from '../../lib/api/foundry';
import { useProjectStore } from '../../lib/stores/projectStore';

const inputClass =
  'w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60';
const buttonClass =
  'text-xs px-3 py-2 rounded-md border border-zinc-700 text-zinc-100 hover:bg-zinc-800 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60';
const toneClass = { ok: 'text-emerald-300 border-emerald-700/60', warn: 'text-amber-300 border-amber-700/60', bad: 'text-red-300 border-red-700/60' } as const;
const SIZE_CLASS = { s: 'w-36', m: 'w-56', l: 'w-80' } as const;

type Status = { kind: 'idle' } | { kind: 'running'; label: string } | { kind: 'error'; message: string } | { kind: 'done'; message: string };

function useObjectUrls(projectId: string | null, artifacts: MissionArtifact[]) {
  const [urls, setUrls] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    const created: string[] = [];
    (async () => {
      const next: Record<string, string> = {};
      for (const a of artifacts) {
        if (isPreviewable(a.mime_type) === 'text') continue;
        try {
          const { blob } = await fetchFoundryContent(projectId, a.artifact_id);
          const url = URL.createObjectURL(blob);
          created.push(url);
          next[a.artifact_id] = url;
        } catch { /* a missing preview is shown as unavailable, never faked */ }
      }
      if (!cancelled) setUrls(next);
    })();
    return () => { cancelled = true; created.forEach((u) => URL.revokeObjectURL(u)); };
  }, [projectId, artifacts]);
  return urls;
}

function BriefEditor({ caps, busy, onRun }: { caps: CapabilitiesResponse | null; busy: boolean; onRun: (b: FoundryBrief) => void }) {
  const [organization, setOrganization] = useState('');
  const [offering, setOffering] = useState('');
  const [objective, setObjective] = useState('');
  const [audience, setAudience] = useState('');
  const [action, setAction] = useState('');
  const [primary, setPrimary] = useState('swiss_editorial');
  const [secondary, setSecondary] = useState('');
  const [blend, setBlend] = useState(0.3);
  const [intensity, setIntensity] = useState<FoundryBrief['generation_intensity']>('balanced');
  const [quality, setQuality] = useState<FoundryBrief['render_quality']>('draft');
  const [selected, setSelected] = useState<DeliverableType[]>(['logo_family', 'poster', 'design_tokens', 'variants', 'website_section']);
  const [references, setReferences] = useState<string[]>([]);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const projectId = useProjectStore((s) => s.activeProjectId);
  const grammars = caps?.grammars ?? [];

  const toggle = (id: DeliverableType) => setSelected((cur) => (cur.includes(id) ? cur.filter((d) => d !== id) : [...cur, id]));
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!organization.trim()) return;
    onRun({
      organization: organization.trim(), offering, business_objective: objective, target_audience: audience, desired_action: action,
      deliverable_types: selected, visual_direction: directionWeights(primary, secondary || null, blend),
      generation_intensity: intensity, render_quality: quality, reference_assets: references,
    });
  };
  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !projectId) return;
    try {
      const id = await uploadReference(projectId, file);
      setReferences((r) => [...r, id]);
      setUploadNote(`Uploaded ${file.name}. Rights are unknown until recorded, so it is a reference only.`);
    } catch (err) {
      setUploadNote(`Upload failed: ${err instanceof Error ? err.message : 'unknown error'}`);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-labelledby="brief-title">
      <h3 id="brief-title" className="text-sm text-zinc-200 font-medium">Brief</h3>
      <label className="text-xs text-zinc-400">Organization (required)
        <input className={inputClass} value={organization} onChange={(e) => setOrganization(e.target.value)} required maxLength={80} />
      </label>
      <label className="text-xs text-zinc-400">What do you offer?
        <input className={inputClass} value={offering} onChange={(e) => setOffering(e.target.value)} maxLength={300} />
      </label>
      <label className="text-xs text-zinc-400">Objective, in plain words (becomes the headline)
        <textarea className={inputClass} rows={2} value={objective} onChange={(e) => setObjective(e.target.value)} maxLength={500} />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-zinc-400">Audience
          <input className={inputClass} value={audience} onChange={(e) => setAudience(e.target.value)} maxLength={300} />
        </label>
        <label className="text-xs text-zinc-400">Desired action
          <input className={inputClass} value={action} onChange={(e) => setAction(e.target.value)} maxLength={120} />
        </label>
      </div>
      <fieldset className="flex flex-col gap-1">
        <legend className="text-xs text-zinc-400 mb-1">Deliverables</legend>
        {DELIVERABLES.map((d) => (
          <label key={d.id} className="text-xs text-zinc-300 flex items-center gap-2">
            <input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} />
            {d.label}{d.heavy && <span className="text-zinc-500">(slower, local render)</span>}
          </label>
        ))}
      </fieldset>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-zinc-400">Visual direction
          <select className={inputClass} value={primary} onChange={(e) => setPrimary(e.target.value)}>
            {grammars.map((g) => <option key={g.grammar_id} value={g.grammar_id}>{g.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-zinc-400">Blend with
          <select className={inputClass} value={secondary} onChange={(e) => setSecondary(e.target.value)}>
            <option value="">Nothing</option>
            {grammars.filter((g) => g.grammar_id !== primary).map((g) => <option key={g.grammar_id} value={g.grammar_id}>{g.name}</option>)}
          </select>
        </label>
      </div>
      {secondary && (
        <label className="text-xs text-zinc-400">Blend amount: {Math.round(blend * 100)}%
          <input type="range" min={5} max={90} value={Math.round(blend * 100)} onChange={(e) => setBlend(Number(e.target.value) / 100)} className="w-full" />
        </label>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-zinc-400">Generation intensity
          <select className={inputClass} value={intensity} onChange={(e) => setIntensity(e.target.value as FoundryBrief['generation_intensity'])}>
            <option value="conservative">Conservative</option><option value="balanced">Balanced</option><option value="exploratory">Exploratory</option>
          </select>
        </label>
        <label className="text-xs text-zinc-400">Render quality
          <select className={inputClass} value={quality} onChange={(e) => setQuality(e.target.value as FoundryBrief['render_quality'])}>
            <option value="draft">Draft (fast)</option><option value="standard">Standard</option>
          </select>
        </label>
      </div>
      <label className="text-xs text-zinc-400">Brand reference (optional)
        <input type="file" accept="image/png,image/jpeg,image/svg+xml" onChange={onFile} disabled={!projectId} className="block text-xs text-zinc-300 mt-1" />
      </label>
      {uploadNote && <p className="text-[11px] text-zinc-400" role="status">{uploadNote}</p>}
      <button type="submit" className={buttonClass} disabled={busy || !projectId || !organization.trim()}>
        {busy ? 'Generating locally…' : 'Generate brand family'}
      </button>
      {!projectId && <p className="text-[11px] text-amber-300">Choose a project in Projects mode first.</p>}
    </form>
  );
}

function Artboard({ artifacts, urls, selectedId, onSelect, size, filter }: {
  artifacts: MissionArtifact[]; urls: Record<string, string>; selectedId: string | null; onSelect: (id: string) => void;
  size: keyof typeof SIZE_CLASS; filter: string;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const visual = artifacts.filter((a) => ['image', 'video'].includes(isPreviewable(a.mime_type)));
  const onKey = (e: React.KeyboardEvent) => {
    const step = 40;
    if (e.key === '+' || e.key === '=') setZoom((z) => clampZoom(z * 1.2));
    else if (e.key === '-') setZoom((z) => clampZoom(z / 1.2));
    else if (e.key === '0') { setZoom(1); setPan({ x: 0, y: 0 }); }
    else if (e.key.startsWith('Arrow')) {
      setPan((p) => ({ x: p.x + (e.key === 'ArrowLeft' ? step : e.key === 'ArrowRight' ? -step : 0),
                       y: p.y + (e.key === 'ArrowUp' ? step : e.key === 'ArrowDown' ? -step : 0) }));
    } else return;
    e.preventDefault();
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <span>Artboard</span>
        <button type="button" className={buttonClass} onClick={() => setZoom((z) => clampZoom(z / 1.2))} aria-label="Zoom out">−</button>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button type="button" className={buttonClass} onClick={() => setZoom((z) => clampZoom(z * 1.2))} aria-label="Zoom in">+</button>
        <button type="button" className={buttonClass} onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Reset view</button>
        <span className="text-zinc-500">Focus the board, then use arrows to pan and +/− to zoom.</span>
      </div>
      <div
        role="region" aria-label="Creative artboard" tabIndex={0} onKeyDown={onKey}
        onPointerDown={(e) => { drag.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }; }}
        onPointerMove={(e) => { if (drag.current) setPan({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y }); }}
        onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}
        className="relative h-[28rem] overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 cursor-grab"
      >
        <div className="absolute left-4 top-4 flex flex-wrap gap-4 origin-top-left" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, width: '1600px' }}>
          {visual.map((a) => (
            <button key={a.artifact_id} type="button" onClick={() => onSelect(a.artifact_id)} aria-pressed={selectedId === a.artifact_id}
              className={`${SIZE_CLASS[size]} flex flex-col gap-1 text-left rounded-lg border p-2 bg-zinc-900/80 ${selectedId === a.artifact_id ? 'border-emerald-500' : 'border-zinc-800'}`}>
              {urls[a.artifact_id]
                ? (isPreviewable(a.mime_type) === 'video'
                  ? <video src={urls[a.artifact_id]} className={`w-full ${filter}`} muted loop playsInline controls aria-label={`${a.name} preview`} />
                  // eslint-disable-next-line @next/next/no-img-element
                  : <img src={urls[a.artifact_id]} alt={`${a.name}, version ${a.version}`} className={`w-full bg-zinc-100 ${filter}`} draggable={false} />)
                : <span className="text-[11px] text-zinc-500">Preview unavailable</span>}
              <span className="text-[11px] text-zinc-300 truncate">{a.name}</span>
              <span className={`text-[10px] font-mono border rounded px-1 w-fit ${toneClass[proofTone(a.proof_state)]}`}>{a.proof_state}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function CreativeFoundryPanel() {
  const projectId = useProjectStore((s) => s.activeProjectId);
  const [caps, setCaps] = useState<CapabilitiesResponse | null>(null);
  const [mission, setMission] = useState<MissionResponse | null>(null);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [size, setSize] = useState<keyof typeof SIZE_CLASS>('m');
  const [a11y, setA11y] = useState<'none' | 'grayscale' | 'contrast' | 'blur'>('none');
  const [approvals, setApprovals] = useState<Record<string, { id: string; hash?: string }>>({});
  const artifacts = useMemo(() => mission?.artifacts ?? [], [mission]);
  const urls = useObjectUrls(projectId, artifacts);
  const selected = artifacts.find((a) => a.artifact_id === selectedId) ?? null;
  const approval = selected ? approvals[selected.artifact_id] ?? null : null;
  const filter = { none: '', grayscale: 'grayscale', contrast: 'contrast-150', blur: 'blur-sm' }[a11y];

  useEffect(() => {
    getFoundryCapabilities().then(setCaps).catch((err) => setStatus({ kind: 'error', message: `Capabilities unavailable: ${err instanceof Error ? err.message : err}` }));
  }, []);

  const run = useCallback(async (brief: FoundryBrief) => {
    if (!projectId) return;
    setStatus({ kind: 'running', label: 'Rendering locally. Heavy deliverables take a minute.' });
    setApprovals({});
    try {
      const res = await runFoundryMission(projectId, brief);
      setMission(res);
      setSelectedId(res.artifacts.find((a) => a.name === 'poster.png')?.artifact_id ?? res.artifacts[0]?.artifact_id ?? null);
      setStatus({ kind: 'done', message: `${res.artifacts.length} artifacts stored in the project; ${res.capability_gaps.length} capability gap(s).` });
    } catch (err) {
      setStatus({ kind: 'error', message: err instanceof Error ? err.message : 'Mission failed' });
    }
  }, [projectId]);

  const fork = async () => {
    if (!projectId || !mission) return;
    setStatus({ kind: 'running', label: 'Rendering a new direction…' });
    try {
      const res = await createFoundryVariant(projectId, { dimensions: ['composition', 'geometry'], seed: Date.now() % 100000 });
      const created = res.artifact;
      if (created) {
        const entry: MissionArtifact = { ...created, proof_state: created.proof.state, blocked_at: null, validations: [] };
        setMission({ ...mission, artifacts: [...mission.artifacts, entry] });
        setSelectedId(entry.artifact_id);
      }
      setStatus({ kind: 'done', message: `New direction ${res.candidate.candidate_id} (parent ${res.candidate.parents[0] ?? 'none'}).` });
    } catch (err) {
      setStatus({ kind: 'error', message: err instanceof Error ? err.message : 'Variant failed' });
    }
  };

  const approve = async () => {
    if (!projectId || !mission || !selected) return;
    try {
      const res = await requestFoundryApproval(projectId, selected.artifact_id, mission.mission_id);
      setApprovals((cur) => ({ ...cur, [selected.artifact_id]: { id: res.approval.approval_id, hash: res.approval.subject_hash } }));
    } catch (err) {
      setStatus({ kind: 'error', message: err instanceof Error ? err.message : 'Approval request failed' });
    }
  };

  return (
    <section aria-labelledby="foundry-title" className="grid grid-cols-1 xl:grid-cols-12 gap-4 min-h-0">
      <div className="xl:col-span-4 flex flex-col gap-4 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4">
        <h2 id="foundry-title" className="text-zinc-100 font-medium">Creative Foundry</h2>
        <p className="text-xs text-zinc-400">Everything renders on this server: SVG, local Chromium, Blender and FFmpeg. No hosted image or video model is used, and nothing is published.</p>
        <BriefEditor caps={caps} busy={status.kind === 'running'} onRun={run} />
        <details className="text-xs text-zinc-400">
          <summary className="cursor-pointer text-zinc-300">Capability inventory</summary>
          <ul className="mt-2 flex flex-col gap-1">
            {(caps?.capabilities ?? []).map((c) => (
              <li key={c.capability_id} className="flex justify-between gap-2">
                <span className="font-mono">{c.capability_id}</span>
                <span className={c.status === 'AVAILABLE' ? 'text-emerald-300' : 'text-zinc-500'}>{c.status}</span>
              </li>
            ))}
          </ul>
        </details>
      </div>
      <div className="xl:col-span-8 flex flex-col gap-4 min-h-0">
        <div role="status" aria-live="polite" className="text-xs text-zinc-300 min-h-[1.25rem]">
          {status.kind === 'running' && status.label}
          {status.kind === 'done' && status.message}
          {status.kind === 'error' && <span className="text-red-300">Error: {status.message}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-400">
          <span role="group" aria-label="Preview size" className="flex gap-1">
            {(['s', 'm', 'l'] as const).map((s) => (
              <button key={s} type="button" aria-pressed={size === s} onClick={() => setSize(s)} className={`${buttonClass} ${size === s ? 'bg-zinc-800' : ''}`}>{s.toUpperCase()}</button>
            ))}
          </span>
          <label className="flex items-center gap-1">Accessibility preview
            <select className="bg-zinc-950 border border-zinc-800 rounded p-1 text-zinc-200" value={a11y} onChange={(e) => setA11y(e.target.value as typeof a11y)}>
              <option value="none">None</option><option value="grayscale">No colour</option><option value="contrast">High contrast</option><option value="blur">Low vision blur</option>
            </select>
          </label>
          <button type="button" className={buttonClass} onClick={fork} disabled={!mission || status.kind === 'running'}>Fork a new direction</button>
        </div>
        <Artboard artifacts={artifacts} urls={urls} selectedId={selectedId} onSelect={setSelectedId} size={size} filter={filter} />
        {artifacts.some((a) => !['image', 'video'].includes(isPreviewable(a.mime_type))) && (
          <div role="group" aria-label="Source, web and report artifacts" className="flex flex-wrap gap-2">
            {artifacts.filter((a) => !['image', 'video'].includes(isPreviewable(a.mime_type))).map((a) => (
              <button key={a.artifact_id} type="button" aria-pressed={selectedId === a.artifact_id} onClick={() => setSelectedId(a.artifact_id)}
                className={`${buttonClass} ${selectedId === a.artifact_id ? 'bg-zinc-800' : ''}`}>
                {a.name} <span className={`ml-1 font-mono ${toneClass[proofTone(a.proof_state)].split(' ')[0]}`}>{a.proof_state}</span>
              </button>
            ))}
          </div>
        )}
        {selected && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4">
            <div className="flex flex-col gap-2 min-w-0">
              <h3 className="text-sm text-zinc-200 font-medium">{selected.name}</h3>
              {isPreviewable(selected.mime_type) === 'html' && urls[selected.artifact_id] && (
                <iframe title={`${selected.name} live preview`} src={urls[selected.artifact_id]} sandbox="allow-scripts allow-forms" className="w-full h-96 rounded border border-zinc-800 bg-zinc-100" />
              )}
              <dl className="text-xs grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-zinc-400">
                <dt>Proof</dt><dd className={toneClass[proofTone(selected.proof_state)].split(' ')[0]}>{selected.proof_state}{selected.blocked_at ? ` (next: ${selected.blocked_at})` : ''}</dd>
                <dt>Version</dt><dd>v{selected.version} ({selected.action})</dd>
                <dt>SHA-256</dt><dd className="font-mono break-all">{selected.sha256}</dd>
                <dt>Type</dt><dd>{selected.mime_type}, {selected.bytes.toLocaleString()} bytes</dd>
              </dl>
              <div className="flex flex-wrap gap-2">
                {urls[selected.artifact_id] && <a className={buttonClass} href={urls[selected.artifact_id]} download={selected.name}>Download</a>}
                <button type="button" className={buttonClass} onClick={approve}>Request approval for these bytes</button>
              </div>
              {approval && (
                <p className="text-xs text-zinc-300" role="status">Approval {approval.id} is pending, bound to subject hash <span className="font-mono break-all">{approval.hash ?? selected.sha256}</span>. A different reviewer decides it in the Approval inbox.</p>
              )}
            </div>
            <div className="flex flex-col gap-2 min-w-0">
              <h4 className="text-xs text-zinc-300 font-medium">Independent checks</h4>
              <ul className="text-[11px] flex flex-col gap-1 max-h-64 overflow-auto">
                {selected.validations.map((v, i) => (
                  <li key={`${v.check}-${i}`} className="flex gap-2">
                    <span className={v.passed === true ? 'text-emerald-300' : v.passed === false ? 'text-red-300' : 'text-amber-300'}>
                      {v.passed === true ? 'PASS' : v.passed === false ? 'FAIL' : 'NOT RUN'}
                    </span>
                    <span className="text-zinc-400 break-all">{v.check}: {v.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
        {mission && (
          <details className="text-xs text-zinc-400 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3">
            <summary className="cursor-pointer text-zinc-300">Routes, gaps and assumptions</summary>
            <ul className="mt-2 flex flex-col gap-1">
              {mission.routes.map((r, i) => <li key={`${r.deliverable}-${i}`}><span className="font-mono">{r.deliverable}</span>: {r.selected} ({r.status})</li>)}
              {mission.capability_gaps.map((g, i) => <li key={`gap-${i}`} className="text-amber-300">Gap, {g.deliverable}: {g.blockers.join('; ') || g.missing.join(', ')}</li>)}
              {mission.assumptions.map((a, i) => <li key={`as-${i}`}>Assumed {a.field}: {a.reason}</li>)}
            </ul>
          </details>
        )}
      </div>
    </section>
  );
}
