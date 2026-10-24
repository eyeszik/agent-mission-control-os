"use client";

import { useRef, useState, type KeyboardEvent } from 'react';
import type { AfAssuranceKind, AfAssuranceRecord } from '@amc/shared';
import { createAssurance, getAssurance, listAssurance } from '../../lib/api/agencyFramework';
import { shortHash } from '../../lib/framework/view';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, KeyValue, RunnerOutput, Skeleton, focusRing, inputClass, useLoad, useRunner } from '../agency/ui';

const KINDS: { kind: AfAssuranceKind; label: string; purpose: string; template: Record<string, unknown> }[] = [
  { kind: 'meaning', label: 'Meaning', purpose: 'Requirement coverage: qualifiers found, exclusions absent, output locations read back.',
    template: { task_ids: ['AGM-10-001'], interpreted_obligation: '', qualifiers: [], exclusions: [], output_refs: [] } },
  { kind: 'mutation', label: 'Mutation', purpose: 'One deliberate perturbation of an in-memory variant; expected versus observed findings.',
    template: { base_ref: 'artifact:<id>@v1', mutation_class: 'CLAIM_CHANGE', find: '', replace: '', expected_findings: ['CLAIM_CHANGED'], test_fixture_ref: 'fixture:' } },
  { kind: 'probe', label: 'Probe', purpose: 'A dependency change inside a sandbox snapshot; the canonical graph is proven unchanged.',
    template: { changed_artifact_id: '', change_description: '', declared_effects: [] } },
  { kind: 'renewal', label: 'Renewal', purpose: 'A triggered proposal that retains the decision and its alternatives; never replaces it.',
    template: { trigger_kind: 'NEW_CONTRADICTION', trigger_evidence_refs: [], affected_decision_ref: 'decision:', proposed_alternatives: [], rationale: '' } },
  { kind: 'review', label: 'Review', purpose: 'Exact candidate hashes, dependency snapshot and full-byte access before any decision.',
    template: { candidate_refs: [], summary: '', request_decision: false } },
];

const GOOD = new Set(['COVERED', 'DETECTED', 'MATCHED', 'PROPOSED', 'UNDER_REVIEW', 'NEEDS_HUMAN']);

function Details({ record }: { record: AfAssuranceRecord }) {
  const r = record.record;
  const b = r.body as Record<string, unknown>;
  const list = (v: unknown) => (Array.isArray(v) && v.length ? v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join(', ') : '—');
  const specific: [string, string][] = (() => {
    switch (r.kind) {
      case 'meaning': return [['Coverage', String(b.coverage_state)], ['Qualifiers', list(b.qualifiers)], ['Exclusions', list(b.exclusions)], ['Ambiguities', list(b.ambiguities)], ['Advisory score', `${String((b.advisory as Record<string, unknown> | undefined)?.semantic_score ?? '—')} (advisory only)`]];
      case 'mutation': return [['Class', String(b.mutation_class)], ['Expected', list(b.expected_findings)], ['Observed', list(b.observed_findings)], ['Missed', list(b.false_negative_indicators)], ['Unexpected', list(b.false_positive_indicators)], ['Variant', String(b.variant_storage)]];
      case 'probe': return [['Changed', String(b.changed_dependency_ref)], ['Declared', list(b.declared_effects)], ['Observed', list(b.observed_effects)], ['Undeclared', list(b.unexpected_effects)], ['Canonical unchanged', String((b.isolation as Record<string, unknown> | undefined)?.canonical_unchanged)], ['Writes', list(b.write_set_refs)]];
      case 'renewal': return [['Trigger', String(b.trigger_kind)], ['Decision', String(b.affected_decision_ref)], ['Retained alternatives', list(b.retained_alternatives)], ['Proposed', list(b.proposed_alternatives)], ['Decision unchanged', String(b.decision_unchanged)]];
      case 'review': return [['Candidates', list((b.candidate_subject_refs as { ref: string }[] | undefined)?.map((s) => s.ref))], ['Full candidate access', String((b.access_check_receipt as Record<string, unknown> | undefined)?.full_candidate_access)], ['Unresolved findings', list(b.unresolved_findings)], ['Decision subject', shortHash(b.decision_subject_hash as string)]];
    }
  })();
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Badge label={r.status} tone={GOOD.has(r.status) ? 'success' : 'warning'} />
        <Badge label={record.integrity.status === 'VERIFIED' ? 'Integrity verified' : 'Integrity failed'} tone={record.integrity.status === 'VERIFIED' ? 'success' : 'danger'} />
        {record.subject_now && <Badge label={record.subject_now.subject_current ? 'Subject current' : 'Subject changed since'} tone={record.subject_now.subject_current ? 'neutral' : 'warning'} />}
        {record.superseded_by.length > 0 && <Badge label="Superseded" tone="neutral" />}
      </div>
      <KeyValue items={[
        ['Record', <code key="id" className="font-mono text-xs">{r.record_id}</code>],
        ['Record hash', <code key="h" className="font-mono text-xs">{shortHash(r.record_hash)}</code>],
        ['Subjects', list(r.subject_refs)],
        ['Authority', r.authority],
        ...specific,
      ]} />
      {record.integrity.problems.length > 0 && <ErrorNote error={record.integrity.problems.join('; ')} />}
    </div>
  );
}

