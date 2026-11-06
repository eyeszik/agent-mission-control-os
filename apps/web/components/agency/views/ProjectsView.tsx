"use client";

import { useState } from 'react';
import { canonizeBrand, createFoundationArtifact, getLifecycle, getMe } from '../../../lib/api/agencyOs';
import { createProject, listProjectArtifacts } from '../../../lib/api/projects';
import { labelOf } from '../../../lib/agency/status';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../ui';

const HEX = /^#[0-9a-fA-F]{6}$/;
const FOUNDATION: { type: string; label: string; hint: string }[] = [
  { type: 'positioning_statement', label: 'Positioning', hint: 'Who it is for and why it matters, in your own words.' },
  { type: 'brand_platform', label: 'Brand platform', hint: 'Promise, values and proof points.' },
  { type: 'brand_core', label: 'Brand core', hint: 'Voice, colour story and typography direction, as prose.' },
];

export function ProjectsView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const setProject = useAgencyStore((s) => s.setProject);
  const refresh = useAgencyStore((s) => s.refresh);
  const me = useLoad(getMe, []);
  const lifecycle = useLoad(() => (projectId ? getLifecycle(projectId) : Promise.resolve(null)), [projectId]);
  const artifacts = useLoad(() => (projectId ? listProjectArtifacts(projectId) : Promise.resolve(null)), [projectId]);
  const [name, setName] = useState('');
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [brandName, setBrandName] = useState('');
  const [palette, setPalette] = useState({ primary: '', secondary: '', surface: '', text: '' });
  const runner = useRunner();
  const existing = new Set((artifacts.data?.artifacts ?? []).map((a) => a.artifact_type));
  const paletteValid = Object.values(palette).every((v) => HEX.test(v));

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 xl:grid-cols-3">
        <Card id="new-project" title="New project">
          <form className="flex flex-col gap-3" onSubmit={(e) => {
            e.preventDefault();
            runner.run('Create project', async () => { const r = await createProject({ display_name: name }); setProject(r.project.project_id); setName(''); refresh(); return `Created ${r.project.display_name}`; });
          }}>
            <Field label="Project name" htmlFor="project-name"><input id="project-name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} className={inputClass} /></Field>
            <Button type="submit" variant="primary" disabled={runner.busy || !name.trim()}>Create project</Button>
          </form>
        </Card>
        <div className="xl:col-span-2">
          <Card id="command-center" title="Project command center" description="Stages, blockers and evidence for the selected project.">
            {!projectId && <Empty title="No project selected">Create a project or pick one in the top bar.</Empty>}
            {lifecycle.error && <ErrorNote error={lifecycle.error} onRetry={lifecycle.reload} />}
            {projectId && !lifecycle.data && !lifecycle.error && <Skeleton lines={5} />}
            {lifecycle.data && (
              <ol className="flex flex-col divide-y divide-line">
                {lifecycle.data.stages.map((s) => (
                  <li key={s.stage} className="flex flex-wrap items-start justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-fg-strong">{labelOf(s.stage)}</p>
                      <p className="text-xs text-fg">{s.unmet.length ? `Waiting on ${s.unmet.map((u) => labelOf(u).toLowerCase()).join(', ')}` : s.evidence.slice(0, 2).join(' · ') || 'No evidence yet'}</p>
                    </div>
                    <Badge status={s.status} />
                  </li>
                ))}
              </ol>
            )}
            {lifecycle.data && lifecycle.data.stale_artifacts.length > 0 && (
              <p role="status" className="text-sm text-status-warning">{lifecycle.data.stale_artifacts.length} artifact(s) are stale because something they depend on changed.</p>
            )}
          </Card>
        </div>
      </div>

      {projectId && (
        <Card id="foundation" title="Strategy and identity inputs"
          description="Human-authored inputs the planner builds on. They are stored as project artifacts; the brand canon must be confirmed by an approver.">
          <div className="grid gap-4 lg:grid-cols-3">
            {FOUNDATION.map((f) => (
              <Field key={f.type} label={f.label} hint={existing.has(f.type) ? 'Already recorded (a new save makes a new artifact).' : f.hint} htmlFor={`f-${f.type}`}>
                <textarea id={`f-${f.type}`} rows={4} maxLength={5000} value={texts[f.type] ?? ''} onChange={(e) => setTexts({ ...texts, [f.type]: e.target.value })} className={inputClass} />
              </Field>
            ))}
          </div>
          <Button disabled={runner.busy || FOUNDATION.every((f) => !(texts[f.type] ?? '').trim())} onClick={() => runner.run('Save inputs', async () => {
            const saved: string[] = [];
            for (const f of FOUNDATION) {
              const text = (texts[f.type] ?? '').trim();
              if (text) { await createFoundationArtifact(projectId, f.type, text); saved.push(f.label); }
            }
            artifacts.reload(); lifecycle.reload();
            return `Saved: ${saved.join(', ')}`;
          })}>Save inputs</Button>
          <fieldset className="flex flex-col gap-3 rounded-md border border-line p-4">
            <legend className="px-1 text-sm font-medium text-fg-strong">Brand canon</legend>
            <p className="text-sm text-fg">Missions render only from an approved brand canon. {me.data?.can.decide_approvals ? 'You can confirm it.' : 'Ask an approver to confirm it; your role cannot.'}</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Field label="Brand name" htmlFor="brand-name"><input id="brand-name" value={brandName} onChange={(e) => setBrandName(e.target.value)} className={inputClass} /></Field>
              {(Object.keys(palette) as (keyof typeof palette)[]).map((k) => (
                <Field key={k} label={`${k} colour`} hint="#rrggbb" htmlFor={`pal-${k}`}>
                  <input id={`pal-${k}`} value={palette[k]} placeholder="#rrggbb" aria-invalid={palette[k] !== '' && !HEX.test(palette[k])}
                    onChange={(e) => setPalette({ ...palette, [k]: e.target.value.trim() })} className={inputClass} />
                </Field>
              ))}
            </div>
            <Button disabled={runner.busy || !me.data?.can.decide_approvals || !brandName.trim() || !paletteValid || !existing.has('brand_core')}
              onClick={() => runner.run('Confirm brand canon', async () => { await canonizeBrand(projectId, brandName.trim(), palette); lifecycle.reload(); return 'Brand canon confirmed from brand_core v1'; })}>
              Confirm brand canon
            </Button>
            {!existing.has('brand_core') && <p className="text-xs text-fg">Save a brand core first; the canon cites it.</p>}
          </fieldset>
          <RunnerOutput message={runner.message} error={runner.error} />
        </Card>
      )}
    </div>
  );
}
