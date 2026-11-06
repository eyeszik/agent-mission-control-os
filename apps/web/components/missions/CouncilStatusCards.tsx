"use client";

import { CheckCircle2, CircleDashed, Loader2, ShieldAlert, ShieldCheck, ShieldQuestion, SkipForward, XCircle } from 'lucide-react';
import type { Mission } from '@amc/shared';
import { SEATS, type CouncilView, type GateState, type SeatState } from '../../lib/missions/council';
import { Badge } from '../agency/ui';

const SEAT_LABEL: Record<SeatState, string> = {
  waiting: 'Waiting',
  running: 'Working',
  done: 'Done',
  skipped: 'Skipped',
  blocked: 'Stopped',
};
const SEAT_TONE = { waiting: 'neutral', running: 'info', done: 'success', skipped: 'neutral', blocked: 'danger' } as const;

const GATE_LABEL: Record<GateState, string> = {
  none: 'Not reached',
  pending: 'Awaiting a reviewer',
  approved: 'Approved',
  rejected: 'Rejected',
};
const GATE_TONE = { none: 'neutral', pending: 'warning', approved: 'success', rejected: 'danger' } as const;

function SeatIcon({ state }: { state: SeatState }) {
  const common = { 'aria-hidden': true, size: 18 } as const;
  switch (state) {
    case 'running': return <Loader2 {...common} className="text-status-info motion-safe:animate-spin" />;
    case 'done': return <CheckCircle2 {...common} className="text-status-success" />;
    case 'skipped': return <SkipForward {...common} className="text-fg" />;
    case 'blocked': return <XCircle {...common} className="text-status-danger" />;
    default: return <CircleDashed {...common} className="text-fg" />;
  }
}

function GateIcon({ gate }: { gate: GateState }) {
  const common = { 'aria-hidden': true, size: 18 } as const;
  if (gate === 'approved') return <ShieldCheck {...common} className="text-status-success" />;
  if (gate === 'rejected') return <ShieldAlert {...common} className="text-status-danger" />;
  if (gate === 'pending') return <ShieldQuestion {...common} className="text-status-warning motion-safe:animate-pulse" />;
  return <ShieldQuestion {...common} className="text-fg" />;
}

/** One card per council seat plus the Sentinel gate, derived only from persisted events and the mission row. */
export function CouncilStatusCards({ view, mission }: { view: CouncilView; mission: Mission }) {
  return (
    <ul aria-label="Council seats" className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">
      {SEATS.map(({ seat, name, role }) => {
        const state = view.seats[seat];
        const result = mission.results[seat];
        return (
          <li key={seat} aria-label={`${name}: ${SEAT_LABEL[state]}`}
            className={`flex min-w-0 flex-col gap-2 rounded-lg border bg-surface p-4 ${state === 'running' ? 'border-status-info' : 'border-line'}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 font-medium text-fg-strong"><SeatIcon state={state} />{name}</span>
              <Badge label={SEAT_LABEL[state]} tone={SEAT_TONE[state]} />
            </div>
            <p className="text-xs text-fg">{role}</p>
            {result && (
              <p className="text-xs text-fg">
                {result.attempts} attempt{result.attempts === 1 ? '' : 's'} · {result.model_mode === 'MOCK_DETERMINISTIC' ? 'mock model' : 'provider model'}
              </p>
            )}
          </li>
        );
      })}
      <li aria-label={`Sentinel gate: ${GATE_LABEL[view.gate]}`}
        className={`flex min-w-0 flex-col gap-2 rounded-lg border bg-surface p-4 ${view.gate === 'pending' ? 'border-status-warning' : 'border-line'}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2 font-medium text-fg-strong"><GateIcon gate={view.gate} />Sentinel gate</span>
          <Badge label={GATE_LABEL[view.gate]} tone={GATE_TONE[view.gate]} />
        </div>
        <p className="text-xs text-fg">A person approves before any write, shell or external action.</p>
        {mission.risk && (
          <p className="text-xs text-fg">
            Risk {mission.risk.level} · {mission.risk.findings.length} finding{mission.risk.findings.length === 1 ? '' : 's'}
            {mission.risk.blocked ? ' · blocked by policy' : ''}
          </p>
        )}
      </li>
    </ul>
  );
}