function KindPanel({ planId, kind }: { planId: string; kind: (typeof KINDS)[number] }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const rows = useLoad(() => listAssurance(planId, kind.kind), [planId, kind.kind]);
  const [selected, setSelected] = useState<AfAssuranceRecord | null>(null);
  const [draft, setDraft] = useState(JSON.stringify(kind.template, null, 2));
  const runner = useRunner();
  const open = (id: string) => runner.run('Open record', async () => {
    setSelected(await getAssurance(planId, id));
    return 'Record read back from storage';
  });
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="flex min-w-0 flex-col gap-3">
        <p className="text-sm text-fg">{kind.purpose}</p>
        {rows.error ? <ErrorNote error={rows.error} onRetry={rows.reload} /> : !rows.data ? <Skeleton /> : rows.data.length === 0 ? (
          <Empty title={`No ${kind.label} records`}>Records are findings: they never approve, release, publish, send or spend.</Empty>
        ) : (
          <ul className="flex flex-col gap-1" aria-label={`${kind.label} records`}>
            {rows.data.map((r) => (
              <li key={r.record_id}>
                <button type="button" onClick={() => void open(r.record_id)}
                  className={`flex w-full flex-wrap items-center justify-between gap-2 rounded-md border border-line px-3 py-2 text-left text-sm hover:bg-surface-raised ${focusRing}`}>
                  <span className="font-mono text-xs text-fg-strong">{r.record_id}</span>
                  <span className="flex gap-2"><Badge label={r.status} tone={GOOD.has(r.status) ? 'success' : 'warning'} />{!r.is_head && <Badge label="superseded" tone="neutral" />}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <Field label={`New ${kind.label} record (JSON)`} htmlFor={`afw-new-${kind.kind}`} hint="Validated on the server; refs must exist in this project.">
          <textarea id={`afw-new-${kind.kind}`} className={`${inputClass} min-h-40 font-mono text-xs`} value={draft} onChange={(e) => setDraft(e.target.value)} />
        </Field>
        <div>
          <Button disabled={runner.busy} onClick={() => runner.run(`Record ${kind.label}`, async () => {
            let body: Record<string, unknown>;
            try { body = JSON.parse(draft); } catch { throw new Error('The record is not valid JSON'); }
            const created = await createAssurance(planId, kind.kind, body);
            setSelected(created);
            rows.reload();
            refresh();
            return `${kind.label} recorded: ${created.record.status}`;
          })}>
            Record {kind.label}
          </Button>
        </div>
        <RunnerOutput message={runner.message} error={runner.error} />
      </div>
      <div className="min-w-0">{selected ? <Details record={selected} /> : <Empty title="Select a record">Full record, integrity and subject currency appear here.</Empty>}</div>
    </div>
  );
}

export function AssurancePanel({ planId }: { planId: string }) {
  const [active, setActive] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    const next = (active + (e.key === 'ArrowRight' ? 1 : KINDS.length - 1)) % KINDS.length;
    setActive(next);
    tabs.current[next]?.focus();
  };
  return (
    <Card title="Assurance" id="afw-assurance" description="Five non-authoritative records. Each is an immutable, hash-sealed project artifact read back on every view.">
      <div role="tablist" aria-label="Assurance record kinds" className="flex flex-wrap gap-1 border-b border-line" onKeyDown={onKey}>
        {KINDS.map((k, i) => (
          <button key={k.kind} ref={(el) => { tabs.current[i] = el; }} type="button" role="tab" id={`afw-tab-${k.kind}`}
            aria-selected={active === i} aria-controls={`afw-panel-${k.kind}`} tabIndex={active === i ? 0 : -1} onClick={() => setActive(i)}
            className={`rounded-t-md px-3 py-2 text-sm ${focusRing} ${active === i ? 'border-b-2 border-accent font-medium text-fg-strong' : 'text-fg hover:text-fg-strong'}`}>
            {k.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`afw-panel-${KINDS[active].kind}`} aria-labelledby={`afw-tab-${KINDS[active].kind}`}>
        <KindPanel key={KINDS[active].kind} planId={planId} kind={KINDS[active]} />
      </div>
    </Card>
  );
}
