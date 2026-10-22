"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ShieldQuestion, X } from 'lucide-react';
import type { Mission } from '@amc/shared';
import { resolveApproval } from '../../lib/api/approvals';
import { missionAction } from '../../lib/api/missions';
import { Badge, Button, ErrorNote, Hash, KeyValue, StatusNote } from '../agency/ui';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Sentinel gate review. The decision goes to POST /approvals/{id}/decide, which
 * enforces the approver role and separation of duties on the server; only then
 * is the paused checkpoint resumed. Nothing here decides locally: a refusal is
 * shown as the server's message and the mission stays paused.
 */
export function ApprovalModal({ mission, open, onClose, onSettled }: {
  mission: Mission;
  open: boolean;
  onClose: () => void;
  onSettled: (mission: Mission | null) => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const approval = mission.approval;
  const decided = approval?.status === 'resolved';

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement as HTMLElement | null;
    setError(null);
    setNote(null);
    const first = dialog.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? dialog.current)?.focus();
    return () => { opener.current?.focus?.(); };
  }, [open]);

  const close = useCallback(() => { if (!busy) onClose(); }, [busy, onClose]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key !== 'Tab' || !dialog.current) return;
    const items = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (items.length === 0) { e.preventDefault(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  const decide = async (decision: 'approve' | 'reject') => {
    if (!approval) return;
    setBusy(decision);
    setError(null);
    setNote(null);
    try {
      if (!decided) {
        await resolveApproval(approval.approval_id, decision, `council-${approval.approval_id}-${decision}`);
        setNote(`Decision recorded (${decision}). Resuming the paused checkpoint…`);
      }
      const next = await missionAction(mission.mission_id, 'resume');
      onSettled(next);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The decision was not accepted');
      onSettled(null);
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;
  const gate = mission.gate;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div aria-hidden="true" className="absolute inset-0 bg-canvas opacity-80" onClick={close} />
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="gate-title" aria-describedby="gate-desc" tabIndex={-1}
        onKeyDown={onKeyDown}
        className="relative flex max-h-[90dvh] w-full max-w-2xl flex-col gap-4 overflow-auto rounded-t-lg border border-line-strong bg-surface p-4 shadow-lg sm:rounded-lg sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2">
            <ShieldQuestion aria-hidden="true" size={20} className="mt-0.5 shrink-0 text-status-warning" />
            <div className="min-w-0">
              <h2 id="gate-title" className="text-base font-semibold text-fg-strong">Sentinel gate: review before Arty builds</h2>
              <p id="gate-desc" className="mt-1 text-sm text-fg">
                Approving lets the council continue from its saved checkpoint and run only the actions listed below.
                Rejecting ends the mission. The person who started a mission cannot approve it.
              </p>
            </div>
          </div>
          <Button variant="ghost" aria-label="Close" onClick={close} disabled={busy !== null}><X aria-hidden="true" size={18} /></Button>
        </div>

        <KeyValue items={[
          ['Risk', mission.risk ? <Badge label={mission.risk.level} tone={mission.risk.level === 'LOW' ? 'success' : mission.risk.level === 'MEDIUM' ? 'warning' : 'danger'} /> : '—'],
          ['Started by', mission.initiated_by ?? '—'],
          ['Policy', mission.risk?.policy_version ?? '—'],
          ['Subject hash', <Hash key="h" value={gate?.subject_hash} />],
          ['Approval', approval ? <span key="a" className="flex flex-wrap items-center gap-2"><Hash value={approval.approval_id} /><Badge status={approval.status} label={approval.status} /></span> : '—'],
        ]} />

        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-fg-strong">Requested actions</h3>
          {(gate?.requested_actions.length ?? 0) === 0 ? (
            <p className="text-sm text-fg">None. The prototype is kept in the mission record only.</p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm">
              {gate?.requested_actions.map((a) => (
                <li key={`${a.tool_id}:${a.target}`} className="flex flex-wrap items-center gap-2 rounded-md border border-line p-2">
                  <Badge label={a.sensitivity} tone={a.sensitivity === 'READ' ? 'neutral' : 'warning'} />
                  <code className="font-mono text-xs text-fg-strong">{a.tool_id}</code>
                  <span className="break-all text-xs text-fg">{a.target}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {mission.risk && mission.risk.findings.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-fg-strong">Findings</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {mission.risk.findings.map((f) => (
                <li key={`${f.source}:${f.code}`} className="flex flex-col gap-0.5 rounded-md border border-line p-2">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge label={f.severity} tone={f.severity === 'LOW' ? 'neutral' : f.severity === 'MEDIUM' ? 'warning' : 'danger'} />
                    <code className="font-mono text-xs text-fg-strong">{f.code}</code>
                    <span className="text-xs text-fg">{f.source === 'POLICY' ? 'policy rule' : 'model review'}</span>
                  </span>
                  <span className="text-xs text-fg">{f.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {note && <StatusNote>{note}</StatusNote>}
        {error && <ErrorNote error={error} />}

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={close} disabled={busy !== null}>Cancel</Button>
          {decided ? (
            <Button variant="primary" onClick={() => decide(approval?.decision ?? 'approve')} disabled={busy !== null}>
              {busy ? 'Resuming…' : `Resume with recorded decision (${approval?.decision})`}
            </Button>
          ) : (
            <>
              <Button variant="danger" onClick={() => decide('reject')} disabled={busy !== null || !approval}>
                {busy === 'reject' ? 'Rejecting…' : 'Reject'}
              </Button>
              <Button variant="primary" onClick={() => decide('approve')} disabled={busy !== null || !approval}>
                {busy === 'approve' ? 'Approving…' : 'Approve and resume'}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
