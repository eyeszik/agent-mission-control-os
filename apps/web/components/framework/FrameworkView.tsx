"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import type { AfApplicability, AfArchetype, AfPlanView, AfTaskState } from '@amc/shared';
import { createPlan, decideApplicability, getCatalog, getPlan, listPlans, listTasks } from '../../lib/api/agencyFramework';
import { APPLICABILITY_LABEL, STATE_LABEL, STATE_TONE, ratioLabel, ratioPercent, shortHash } from '../../lib/framework/view';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, KeyValue, RunnerOutput, Skeleton, focusRing, inputClass, useLoad, useRunner } from '../agency/ui';
import { AssurancePanel } from './AssurancePanel';
import { AuditPanel, GatesPanel, MetricsPanel } from './FrameworkPanels';
import { TaskInspector } from './TaskInspector';

const ARCHETYPES: { id: AfArchetype; label: string }[] = [
  { id: 'B2C_PHYSICAL_PRODUCT', label: 'B2C physical product' },
  { id: 'B2B_PROFESSIONAL_SERVICES', label: 'B2B professional services' },
  { id: 'SAAS_SUBSCRIPTION', label: 'SaaS subscription' },
  { id: 'OTHER', label: 'Other' },
];
const DISCIPLINES = ['Discover', 'Strategize', 'Design', 'Build', 'Activate', 'Optimize'] as const;
const TABS = ['Tasks', 'Gates', 'KPIs', 'Assurance', 'Audit'] as const;

