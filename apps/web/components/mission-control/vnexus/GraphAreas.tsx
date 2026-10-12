"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { GraphNode } from '@amc/shared';
import {
  addEdge,
  addNode,
  archiveBranch,
  branchFeedback,
  compareBranch,
  compareTwoBranches,
  evaluateBranch,
  forkBranch,
  graphImpact,
  graphView,
  listBranches,
  listVersions,
  mergeBranches,
  nodeEvidence,
  rebaseBranch,
  settleBranch,
  submitBranch,
  type BranchComparison,
  type Evidence,
  type GraphView,
  type Impact,
  type TwoBranchComparison,
  type VnexusBranch,
} from '../../../lib/api/vnexus';
import { changeSetFromLines } from '../../../lib/design/vnexus-editor';
import { useVnexusStore } from '../../../lib/stores/vnexusStore';
import { Badge, Empty, Field, KeyValue, Panel, StatusLine, buttonClass, inputClass, short, useAction } from './ui';

const NODE_KINDS: GraphNode['kind'][] = ['Campaign', 'Audience', 'Insight', 'DesignDecision', 'CreativeConcept', 'Asset', 'Prompt', 'Experiment',
  'Experience', 'Channel', 'Evidence'];
const EDGE_KINDS = ['DERIVED_FROM', 'DEPENDS_ON', 'IMPLEMENTS', 'TESTED_BY', 'TARGETS', 'CONFLICTS_WITH', 'SUPPORTED_BY'];

export function GraphArea() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const [view, setView] = useState<GraphView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [asOf, setAsOf] = useState('');
  const [kind, setKind] = useState<GraphNode['kind']>('Insight');
  const [label, setLabel] = useState('');
  const [edge, setEdge] = useState({ kind: 'SUPPORTED_BY', src: '', dst: '' });
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => setView(await graphView(brandId, asOf || undefined)), [brandId, asOf]);
  const load = useCallback(() => run('Loading graph', refresh, () => 'Graph loaded'), [refresh, run]);
  useEffect(() => { void load(); }, [load]);
  const nodes = view?.nodes ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.node_id, n])), [nodes]);
  const inspect = async (id: string) => {
    setSelected(id);
    await run('Inspecting node', async () => { setImpact(await graphImpact(brandId, [id])); setEvidence(await nodeEvidence(id)); });
  };
  const createNode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim()) return;
    await run('Adding node', () => addNode(brandId, { kind, label: label.trim(), attributes: {} }), (n) => `Added ${n.label}`);
    setLabel(''); void refresh().catch(() => undefined);
  };
  const createEdge = async (e: React.FormEvent) => {
    e.preventDefault();
    await run('Adding relationship', () => addEdge(brandId, { kind: edge.kind, src_node_id: edge.src, dst_node_id: edge.dst }), () => 'Relationship added');
    void refresh().catch(() => undefined);
  };
  return (
    <Panel title="Temporal knowledge graph" description="Typed decisions and their lineage. Superseded decisions stay visible through 'as of' views."
      actions={<button type="button" className={buttonClass} onClick={() => void load()} disabled={busy}>Refresh</button>}>
      <StatusLine state={state} />
      <div className="flex flex-wrap gap-2 items-end">
        <Field label="As of (ISO time, empty = now)"><input className={inputClass} value={asOf} onChange={(e) => setAsOf(e.target.value)} placeholder="2026-10-11T00:00:00.000000Z" /></Field>
        {view && <p className="text-xs text-zinc-400">{nodes.length} nodes · {view.edges.length} edges · lineage cycles: {view.lineage_cycles.length}</p>}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <ul className="text-xs flex flex-col gap-1 max-h-80 overflow-auto" aria-label="Nodes">
          {nodes.length === 0 && <li><Empty>No nodes yet. Approving a genome version adds the first ones.</Empty></li>}
          {nodes.map((n) => (
            <li key={n.node_id}>
              <button type="button" onClick={() => void inspect(n.node_id)} aria-pressed={selected === n.node_id}
                className={`w-full text-left px-2 py-1 rounded-sm border ${selected === n.node_id ? 'border-emerald-700/60 bg-zinc-800/60' : 'border-zinc-800 hover:bg-zinc-800/40'} focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60`}>
                <span className="text-zinc-500">{n.kind}</span> <span className="text-zinc-200">{n.label}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-2 text-xs">
          {selected && byId.get(selected) && <KeyValue rows={[['Node', byId.get(selected)!.label], ['Kind', byId.get(selected)!.kind], ['Valid from', byId.get(selected)!.valid_from]]} />}
          {impact && <div><p className="text-zinc-400">Downstream if this changes ({impact.affected.length})</p>
            {impact.affected.map((a) => <p key={a.node_id}>{a.kind}: {a.label}</p>)}</div>}
          {evidence && <div><p className="text-zinc-400">Evidence ({evidence.evidence.length}) · approvals ({evidence.approvals.length}){evidence.unsupported ? ' — unsupported decision' : ''}</p>
            {evidence.evidence.map((e) => <p key={e.node_id}>{e.label}</p>)}{evidence.approvals.map((a) => <p key={a.node_id}>✓ {a.label}</p>)}</div>}
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <form onSubmit={createNode} className="flex flex-wrap items-end gap-2">
          <Field label="Node kind"><select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value as GraphNode['kind'])}>{NODE_KINDS.map((k) => <option key={k}>{k}</option>)}</select></Field>
          <Field label="Label"><input className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <button type="submit" className={buttonClass} disabled={busy || !label.trim()}>Add node</button>
        </form>
        <form onSubmit={createEdge} className="flex flex-wrap items-end gap-2">
          <Field label="From"><select className={inputClass} value={edge.src} onChange={(e) => setEdge({ ...edge, src: e.target.value })}><option value="">…</option>{nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}</select></Field>
          <Field label="Relationship"><select className={inputClass} value={edge.kind} onChange={(e) => setEdge({ ...edge, kind: e.target.value })}>{EDGE_KINDS.map((k) => <option key={k}>{k}</option>)}</select></Field>
          <Field label="To"><select className={inputClass} value={edge.dst} onChange={(e) => setEdge({ ...edge, dst: e.target.value })}><option value="">…</option>{nodes.map((n) => <option key={n.node_id} value={n.node_id}>{n.label}</option>)}</select></Field>
          <button type="submit" className={buttonClass} disabled={busy || !edge.src || !edge.dst}>Add relationship</button>
        </form>
      </div>
    </Panel>
  );
}

