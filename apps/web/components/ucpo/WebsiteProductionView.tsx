"use client";

import { useState } from 'react';
import type { UcpoSiteView } from '@amc/shared';
import { buildSite, compileSite, getSite, getUcpoCapabilities, listSites, traceRequirement } from '../../lib/api/ucpo';
import { useAgencyStore } from '../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, Hash, KeyValue, RunnerOutput, Skeleton, focusRing, inputClass, useLoad, useRunner } from '../agency/ui';

// Website production line (UCPO): brief -> requirements -> PSEM genome -> site IR -> source ->
// sandboxed build -> browser QA -> semantic coverage -> release proof -> human approval.
// Every control calls a real authorized route or is disabled with its reason. Nothing deploys.

const BUILDABLE = new Set(['SCHEDULED', 'RETRY_PENDING']);
const RESULT_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  PASS: 'success', FAIL: 'danger', BLOCKED: 'warning', NOT_RUN: 'neutral', INCONCLUSIVE: 'warning',
};

function BriefIntake({ projectId, onCompiled }: { projectId: string; onCompiled: (siteId: string) => void }) {
  const runner = useRunner();
  const [siteId, setSiteId] = useState('');
  const [brief, setBrief] = useState('');
  const validId = /^[a-z0-9][a-z0-9-]{0,39}$/.test(siteId);
  let parsed: unknown = null;
  let parseError: string | null = null;
  if (brief.trim()) {
    try { parsed = JSON.parse(brief); } catch (e) { parseError = (e as Error).message; }
  }
  const reason = !validId ? 'Enter a lowercase site id (letters, digits, hyphens).'
    : !brief.trim() ? 'Paste a WebsiteBrief JSON (see sample_ucpo_website.json).'
    : parseError ? `The brief is not valid JSON: ${parseError}` : null;
  return (
    <Card title="Brief intake" id="ucpo-intake"
      description="All copy comes from the brief. Compiling is deterministic and executes nothing; the generated source is only built in the sandbox.">
      <div className="grid grid-cols-1 gap-3">
        <Field label="Site id" htmlFor="ucpo-site-id" hint="Stable id; compiling again with the same id regenerates selectively.">
          <input id="ucpo-site-id" className={inputClass} value={siteId} onChange={(e) => setSiteId(e.target.value.trim())} maxLength={40} />
        </Field>
        <Field label="WebsiteBrief (JSON)" htmlFor="ucpo-brief">
          <textarea id="ucpo-brief" className={`${inputClass} min-h-48 font-mono text-xs`} value={brief}
            onChange={(e) => setBrief(e.target.value)} spellCheck={false} />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={runner.busy || reason !== null} onClick={() => runner.run('Compile site', async () => {
          const result = await compileSite(projectId, siteId, parsed);
          onCompiled(result.site_id);
          return `Compiled ${result.requirements} requirements into ${result.source_files} source files; build queued.`;
        })}>Compile site</Button>
        {reason && <span className="text-sm text-fg" role="note">{reason}</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
    </Card>
  );
}

function Overview({ view, onBuilt }: { view: UcpoSiteView; onBuilt: () => void }) {
  const runner = useRunner();
  const state = view.job.state ?? 'NONE';
  const buildReason = BUILDABLE.has(state) ? null : `Build already ran for this source revision (job ${state.toLowerCase()}). Compile a changed brief to build again.`;
  return (
    <Card title={`Site ${view.site_id}`} id="ucpo-overview" description="Every stage is a Project OS artifact with its exact version.">
      <KeyValue items={[
        ['Job', <span key="job"><Badge label={state} tone={state === 'WAITING_APPROVAL' ? 'warning' : 'neutral'} /> <Hash value={view.job.job_id} /></span>],
        ['Build', view.build ? String(view.build.status) : 'not run'],
        ['Browser QA', view.browser_qa ? view.browser_qa.status : 'not run'],
        ['Coverage', view.coverage ? `${view.coverage.mandatory_resolved} / ${view.coverage.mandatory_applicable} mandatory requirements` : 'unresolved until rendered'],
        ['Release', view.release.allowed ? 'Approved and current (deployment is still a separate, unauthorized act)' : `Blocked: ${view.release.reasons.join('; ') || 'not built'}`],
      ]} />
      {view.job.reasons.length > 0 && <ErrorNote error={view.job.reasons.join('; ')} />}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={runner.busy || buildReason !== null} onClick={() => runner.run('Build and verify', async () => {
          const r = await buildSite(view.project_id, view.site_id);
          onBuilt();
          return `Tick ${r.tick.outcome}: ${r.tick.state ?? ''}${r.tick.reasons.length ? ` (${r.tick.reasons.join('; ')})` : ''}`;
        })}>Build and verify in sandbox</Button>
        {buildReason && <span className="text-sm text-fg" role="note">{buildReason}</span>}
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Stage artifacts</caption>
        <thead><tr><th scope="col">Stage</th><th scope="col">Version</th><th scope="col">Status</th><th scope="col">Hash</th></tr></thead>
        <tbody>
          {Object.entries(view.stages).map(([stage, s]) => (
            <tr key={stage} className="border-t border-line"><th scope="row" className="py-1 font-mono text-xs">{stage}</th>
              <td>v{s.version}</td><td>{s.status ?? 'n/a'}</td><td><Hash value={s.content_hash} /></td></tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Evidence({ view }: { view: UcpoSiteView }) {
  if (!view.browser_qa) return <Empty title="No browser evidence yet">Build the site to run the sandboxed Chromium checks.</Empty>;
  const failing = view.browser_qa.checks.filter((c) => c.result !== 'PASS');
  return (
    <Card title="Browser evidence" id="ucpo-evidence" description={view.browser_qa.note}>
      <p className="text-sm text-fg">{view.browser_qa.checks.length} checks · {failing.length} not passing · {Object.keys(view.browser_qa.screenshots).length} screenshots hashed · {view.browser_qa.blocked_requests.length} external requests blocked</p>
      <ul className="flex flex-col gap-1">
        {(failing.length ? failing : view.browser_qa.checks.slice(0, 12)).map((c, i) => (
          <li key={`${c.check}-${c.route}-${c.viewport}-${i}`} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge label={c.result} tone={RESULT_TONE[c.result]} /> <span className="font-mono text-xs">{c.check}</span>
            <span>{c.route ?? ''} {c.viewport ?? ''}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ProofAndDebt({ view, onApprovals }: { view: UcpoSiteView; onApprovals: () => void }) {
  return (
    <Card title="Release proof" id="ucpo-proof" description="Binds exact revisions; any change makes it stale. Approval never deploys.">
      {view.proof ? (
        <KeyValue items={[
          ...Object.entries(view.proof.gates).map(([g, v]) => [g, v] as [string, string]),
          ['Eligible for approval', view.proof.eligible_for_approval ? 'yes' : `no: ${view.proof.reasons.slice(0, 5).join('; ')}`],
          ['Deployment', view.proof.deployment],
        ]} />
      ) : <Empty title="No proof">A proof is sealed after the sandboxed build and browser QA.</Empty>}
      {view.coverage && view.coverage.debt.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-sm font-semibold text-fg-strong">Semantic debt ({view.coverage.debt.length})</h4>
          <ul className="flex flex-col gap-1 text-sm">{view.coverage.debt.slice(0, 10).map((d) => (
            <li key={d.req_id}><span className="font-mono text-xs">{d.req_id}</span> · lost at {d.loss_stage ?? 'unverified'} · {d.repair_proposal}</li>
          ))}</ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!view.approval} onClick={onApprovals}>Open approval queue</Button>
        {!view.approval && <span className="text-sm text-fg" role="note">No approval is open: only an eligible, current proof gets one.</span>}
      </div>
    </Card>
  );
}

function IntentLinker({ view }: { view: UcpoSiteView }) {
  const runner = useRunner();
  const [reqId, setReqId] = useState('req.index.s1.heading');
  const [trace, setTrace] = useState<string | null>(null);
  return (
    <Card title="Intent linker" id="ucpo-linker" description="Trace a requirement from the brief through the IR and source to the rendered page.">
      <Field label="Requirement id" htmlFor="ucpo-req"><input id="ucpo-req" className={inputClass} value={reqId} onChange={(e) => setReqId(e.target.value.trim())} /></Field>
      <div><Button disabled={runner.busy || !reqId} onClick={() => runner.run('Trace', async () => {
        const t = await traceRequirement(view.project_id, view.site_id, reqId);
        setTrace(JSON.stringify({ status: t.status.status, stages: t.status.stages, ir: t.ir, source: t.source, rendered: t.rendered }, null, 2));
      })}>Trace</Button></div>
      <RunnerOutput message={runner.message} error={runner.error} />
      {/* Scrollable, so it must be keyboard-focusable and named (axe: scrollable-region-focusable). */}
      {trace && <pre tabIndex={0} role="region" aria-label="Trace result"
        className={`max-h-72 overflow-auto rounded-md bg-surface-raised p-3 text-xs text-fg-strong ${focusRing}`}>{trace}</pre>}
    </Card>
  );
}

function Capabilities() {
  const caps = useLoad(() => getUcpoCapabilities(), []);
  if (caps.error) return <ErrorNote error={caps.error} onRetry={caps.reload} />;
  if (!caps.data) return <Skeleton lines={4} />;
  return (
    <Card title="Disciplines and capabilities" id="ucpo-capabilities" description="Discovered on the API host. A gap returns a specification, never a fabricated artifact.">
      <ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        {caps.data.disciplines.map((d) => (
          <li key={d.discipline_id} className="flex flex-wrap items-center gap-2">
            <Badge label={d.route.status === 'ROUTED' ? 'Routed' : 'Gap'} tone={d.route.status === 'ROUTED' ? 'success' : 'warning'} /> {d.name}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Project-scoped website production line. */
export function WebsiteProductionView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const setSection = useAgencyStore((s) => s.setSection);
  const [siteId, setSiteId] = useState<string | null>(null);
  const sites = useLoad(() => (projectId ? listSites(projectId) : Promise.resolve([])), [projectId]);
  const active = siteId ?? sites.data?.[0]?.site_id ?? null;
  const view = useLoad(() => (projectId && active ? getSite(projectId, active) : Promise.resolve(null)), [projectId, active]);
  if (!projectId) return <Empty title="Choose a project">Sites are produced inside a project. Select one above.</Empty>;
  if (sites.error) return <ErrorNote error={sites.error} onRetry={sites.reload} />;
  if (!sites.data) return <Skeleton lines={6} />;
  return (
    <div className="flex min-w-0 flex-col gap-6">
      {sites.data.length > 0 && (
        <Field label="Site" htmlFor="ucpo-site-select">
          <select id="ucpo-site-select" className={inputClass} value={active ?? ''} onChange={(e) => setSiteId(e.target.value)}>
            {sites.data.map((s) => <option key={s.site_id} value={s.site_id}>{s.site_id} (brief v{s.version})</option>)}
          </select>
        </Field>
      )}
      {view.error && <ErrorNote error={view.error} onRetry={view.reload} />}
      {view.data && (
        <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-2">
          <Overview view={view.data} onBuilt={view.reload} />
          <ProofAndDebt view={view.data} onApprovals={() => setSection('approvals')} />
          <Evidence view={view.data} />
          <IntentLinker view={view.data} />
        </div>
      )}
      <BriefIntake projectId={projectId} onCompiled={(id) => { setSiteId(id); sites.reload(); view.reload(); }} />
      <Capabilities />
    </div>
  );
}