function Instantiate({ projectId, onCreated }: { projectId: string; onCreated: () => void }) {
  const runner = useRunner();
  const [archetype, setArchetype] = useState<AfArchetype>('OTHER');
  const [scope, setScope] = useState('');
  return (
    <Card title="Start the agency operating framework" id="afw-start"
      description="Adds the version-pinned 295-task catalog to this project. Every task starts in the backlog and unassessed; nothing is marked done.">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Engagement type" htmlFor="afw-archetype">
          <select id="afw-archetype" className={inputClass} value={archetype} onChange={(e) => setArchetype(e.target.value as AfArchetype)}>
            {ARCHETYPES.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </Field>
        <Field label="Engagement scope" htmlFor="afw-scope" hint="What the client engaged you for; used by reviewers when deciding applicability.">
          <input id="afw-scope" className={inputClass} value={scope} onChange={(e) => setScope(e.target.value)} maxLength={2000} />
        </Field>
      </div>
      <div>
        <Button variant="primary" disabled={runner.busy} onClick={() => runner.run('Start framework', async () => {
          const view = await createPlan({ project_id: projectId, archetype, engagement_scope: scope.trim() });
          onCreated();
          return `Framework added: ${view.progress.overall.defined} tasks, 0 verified.`;
        })}>
          Add 295-task framework
        </Button>
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function ModuleNavigator({ view, modules, selected, onSelect }: {
  view: AfPlanView; modules: { module_id: string; title: string; phase: string }[]; selected: string; onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="Modules" className="flex min-w-0 flex-col gap-3">
      {DISCIPLINES.map((d) => (
        <div key={d} className="flex flex-col gap-1">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg">{d} <span className="font-normal normal-case">· {ratioLabel(view.progress.disciplines[d])}</span></h4>
          <ul className="flex flex-col gap-1">
            {modules.filter((m) => m.phase === d).map((m) => {
              const c = view.progress.modules[m.module_id];
              const pct = ratioPercent(c);
              return (
                <li key={m.module_id}>
                  <button type="button" aria-current={selected === m.module_id ? 'true' : undefined} onClick={() => onSelect(m.module_id)}
                    className={`flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left text-sm ${focusRing} ${selected === m.module_id ? 'bg-surface-raised text-fg-strong' : 'text-fg hover:bg-surface-raised'}`}>
                    <span><span className="font-mono text-xs">{m.module_id}</span> {m.title}</span>
                    <span className="text-xs text-fg">{pct === null ? ratioLabel(c) : `${pct}% · ${ratioLabel(c)}`}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function ModuleTasks({ planId, moduleId, onOpen }: { planId: string; moduleId: string; onOpen: (taskId: string) => void }) {
  const refresh = useAgencyStore((s) => s.refresh);
  const [state, setState] = useState('');
  const [applicability, setApplicability] = useState('');
  const [query, setQuery] = useState('');
  const [bulk, setBulk] = useState<AfApplicability>('REQUIRED');
  const [reason, setReason] = useState('');
  const runner = useRunner();
  const tasks = useLoad(() => listTasks(planId, { module_id: moduleId, state, applicability, q: query }), [planId, moduleId, state, applicability, query]);
  const unassessed = (tasks.data ?? []).filter((t) => t.applicability === 'UNASSESSED');
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Field label="State" htmlFor="afw-filter-state">
          <select id="afw-filter-state" className={inputClass} value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All</option>
            {(Object.keys(STATE_LABEL) as AfTaskState[]).map((s) => <option key={s} value={s}>{STATE_LABEL[s]}</option>)}
          </select>
        </Field>
        <Field label="Applicability" htmlFor="afw-filter-app">
          <select id="afw-filter-app" className={inputClass} value={applicability} onChange={(e) => setApplicability(e.target.value)}>
            <option value="">All</option>
            {(Object.keys(APPLICABILITY_LABEL) as AfApplicability[]).map((a) => <option key={a} value={a}>{APPLICABILITY_LABEL[a]}</option>)}
          </select>
        </Field>
        <Field label="Search" htmlFor="afw-filter-q">
          <input id="afw-filter-q" type="search" className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} maxLength={120} />
        </Field>
      </div>
      {unassessed.length > 0 && (
        <fieldset className="flex flex-col gap-2 rounded-md border border-line p-3">
          <legend className="px-1 text-sm font-medium text-fg-strong">Assess {unassessed.length} unassessed task(s) in {moduleId}</legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
            <Field label="Decision" htmlFor="afw-bulk">
              <select id="afw-bulk" className={inputClass} value={bulk} onChange={(e) => setBulk(e.target.value as AfApplicability)}>
                <option value="REQUIRED">Required</option>
                <option value="CONDITIONAL">Conditional</option>
                <option value="NOT_APPLICABLE">Not applicable</option>
              </select>
            </Field>
            <Field label="Reason" htmlFor="afw-bulk-reason">
              <input id="afw-bulk-reason" className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button disabled={runner.busy || reason.trim().length < 3} onClick={() => runner.run('Record applicability', async () => {
              const out = await decideApplicability(planId, unassessed.map((t) => ({ task_id: t.task_id, applicability: bulk, reason: reason.trim() })));
              tasks.reload();
              refresh();
              return `${out.applied.length} task(s) assessed${out.skipped.length ? `, ${out.skipped.length} skipped` : ''}`;
            })}>Apply</Button>
          </div>
          <RunnerOutput message={runner.message} error={runner.error} />
        </fieldset>
      )}
      {tasks.error ? <ErrorNote error={tasks.error} onRetry={tasks.reload} /> : !tasks.data ? <Skeleton lines={6} /> : tasks.data.length === 0 ? (
        <Empty title="No tasks match these filters" />
      ) : (
        <ul className="flex flex-col gap-1" aria-label={`Tasks in ${moduleId}`}>
          {tasks.data.map((t) => (
            <li key={t.task_id}>
              <button type="button" onClick={() => onOpen(t.task_id)}
                className={`flex w-full flex-col gap-1 rounded-md border border-line px-3 py-2 text-left hover:bg-surface-raised ${focusRing}`}>
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm text-fg-strong"><span className="font-mono text-xs text-fg">{t.task_id}</span> {t.title}</span>
                  <span className="flex flex-wrap gap-1">
                    <Badge label={APPLICABILITY_LABEL[t.applicability as AfApplicability]} tone={t.applicability === 'REQUIRED' ? 'info' : 'neutral'} />
                    <Badge label={STATE_LABEL[t.state as AfTaskState]} tone={STATE_TONE[t.state as AfTaskState]} />
                  </span>
                </span>
                <span className="text-xs text-fg">{t.output_class} · {t.ref_count} ref(s){t.status_reason ? ` · ${t.status_reason}` : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlanDashboard({ planId }: { planId: string }) {
  const plan = useLoad(() => getPlan(planId), [planId]);
  const catalog = useLoad(getCatalog, []);
  const [tab, setTab] = useState(0);
  const [moduleId, setModuleId] = useState('AGM-01');
  const [taskId, setTaskId] = useState<string | null>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const modules = useMemo(() => catalog.data?.modules ?? [], [catalog.data]);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    const next = (tab + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length;
    setTab(next);
    tabs.current[next]?.focus();
  };
  if (plan.error) return <ErrorNote error={plan.error} onRetry={plan.reload} />;
  if (!plan.data || !catalog.data) return <Skeleton lines={8} />;
  const view = plan.data;
  const overall = view.progress.overall;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <Card title="Agency operating framework" id="afw-summary"
        description={`${view.plan.archetype.replaceAll('_', ' ').toLowerCase()} · catalog ${view.catalog.catalog_version} · pinned ${shortHash(view.catalog.sha256)}`}>
        <KeyValue items={[
          ['Tasks', `${overall.defined} defined · ${overall.applicable} applicable · ${overall.not_applicable} not applicable · ${overall.unassessed} not assessed`],
          ['Progress', ratioLabel(overall)],
          ['Verified / approved', `${overall.verified} verified · ${overall.approved} approved · ${overall.blocked} blocked or invalidated`],
          ['Release', `Not release-eligible here: ${view.readiness.release_eligibility_owner}`],
          ['External actions', view.readiness.external_actions],
        ]} />
        {view.readiness.synthetic_evidence_present && <Badge label="Synthetic evidence present: never client proof" tone="warning" wrap />}
      </Card>

      <div role="tablist" aria-label="Framework views" className="flex flex-wrap gap-1 border-b border-line" onKeyDown={onKey}>
        {TABS.map((t, i) => (
          <button key={t} ref={(el) => { tabs.current[i] = el; }} type="button" role="tab" id={`afw-main-tab-${i}`}
            aria-selected={tab === i} aria-controls={`afw-main-panel-${i}`} tabIndex={tab === i ? 0 : -1} onClick={() => setTab(i)}
            className={`rounded-t-md px-3 py-2 text-sm ${focusRing} ${tab === i ? 'border-b-2 border-accent font-medium text-fg-strong' : 'text-fg hover:text-fg-strong'}`}>
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`afw-main-panel-${tab}`} aria-labelledby={`afw-main-tab-${tab}`} className="min-w-0">
        {TABS[tab] === 'Tasks' && (
          <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(14rem,18rem)_minmax(0,1fr)_minmax(0,1.2fr)]">
            <Card title="Modules" id="afw-modules"><ModuleNavigator view={view} modules={modules} selected={moduleId} onSelect={(id) => { setModuleId(id); setTaskId(null); }} /></Card>
            <Card title={`${moduleId} · ${modules.find((m) => m.module_id === moduleId)?.title ?? ''}`} id="afw-tasks"
              description={modules.find((m) => m.module_id === moduleId)?.required_deliverable}>
              <ModuleTasks planId={planId} moduleId={moduleId} onOpen={setTaskId} />
            </Card>
            <Card title="Task" id="afw-inspector">
              {taskId ? <TaskInspector key={taskId} planId={planId} taskId={taskId} onClose={() => setTaskId(null)} /> : <Empty title="Select a task">Objective, owner, refs, checks, approvals and history appear here.</Empty>}
            </Card>
          </div>
        )}
        {TABS[tab] === 'Gates' && <GatesPanel view={view} />}
        {TABS[tab] === 'KPIs' && <MetricsPanel planId={planId} />}
        {TABS[tab] === 'Assurance' && <AssurancePanel planId={planId} />}
        {TABS[tab] === 'Audit' && <AuditPanel planId={planId} />}
      </div>
    </div>
  );
}

/** Project-scoped agency operating framework: modules, tasks, gates, KPIs, assurance and audit. */
export function FrameworkView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const plans = useLoad(() => (projectId ? listPlans(projectId) : Promise.resolve([])), [projectId]);
  if (!projectId) return <Empty title="Choose a project">The framework is instantiated per project. Select one above.</Empty>;
  if (plans.error) return <ErrorNote error={plans.error} onRetry={plans.reload} />;
  if (!plans.data) return <Skeleton lines={6} />;
  if (plans.data.length === 0) return <Instantiate projectId={projectId} onCreated={plans.reload} />;
  return <PlanDashboard planId={plans.data[0].plan_id} />;
}
