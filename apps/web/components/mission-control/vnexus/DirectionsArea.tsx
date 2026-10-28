"use client";

import { useCallback, useEffect, useState } from 'react';
import type { DirectionReviewMode, DirectionState, ReviewSession } from '@amc/shared';
import {
  createDirectionIntent, directionCandidateContent, freezeDirection, generateDirections, getDirectionHandoff, getDirectionReview,
  getDirectionState, importDirectionCandidate, listDirectionIntents, reconstructDirection, requestDirectionSelection, reviewDirections,
  type DirectionFindingInput,
} from '../../../lib/api/vnexusDirections';
import { useProjectStore } from '../../../lib/stores/projectStore';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, buttonClass, inputClass, short, useAction } from './ui';

// Creative directions: brief -> prompt package -> candidates -> evidence -> recommended direction -> revision queue ->
// vector/raster master -> existing approval -> brand book. A review recommends and writes work orders; it never approves,
// regenerates, spends or publishes. Hosted generation routes are disabled; the manual route exports prompts and imports results.

const ROLES = ['LOGO_MARK', 'WORDMARK', 'LOCKUP', 'ICON', 'ILLUSTRATION', 'HERO_IMAGE', 'PHOTOGRAPHY', 'TEXTURE'] as const;
const MODES: DirectionReviewMode[] = ['COMPARE', 'FULL', 'QUICK', 'VECTOR', 'RELEASE'];
const SEATS: [string, string][] = [
  ['01', 'Brand strategist'], ['02', 'Creative director'], ['03', 'Identity designer'], ['04', 'Typography'], ['05', 'Composition'],
  ['06', 'Color'], ['07', 'Accessibility'], ['08', 'Imagery'], ['09', 'Emotional response'], ['10', 'Brand memory'],
  ['11', 'Production/vector'], ['12', 'Application/UX'], ['13', 'Brand safety/rights'], ['14', 'Evidence/QA'],
];
const verdictTone = (v: string) => (v === 'READY_FOR_APPROVAL' || v === 'RECOMMENDED_DIRECTION' ? 'PASSED'
  : v === 'BLOCKED' ? 'BLOCKING' : v === 'REVISE' ? 'FAILED' : 'WARNING');
const gateTone = (s: string) => (s === 'PASS' ? 'PASSED' : s === 'FAIL' ? 'FAILED' : s === 'UNKNOWN' ? 'WARNING' : 'muted');

function useTarget() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const projectId = useProjectStore((s) => s.activeProjectId);
  return { brandId, projectId, target: projectId ? { scope, scope_ref: scopeRef, project_id: projectId } : null };
}