export function MultiverseArea() {
  const brandId = useVnexusStore((s) => s.brandId) as string;
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const [branches, setBranches] = useState<VnexusBranch[]>([]);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [other, setOther] = useState('');
  const [comparison, setComparison] = useState<BranchComparison | null>(null);
  const [two, setTwo] = useState<TwoBranchComparison | null>(null);
  const [form, setForm] = useState({ name: '', hypothesis: '', lines: '' });
  const [feedback, setFeedback] = useState('');
  const { state, run, busy } = useAction();
  const refresh = useCallback(async () => {
    const [b, v] = await Promise.all([listBranches(brandId), listVersions(brandId)]);
    setBranches(b);
    setBaseId(v.find((x) => x.scope === scope && x.scope_ref === scopeRef && x.status === 'APPROVED')?.version_id ?? null);
  }, [brandId, scope, scopeRef]);
  useEffect(() => { void run('Loading branches', refresh, () => 'Branches loaded'); }, [refresh, run]);
  const load = () => refresh().catch(() => undefined);
  const current = branches.find((b) => b.branch_id === selected) ?? null;
  const fork = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!baseId) return;
    const parsed = changeSetFromLines(form.lines);
    if (!parsed.ok) { await run('Forking', () => Promise.reject(new Error(parsed.error))); return; }
    await run('Forking', () => forkBranch(brandId, { base_version_id: baseId, name: form.name.trim(), hypothesis: form.hypothesis, changes: parsed.changes }),
      (b) => `Forked ${b.name}`);
    setForm({ name: '', hypothesis: '', lines: '' }); void load();
  };
  const act = async (label: string, fn: () => Promise<unknown>) => { await run(label, fn); void load(); };
  return (
    <Panel title="Creative multiverse" description="Alternative directions as change sets over the approved version. Promotion goes through human approval; nothing merges itself.">
      <StatusLine state={state} />
      <form onSubmit={fork} className="grid grid-cols-1 md:grid-cols-3 gap-2 items-end">
        <Field label="Branch name"><input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Hypothesis"><input className={inputClass} value={form.hypothesis} onChange={(e) => setForm({ ...form, hypothesis: e.target.value })} /></Field>
        <Field label="Changes" hint="key=value per line; -key removes"><textarea className={inputClass} rows={2} value={form.lines} onChange={(e) => setForm({ ...form, lines: e.target.value })} placeholder="visual.typography.display=Inter" /></Field>
        <button type="submit" className={`${buttonClass} md:col-span-3 justify-self-start`} disabled={busy || !baseId || !form.name.trim()}>
          {baseId ? `Fork from approved ${short(baseId, 10)}` : 'No approved version at this scope'}
        </button>
      </form>
      {branches.length === 0 ? <Empty>No branches yet.</Empty> : (
        <ul className="text-xs flex flex-col gap-1" aria-label="Branches">
          {branches.map((b) => (
            <li key={b.branch_id} className="flex flex-wrap items-center gap-2">
              <button type="button" aria-pressed={selected === b.branch_id} onClick={() => { setSelected(b.branch_id); setComparison(null); setTwo(null); }}
                className={`px-2 py-1 rounded-sm border ${selected === b.branch_id ? 'border-emerald-700/60' : 'border-zinc-800'} focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60`}>{b.name}</button>
              <Badge value={b.state} /><span className="text-zinc-500">{Object.keys(b.changes.set).length} set · {b.changes.unset.length} unset</span>
            </li>
          ))}
        </ul>
      )}
      {current && (
        <div className="flex flex-col gap-2 border-t border-zinc-800 pt-3">
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void run('Comparing with base', async () => setComparison(await compareBranch(current.branch_id)))}>Compare with base</button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void act('Recording evaluation', () => evaluateBranch(current.branch_id))}>Record checks</button>
            <button type="button" className={buttonClass} disabled={busy || current.state !== 'OPEN'} onClick={() => void act('Rebasing', () => rebaseBranch(current.branch_id))}>Rebase</button>
            <button type="button" className={buttonClass} disabled={busy || current.state !== 'OPEN'} onClick={() => void act('Submitting', () => submitBranch(current.branch_id))}>Submit for approval</button>
            <button type="button" className={buttonClass} disabled={busy || current.state !== 'IN_REVIEW'} onClick={() => void act('Checking decision', () => settleBranch(current.branch_id))}>Check decision</button>
            <button type="button" className={buttonClass} disabled={busy || current.state !== 'OPEN'} onClick={() => void act('Archiving', () => archiveBranch(current.branch_id))}>Archive</button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Compare or merge with"><select className={inputClass} value={other} onChange={(e) => setOther(e.target.value)}><option value="">…</option>{branches.filter((b) => b.branch_id !== current.branch_id).map((b) => <option key={b.branch_id} value={b.branch_id}>{b.name}</option>)}</select></Field>
            <button type="button" className={buttonClass} disabled={busy || !other} onClick={() => void run('Comparing branches', async () => setTwo(await compareTwoBranches(current.branch_id, other)))}>Compare</button>
            <button type="button" className={buttonClass} disabled={busy || !other} onClick={() => void act('Merging into a new branch', () => mergeBranches(current.branch_id, other, `${current.name} + merge`))}>Merge into new branch</button>
          </div>
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); void act('Recording feedback', () => branchFeedback(current.branch_id, feedback)).then(() => setFeedback('')); }}>
            <Field label="Your feedback (stored verbatim with your name)"><input className={inputClass} value={feedback} onChange={(e) => setFeedback(e.target.value)} /></Field>
            <button type="submit" className={buttonClass} disabled={busy || !feedback.trim()}>Record</button>
          </form>
          {comparison && (
            <div className="text-xs flex flex-col gap-1">
              <p><Badge value={comparison.promotable ? 'PASSED' : 'BLOCKING'} label={comparison.promotable ? 'Promotable' : 'Not promotable'} /> {comparison.base_is_current ? '' : 'Base is no longer current — rebase first.'}</p>
              <p className="text-zinc-400">Added {comparison.values.added.length} · modified {comparison.values.modified.length} · removed {comparison.values.removed.length} · inherited constraints untouched {comparison.constraints.unchanged_inherited.length}</p>
              {comparison.invariant_violations.map((v) => <p key={`${v.kind}${v.key}`} className="text-red-300">{v.kind}: {v.key} — {v.detail}</p>)}
            </div>
          )}
          {two && <p className="text-xs text-zinc-300">{two.comparable ? `Agree ${two.agree?.length ?? 0} · only here ${two.only_a?.length ?? 0} · only there ${two.only_b?.length ?? 0} · conflicts ${two.conflicts?.map((c) => c.key).join(', ') || 'none'}` : two.reason}</p>}
        </div>
      )}
    </Panel>
  );
}
