"use client";

import { useEffect, useState } from 'react';
import type { DeliveryManifest } from '@amc/shared';
import { exportManifest, getDeliverables, requestRevision } from '../../../lib/api/agencyOs';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Button, Card, Empty, ErrorNote, Field, Hash, KeyValue, RunnerOutput, Skeleton, inputClass, useLoad, useRunner } from '../ui';

function ManifestPanel({ manifest }: { manifest: DeliveryManifest }) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' }));
    setHref(url);
    return () => URL.revokeObjectURL(url);
  }, [manifest]);
  const signature = manifest.signature as { status?: string; reason?: string };
  return (
    <div className="flex flex-col gap-3 rounded-md border border-line p-4">
      <KeyValue items={[
        ['Included', `${manifest.items.length} verified, approved item(s)`],
        ['Excluded', manifest.excluded.length ? manifest.excluded.map((e) => `${String(e.artifact_id)}: ${(e.reasons as string[]).join(', ')}`).join('; ') : 'None'],
        ['Manifest hash', <Hash key="h" value={manifest.manifest_hash} />],
        ['Signature', <Badge key="s" status={signature.status ?? 'UNSIGNED'} label={signature.status === 'SIGNED' ? 'Signed (HMAC-SHA256)' : `Unsigned — ${signature.reason ?? 'no key'}`} />],
        ['Sent anywhere', 'No. The manifest is returned to you and recorded; nothing is delivered externally.'],
      ]} />
      {href && <a href={href} download={`delivery-${manifest.manifest_hash.slice(0, 12)}.json`} className="text-sm font-medium text-accent underline underline-offset-2">Download manifest (JSON)</a>}
    </div>
  );
}

export function DeliverablesView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const vault = useLoad(() => (projectId ? getDeliverables(projectId) : Promise.resolve([])), [projectId]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [manifest, setManifest] = useState<DeliveryManifest | null>(null);
  const [revising, setRevising] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const runner = useRunner();
  useEffect(() => { setSelected(new Set()); setManifest(null); }, [projectId]);
  if (!projectId) return <Empty title="No project selected" />;
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="flex flex-col gap-6">
      <Card id="vault" title="Deliverable vault" description="Every version with its hash, approvals, release verdict and rights evidence. Export re-checks the stored bytes first."
        actions={<Button variant="primary" disabled={runner.busy || selected.size === 0}
          onClick={() => runner.run('Export', async () => { const m = await exportManifest(projectId, Array.from(selected)); setManifest(m); return `${m.items.length} included, ${m.excluded.length} excluded`; })}>
          Export selected ({selected.size})
        </Button>}>
        {vault.error && <ErrorNote error={vault.error} onRetry={vault.reload} />}
        {vault.loading && !vault.data && <Skeleton lines={5} />}
        {vault.data && vault.data.length === 0 && <Empty title="No deliverables yet">Launch a mission to produce one.</Empty>}
        {vault.data && vault.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <caption className="sr-only">Project deliverables</caption>
              <thead className="text-xs text-fg">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 pr-3"><span className="sr-only">Select</span></th>
                  <th scope="col" className="py-2 pr-3">Artifact</th>
                  <th scope="col" className="py-2 pr-3">Version</th>
                  <th scope="col" className="py-2 pr-3">Hash</th>
                  <th scope="col" className="py-2 pr-3">Release</th>
                  <th scope="col" className="py-2 pr-3">Rights</th>
                  <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {vault.data.map((d) => (
                  <tr key={d.artifact_id} className="border-b border-line align-top">
                    <td className="py-2 pr-3"><input type="checkbox" aria-label={`Select ${d.artifact_key}`} checked={selected.has(d.artifact_id)} onChange={() => toggle(d.artifact_id)} /></td>
                    <td className="py-2 pr-3"><span className="text-fg-strong">{d.artifact_key}</span><div className="text-xs text-fg">{d.artifact_type}</div></td>
                    <td className="py-2 pr-3 text-fg-strong">v{d.version}</td>
                    <td className="py-2 pr-3"><Hash value={d.content_hash} /></td>
                    <td className="py-2 pr-3">
                      <Badge status={d.release.allowed ? 'VERIFIED' : 'BLOCKED'} label={d.release.allowed ? 'Releasable' : 'Not releasable'} />
                      {!d.release.allowed && <div className="mt-1 text-xs text-fg">{d.release.reasons.join(', ')}</div>}
                    </td>
                    <td className="py-2 pr-3"><Badge status={d.rights.status} label={d.rights.status === 'RECORDED' ? 'Recorded' : 'Not recorded'} /></td>
                    <td className="py-2"><Button variant="ghost" onClick={() => { setRevising(d.artifact_id); setNote(''); }}>Request revision</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {revising && (
          <form className="flex flex-col gap-2 rounded-md border border-line p-3" onSubmit={(e) => {
            e.preventDefault();
            runner.run('Request revision', async () => { await requestRevision(projectId, revising, note); setRevising(null); vault.reload(); return 'Revision requested. Launch the revised brief as a new mission.'; });
          }}>
            <Field label="What should change?" htmlFor="revision-note"><textarea id="revision-note" required rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} /></Field>
            <div className="flex gap-2"><Button type="submit" variant="primary" disabled={!note.trim() || runner.busy}>Send request</Button><Button variant="ghost" onClick={() => setRevising(null)}>Cancel</Button></div>
          </form>
        )}
        <RunnerOutput message={runner.message} error={runner.error} />
      </Card>
      {manifest && <Card id="manifest" title="Delivery manifest"><ManifestPanel manifest={manifest} /></Card>}
    </div>
  );
}
