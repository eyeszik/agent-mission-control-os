"use client";

import { useState } from 'react';
import { archiveClient, createClient, getOffboarding, linkProject, listClients, startOffboarding } from '../../../lib/api/agencyOs';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../ui';

function Offboarding({ clientId }: { clientId: string }) {
  const report = useLoad(() => getOffboarding(clientId), [clientId]);
  if (report.error) return <ErrorNote error={report.error} />;
  if (!report.data) return <Skeleton lines={2} />;
  const r = report.data as { blockers: string[]; can_archive: boolean; artifacts_retained: number; retention: { policy: string; deletion: string } };
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p>{r.artifacts_retained} artifact(s) retained. {r.retention.policy}.</p>
      <p className="text-fg">Deletion: {r.retention.deletion}</p>
      {r.blockers.length > 0 ? <ul className="list-disc pl-5 text-status-warning">{r.blockers.map((b) => <li key={b}>{b}</li>)}</ul>
        : <p className="text-status-success">Nothing is open.</p>}
    </div>
  );
}

export function ClientsView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const refresh = useAgencyStore((s) => s.refresh);
  const clients = useLoad(listClients, []);
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const runner = useRunner();

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <Card id="new-client" title="Add a client">
        <form className="flex flex-col gap-3" onSubmit={(e) => {
          e.preventDefault();
          runner.run('Add client', async () => { const c = await createClient(name, notes); setName(''); setNotes(''); clients.reload(); refresh(); return `Added ${c.display_name}`; });
        }}>
          <Field label="Client name" htmlFor="client-name"><input id="client-name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} className={inputClass} /></Field>
          <Field label="Notes" htmlFor="client-notes" hint="Avoid personal data; this is visible to your whole team."><textarea id="client-notes" rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} className={inputClass} /></Field>
          <Button type="submit" variant="primary" disabled={runner.busy || !name.trim()}>Add client</Button>
        </form>
        <RunnerOutput message={runner.message} error={runner.error} />
      </Card>
      <div className="xl:col-span-2">
        <Card id="clients" title="Clients">
          {clients.error && <ErrorNote error={clients.error} onRetry={clients.reload} />}
          {clients.loading && !clients.data && <Skeleton lines={4} />}
          {clients.data && clients.data.length === 0 && <Empty title="No clients yet">Add your first client to connect projects to it.</Empty>}
          <ul className="flex flex-col gap-3">
            {(clients.data ?? []).map((c) => (
              <li key={c.client_id} className="rounded-md border border-line p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-fg-strong">{c.display_name}</p>
                    <p className="text-xs text-fg">{(c.projects ?? []).length} project(s){c.notes ? ` · ${c.notes}` : ''}</p>
                  </div>
                  <Badge status={c.status} />
                </div>
                {(c.projects ?? []).length > 0 && (
                  <ul className="mt-2 flex flex-wrap gap-2 text-xs">{(c.projects ?? []).map((p) => <li key={p.project_id}><Badge tone="neutral" label={p.display_name} /></li>)}</ul>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {projectId && c.status === 'ACTIVE' && !(c.projects ?? []).some((p) => p.project_id === projectId) && (
                    <Button disabled={runner.busy} onClick={() => runner.run('Link project', async () => { await linkProject(c.client_id, projectId); clients.reload(); refresh(); return 'Linked the selected project'; })}>
                      Link selected project
                    </Button>
                  )}
                  <Button variant="ghost" aria-expanded={open === c.client_id} onClick={() => setOpen(open === c.client_id ? null : c.client_id)}>Offboarding</Button>
                </div>
                {open === c.client_id && (
                  <div className="mt-3 flex flex-col gap-3 rounded-md border border-line p-3">
                    <Offboarding clientId={c.client_id} />
                    <div className="flex flex-wrap gap-2">
                      {c.status === 'ACTIVE' && <Button variant="danger" disabled={runner.busy} onClick={() => runner.run('Start offboarding', async () => { await startOffboarding(c.client_id); clients.reload(); return 'Offboarding started: no new work can start for this client'; })}>Start offboarding</Button>}
                      {c.status === 'OFFBOARDING' && <Button variant="danger" disabled={runner.busy} onClick={() => runner.run('Archive', async () => { await archiveClient(c.client_id); clients.reload(); return 'Client archived'; })}>Archive</Button>}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
