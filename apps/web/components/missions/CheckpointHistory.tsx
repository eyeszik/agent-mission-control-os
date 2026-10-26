"use client";

import { useEffect, useState } from 'react';
import type { Checkpoints, ToolAudit } from '@amc/shared';
import { getCheckpoints, getToolAudits } from '../../lib/api/missions';
import { Badge, ErrorNote, Hash, Skeleton, errorMessage } from '../agency/ui';

/**
 * The mission's hash-chained checkpoints (verified on the server on every
 * read), the engine's own LangGraph history when there is one, and the
 * Sentinel gateway's audit of every tool call. Reloads whenever a new
 * checkpoint or tool event arrives on the timeline.
 */
export function CheckpointHistory({ missionId, revision }: { missionId: string; revision: number }) {
  const [data, setData] = useState<Checkpoints | null>(null);
  const [audits, setAudits] = useState<ToolAudit[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getCheckpoints(missionId), getToolAudits(missionId)])
      .then(([cp, au]) => { if (alive) { setData(cp); setAudits(au); setError(null); } })
      .catch((err) => { if (alive) setError(errorMessage(err)); });
    return () => { alive = false; };
  }, [missionId, revision]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton lines={3} />;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section aria-labelledby="cp-title" className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="cp-title" className="text-sm font-semibold text-fg-strong">Checkpoints</h3>
          <Badge label={data.chain_verified ? 'Hash chain verified' : `Chain broken: ${data.chain_detail}`} tone={data.chain_verified ? 'success' : 'danger'} wrap />
        </div>
        {data.checkpoints.length === 0 ? (
          <p className="text-sm text-fg">No checkpoint saved yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-xs">
              <caption className="sr-only">Saved checkpoints in order</caption>
              <thead className="text-fg">
                <tr><th scope="col" className="py-1 pr-3 font-medium">#</th><th scope="col" className="py-1 pr-3 font-medium">Phase</th>
                  <th scope="col" className="py-1 pr-3 font-medium">Engine</th><th scope="col" className="py-1 pr-3 font-medium">State hash</th>
                  <th scope="col" className="py-1 pr-3 font-medium">Previous</th><th scope="col" className="py-1 font-medium">Native</th></tr>
              </thead>
              <tbody className="text-fg-strong">
                {data.checkpoints.map((c) => (
                  <tr key={c.checkpoint_id} className="border-t border-line">
                    <td className="py-1.5 pr-3 font-mono">{c.seq}</td>
                    <td className="py-1.5 pr-3">{c.phase}</td>
                    <td className="py-1.5 pr-3">{c.engine}</td>
                    <td className="py-1.5 pr-3"><Hash value={c.state_hash} /></td>
                    <td className="py-1.5 pr-3"><Hash value={c.prev_hash} /></td>
                    <td className="py-1.5">{c.native_checkpoint_id ? <Hash value={c.native_checkpoint_id} /> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data.native.length > 0 && (
          <details className="text-xs text-fg">
            <summary className="cursor-pointer text-fg-strong">LangGraph state history ({data.native.length})</summary>
            <ol className="mt-2 flex flex-col gap-1">
              {data.native.map((n, i) => (
                <li key={n.checkpoint_id ?? i} className="flex flex-wrap items-center gap-2">
                  <Hash value={n.checkpoint_id} />
                  <span>next: {n.next.length ? n.next.join(', ') : 'end'}</span>
                  {n.interrupted && <Badge label="Interrupted at gate" tone="warning" />}
                  {n.terminal && <Badge label={n.terminal} tone="neutral" />}
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>

      <section aria-labelledby="audit-title" className="flex min-w-0 flex-col gap-2">
        <h3 id="audit-title" className="text-sm font-semibold text-fg-strong">Tool audit</h3>
        {audits.length === 0 ? (
          <p className="text-sm text-fg">No tool has been called for this mission.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-xs">
            {audits.map((a) => (
              <li key={a.audit_id} className="flex flex-wrap items-center gap-2">
                <Badge label={a.decision} tone={a.decision === 'ALLOWED' ? 'success' : a.decision === 'DENIED' ? 'warning' : 'danger'} />
                <code className="font-mono text-fg-strong">{a.tool_id}</code>
                <span className="text-fg">{a.seat ?? 'service'} · {a.sensitivity} · {a.reason_code}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