function CandidateImage({ brandId, intentId, projectId, candidateId, label }: { brandId: string; intentId: string; projectId: string; candidateId: string; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let made: string | null = null;
    let cancelled = false;
    directionCandidateContent(brandId, intentId, projectId, candidateId)
      .then(({ blob }) => { made = URL.createObjectURL(blob); if (!cancelled) setUrl(made); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [brandId, intentId, projectId, candidateId]);
  if (failed) return <p className="text-[11px] text-red-300">Stored bytes could not be read back.</p>;
  if (!url) return <p className="text-[11px] text-zinc-500">Loading…</p>;
  return <img src={url} alt={`Stored candidate ${label}`} className="h-32 w-32 object-contain rounded-sm border border-zinc-800 bg-zinc-100" />;
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function SessionView({ session }: { session: ReviewSession }) {
  const labelOf = Object.fromEntries(Object.entries(session.labels).map(([label, id]) => [id, label]));
  return (
    <div className="flex flex-col gap-2 text-xs">
      <KeyValue rows={[
        ['Verdict', <span key="v" className="whitespace-nowrap"><Badge value={verdictTone(session.recommendation.verdict)} label={session.recommendation.verdict} /></span>],
        ['Recommended', session.recommendation.label ? `${session.recommendation.label} (${session.recommendation.note})` : '—'],
        ['Reasons', session.recommendation.reasons.join(' · ') || '—'],
        ['Lenses not reviewed', session.lenses_required_missing.length ? session.lenses_required_missing.join(', ') : 'none'],
        ['Critique route', `gemini.image_critique ${session.routes['gemini.image_critique'] ?? '—'}; scores come only from named reviewers`],
        ['Brand memory', `${session.brand_memory.measured_recall} · ${session.brand_memory.trademark_clearance}`],
        ['Aggregate', session.recommendation.aggregate ? JSON.stringify(session.recommendation.aggregate.means ?? session.recommendation.aggregate.coverage) : 'not computed'],
      ]} />
      <div className="overflow-x-auto">
      <table className="w-full whitespace-nowrap">
        <caption className="sr-only">Critical gates per candidate</caption>
        <thead><tr className="text-left text-zinc-500"><th className="p-1">Candidate</th><th className="p-1">Verdict</th>
          {['EXACT_IDENTITY_TEXT', 'ACCESSIBILITY', 'SAFETY_PRIVACY_RIGHTS', 'CANONICAL_INTEGRITY', 'OUTPUT_PROVENANCE'].map((g) => <th key={g} className="p-1">{g.toLowerCase().replace(/_/g, ' ')}</th>)}</tr></thead>
        <tbody>{session.outcomes.map((o) => (
          <tr key={o.candidate_id} className="border-t border-zinc-800 align-top">
            <td className="p-1">{o.label}</td>
            <td className="p-1"><Badge value={verdictTone(o.verdict)} label={o.verdict} /></td>
            {['EXACT_IDENTITY_TEXT', 'ACCESSIBILITY', 'SAFETY_PRIVACY_RIGHTS', 'CANONICAL_INTEGRITY', 'OUTPUT_PROVENANCE'].map((g) => {
              const r = session.gates.find((x) => x.candidate_id === o.candidate_id && x.gate === g);
              return <td key={g} className="p-1" title={r?.evidence}><Badge value={gateTone(r?.status ?? '')} label={r?.status ?? '—'} /></td>;
            })}
          </tr>
        ))}</tbody>
      </table>
      </div>
      <details>
        <summary className="cursor-pointer text-zinc-300">Findings ({session.findings.length})</summary>
        <ul className="flex flex-col gap-1 mt-1">{session.findings.map((f) => (
          <li key={f.finding_id} className="border-t border-zinc-800 pt-1">
            <Badge value={f.severity === 'BLOCKER' ? 'BLOCKING' : f.severity === 'MAJOR' ? 'FAILED' : 'muted'} label={f.severity} />{' '}
            <span className="text-zinc-400">{labelOf[f.candidate_id] ?? short(f.candidate_id)} · seat {f.seat} · {f.criterion} · {f.evidence_class.toLowerCase()} ({f.assessor.kind.toLowerCase()} {f.assessor.id})</span>
            <p className="text-zinc-200">{f.observation}</p>
          </li>
        ))}</ul>
      </details>
      <div>
        <h4 className="text-zinc-300">Revision queue (proposals only)</h4>
        {session.work_orders.length === 0 ? <p className="text-zinc-500">No work orders.</p> : (
          <ul className="flex flex-col gap-1">{session.work_orders.map((w) => (
            <li key={w.work_order_id} className="border-t border-zinc-800 pt-1">
              <p className="text-zinc-200">{labelOf[w.candidate_id] ?? short(w.candidate_id)}: {w.change}</p>
              <p className="text-zinc-400">Why: {w.why} · Verify: {w.verification} · Protected: {w.protected_invariants.join(', ')}</p>
            </li>
          ))}</ul>
        )}
      </div>
    </div>
  );
}

function IntentWorkspace({ brandId, projectId, intentId }: { brandId: string; projectId: string; intentId: string }) {
  const [state, setState] = useState<DirectionState | null>(null);
  const [session, setSession] = useState<ReviewSession | null>(null);
  const [mode, setMode] = useState<DirectionReviewMode>('COMPARE');
  const [picked, setPicked] = useState<string[]>([]);
  const [findings, setFindings] = useState<DirectionFindingInput[]>([]);
  const [draft, setDraft] = useState<DirectionFindingInput>({ candidate: 'A', seat: '02', criterion: 'concept_coherence', evidence_class: 'INFERRED', observation: '' });
  const [slot, setSlot] = useState(1);
  const [rights, setRights] = useState('');
  const { state: action, run, busy } = useAction();
  const refresh = useCallback(() => run('Loading', () => getDirectionState(brandId, intentId, projectId), () => 'Loaded').then((s) => { if (s) setState(s); }), [brandId, intentId, projectId, run]);
  useEffect(() => { void refresh(); }, [refresh]);
  if (!state) return <StatusLine state={action} />;
  const intent = state.intent;
  const lastSession = state.sessions[state.sessions.length - 1];
  const exportHandoff = async () => {
    const pkg = await getDirectionHandoff(brandId, intentId, projectId);
    const url = URL.createObjectURL(new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url; a.download = `direction-prompts-${intentId}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return pkg;
  };
  return (
    <div className="flex flex-col gap-4 text-xs">
      <KeyValue rows={[
        ['Intent', `${intent.asset_role} · ${intent.status}${intent.blockers.length ? ` · ${intent.blockers.join('; ')}` : ''}`],
        ['Genome', `${intent.genome_ref}${state.stale ? ` (stale: current is ${state.current_genome_ref})` : ''}`],
        ['Vector', `${intent.vector_need} · ${String(intent.vector_instructions.exact_text_rule ?? '')}`],
        ['Gaps', intent.field_decisions.filter((d) => d.status === 'UNKNOWN').map((d) => d.field).join(', ') || 'none'],
      ]} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Exporting prompt package', exportHandoff, () => 'Prompt package downloaded (no provider was called)')}>Export prompt package</button>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Composing locally', () => generateDirections(brandId, intentId, projectId, 'local.foundry_compose'),
          (r) => (r.status === 'BLOCKED' ? `Blocked: ${r.decision.blockers.join('; ')}` : `${r.candidates.length} candidates recorded`)).then(() => refresh())}>Compose locally (marks/icons)</button>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Requesting hosted generation', () => generateDirections(brandId, intentId, projectId, 'cloudflare.workers_ai.text_to_image'),
          (r) => `${r.status}: ${r.decision.blockers.join('; ')}${r.decision.offer ? ` — offered: ${r.decision.offer}` : ''}`)}>Hosted text-to-image (disabled)</button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Slot"><select className={inputClass} value={slot} onChange={(e) => setSlot(Number(e.target.value))}>
          {intent.image_instructions.map((s) => <option key={s.slot} value={s.slot}>{s.slot}: {s.direction}</option>)}</select></Field>
        <Field label="Rights basis (your statement)"><input className={inputClass} value={rights} onChange={(e) => setRights(e.target.value)} /></Field>
        <Field label="Import result (PNG or SVG)"><input type="file" accept="image/png,image/svg+xml" className={inputClass} onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          void run('Importing', async () => importDirectionCandidate(brandId, intentId, projectId, {
            slot, mime: file.type === 'image/svg+xml' ? 'image/svg+xml' : 'image/png', data_base64: await readFile(file),
            reported: rights ? { rights_basis: rights } : {},
          }), (r) => `Imported ${short(r.candidate.candidate_id)} (USER_REPORTED provenance)`).then(() => refresh());
        }} /></Field>
      </div>
      {state.candidates.length === 0 ? <Empty>No candidates yet. Compose locally, or export the prompt package and import results.</Empty> : (
        <ul className="grid grid-cols-2 md:grid-cols-4 gap-3">{state.candidates.map((c) => (
          <li key={c.candidate_id} className="flex flex-col gap-1">
            <CandidateImage brandId={brandId} intentId={intentId} projectId={projectId} candidateId={c.candidate_id} label={`${c.slot} ${c.direction}`} />
            <label className="flex items-center gap-1 text-zinc-300"><input type="checkbox" checked={picked.includes(c.candidate_id)}
              onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.candidate_id] : p.filter((x) => x !== c.candidate_id)))} />
              {c.derived_from ? 'vector rebuild' : `slot ${c.slot}`} · {short(c.candidate_id, 10)}</label>
            <span className="flex flex-wrap gap-1"><Badge value={c.provenance === 'RECORDED' ? 'PASSED' : c.provenance === 'SIMULATED' ? 'FAILED' : 'WARNING'} label={c.provenance} />
              <Badge value="muted" label={c.observed.format_class} />{c.stale ? <Badge value="WARNING" label="STALE" /> : null}</span>
            <span className="text-zinc-500">{c.cost_measured_minor !== null ? `cost ${c.cost_measured_minor} (measured)` : c.reported.cost_minor !== null ? `cost ${c.reported.cost_minor} (reported, unverified)` : 'cost not measured'}{c.near_duplicate_of ? ` · near-duplicate of ${short(c.near_duplicate_of, 10)}` : ''}</span>
          </li>
        ))}</ul>
      )}
      <Panel title="Review board" description="Seats are perspectives, not separate model calls. Scores are a named reviewer's rubric judgment; unassessed criteria stay empty.">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Mode"><select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as DirectionReviewMode)}>
            {MODES.map((m) => <option key={m}>{m}</option>)}</select></Field>
          <Field label="Candidate (label or id)"><input className={inputClass} value={draft.candidate} onChange={(e) => setDraft({ ...draft, candidate: e.target.value.trim() })} /></Field>
          <Field label="Seat"><select className={inputClass} value={draft.seat} onChange={(e) => setDraft({ ...draft, seat: e.target.value })}>
            {SEATS.map(([id, name]) => <option key={id} value={id}>{id} {name}</option>)}</select></Field>
          <Field label="Criterion"><input className={inputClass} value={draft.criterion} onChange={(e) => setDraft({ ...draft, criterion: e.target.value.trim() })} /></Field>
          <Field label="Evidence"><select className={inputClass} value={draft.evidence_class} onChange={(e) => setDraft({ ...draft, evidence_class: e.target.value as DirectionFindingInput['evidence_class'] })}>
            {['OBSERVED', 'INFERRED', 'PROPOSED', 'UNKNOWN'].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Score 0–10 (optional)"><input className={inputClass} inputMode="numeric" value={draft.score ?? ''} onChange={(e) => setDraft({ ...draft, score: e.target.value === '' ? undefined : Math.max(0, Math.min(10, Number(e.target.value))) })} /></Field>
          <Field label="Observation"><input className={inputClass} value={draft.observation} onChange={(e) => setDraft({ ...draft, observation: e.target.value })} /></Field>
          <button type="button" className={buttonClass} disabled={!draft.observation} onClick={() => { setFindings((f) => [...f, draft]); setDraft({ ...draft, observation: '', score: undefined }); }}>Add finding</button>
        </div>
        {findings.length > 0 && <p className="text-zinc-400">{findings.length} finding(s) queued for this review.</p>}
        <button type="button" className={buttonClass} disabled={busy || picked.length === 0} onClick={() => void run('Reviewing',
          () => reviewDirections(brandId, intentId, projectId, mode, picked, findings),
          (r) => `Review ${short(r.session.session_id)}: ${r.session.recommendation.verdict}`).then((r) => { if (r) { setSession(r.session); setFindings([]); void refresh(); } })}>Run {mode} review on {picked.length} candidate(s)</button>
        {!session && lastSession && <button type="button" className={buttonClass} onClick={() => void run('Loading review', () => getDirectionReview(brandId, intentId, projectId, lastSession.session_id), () => 'Loaded').then((r) => { if (r) setSession(r.session); })}>Open last review ({lastSession.verdict})</button>}
        {session && <SessionView session={session} />}
      </Panel>
      <Panel title="Selection, master and approval" description="Selection and the master are decided by another person in the approval queue. The brand book reads the master only through the approved genome, pinned by hash.">
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} disabled={busy || !session || picked.length !== 1} onClick={() => void run('Requesting selection approval',
            () => requestDirectionSelection(brandId, intentId, projectId, picked[0], session!.session_id),
            (r) => (r.status === 'PENDING' ? `Selection approval ${short(r.approval_id, 10)} pending in the approval queue` : `Blocked: ${r.reasons.join(', ')}`)).then(() => refresh())}>Request selection of the checked candidate</button>
          <button type="button" className={buttonClass} disabled={busy || picked.length !== 1} onClick={() => void run('Reconstructing',
            () => reconstructDirection(brandId, intentId, projectId, { candidate_id: picked[0], method: 'controlled_trace' }),
            (r) => `Reconstruction ${r.reconstruction.status} (${r.reconstruction.classification}; fidelity ${String(r.reconstruction.fidelity.status)})`).then(() => refresh())}>Rebuild as vector</button>
          <button type="button" className={buttonClass} disabled={busy || !session || session.mode !== 'RELEASE' || picked.length !== 1} onClick={() => void run('Freezing master',
            () => freezeDirection(brandId, intentId, projectId, picked[0], session!.session_id),
            (r) => (r.status === 'PENDING_GENOME_REVIEW' ? `Genome draft ${short(r.genome_version_id, 10)} submitted; approval ${short(r.approval_id, 10)} pending` : `Blocked: ${r.reasons.join(', ')}`)).then(() => refresh())}>Freeze as master (needs a RELEASE review)</button>
        </div>
        <ul className="flex flex-col gap-1">{state.bindings.map((b) => (
          <li key={b.binding_id} className="border-t border-zinc-800 pt-1">
            {b.kind} · {short(b.subject_sha256, 12)} · approval {short(b.approval_id, 10)} · {b.kind === 'SELECTION' ? (b.selected ? 'selected' : `not selected: ${(b.reasons ?? []).join(', ')}`) : `genome ${b.genome_status ?? b.status}`}
          </li>
        ))}</ul>
        {state.reconstructions.map((r) => (
          <p key={r.reconstruction_id} className="text-zinc-300">Vector rebuild {short(r.reconstruction_id, 10)}: {r.status} · {r.checks.filter((c) => c.status === 'FAIL').map((c) => c.check).join(', ') || 'no failed checks'} · {r.checks.filter((c) => c.status === 'NOT_VERIFIED').length} not verified</p>
        ))}
      </Panel>
      <StatusLine state={action} />
    </div>
  );
}

export function DirectionsArea() {
  const { brandId, projectId, target } = useTarget();
  const [intents, setIntents] = useState<{ intent_id: string; asset_role: string; status: string; objective: string }[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [role, setRole] = useState<(typeof ROLES)[number]>('LOGO_MARK');
  const [objective, setObjective] = useState('');
  const [exactText, setExactText] = useState('');
  const { state, run, busy } = useAction();
  useEffect(() => {
    if (!projectId) return;
    void listDirectionIntents(brandId, projectId).then((r) => setIntents(r.intents)).catch(() => setIntents([]));
  }, [brandId, projectId]);
  if (!target || !projectId) return <Empty>Select a project to work on creative directions.</Empty>;
  return (
    <Panel title="Creative directions" description="Brand-aware concepts from the approved genome, reviewed with evidence, selected by a person and frozen into the genome through the existing approval.">
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <Field label="Asset role"><select className={inputClass} value={role} onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])}>
          {ROLES.map((r) => <option key={r}>{r}</option>)}</select></Field>
        <Field label="Objective"><input className={inputClass} value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        <Field label="Exact identity text" hint="Leave empty if unknown; type @none if there is none"><input className={inputClass} value={exactText} onChange={(e) => setExactText(e.target.value)} /></Field>
        <button type="button" className={buttonClass} disabled={busy || !objective.trim()} onClick={() => void run('Compiling intent',
          () => createDirectionIntent(brandId, target, {
            asset_role: role, objective: objective.trim(),
            exact_text: exactText.trim() === '' ? null : exactText.trim() === '@none' ? '@none' : [exactText],
          }), (r) => `Intent ${short(r.intent.intent_id)} ${r.intent.status}`).then((r) => {
            if (r) { setActive(r.intent.intent_id); setIntents((xs) => [{ ...r.intent, objective: r.intent.brief.objective }, ...xs.filter((x) => x.intent_id !== r.intent.intent_id)]); }
          })}>Compile intent</button>
      </div>
      <StatusLine state={state} />
      {intents.length > 0 && (
        <Field label="Intent"><select className={inputClass} value={active ?? ''} onChange={(e) => setActive(e.target.value || null)}>
          <option value="">Choose an intent</option>
          {intents.map((i) => <option key={i.intent_id} value={i.intent_id}>{i.asset_role} · {i.status} · {i.objective.slice(0, 60)}</option>)}
        </select></Field>
      )}
      {active && <IntentWorkspace key={active} brandId={brandId} projectId={projectId} intentId={active} />}
    </Panel>
  );
}
