import type { CouncilSeat, CouncilStreamEvent, MissionStatus, TimelineEvent } from '@amc/shared';

// Pure view-model for a council mission: the timeline is the run's persisted
// events, merged by sequence (replay-safe: the REST page and the SSE stream may
// overlap), and seat cards are derived from those events only. Nothing here
// invents progress; a seat is "running" only after its SEAT_STARTED event.

export type SeatState = 'waiting' | 'running' | 'done' | 'skipped' | 'blocked';
export type GateState = 'none' | 'pending' | 'approved' | 'rejected';
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export interface CouncilView {
  seats: Record<CouncilSeat, SeatState>;
  gate: GateState;
  terminal: 'completed' | 'rejected' | 'blocked' | 'failed' | 'cancelled' | null;
  lastSequence: number;
}

export const SEATS: { seat: CouncilSeat; name: string; role: string }[] = [
  { seat: 'george', name: 'George', role: 'Mission commander: goals, architecture, task graph' },
  { seat: 'fable', name: 'Fable/Cipher', role: 'Sentinel: security, permissions, secrets, risk' },
  { seat: 'arty', name: 'Arty', role: 'Maker: validated UI and code scaffold' },
];

export const STATUS_LABEL: Record<MissionStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  needs_approval: 'Awaiting approval',
  resuming: 'Resuming',
  completed: 'Completed',
  rejected: 'Rejected',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export const STATUS_TONE: Record<MissionStatus, Tone> = {
  queued: 'neutral',
  running: 'info',
  needs_approval: 'warning',
  resuming: 'info',
  completed: 'success',
  rejected: 'danger',
  failed: 'danger',
  cancelled: 'neutral',
};

export function fromStream(event: CouncilStreamEvent): TimelineEvent {
  return {
    sequence: event.sequence,
    event_type: event.event_type,
    node_id: event.node_id,
    observed_at: event.observed_at,
    payload: event.safe_payload,
  };
}

/** Union by sequence, ascending. Re-delivered events (stream replay, refetch) are idempotent. */
export function mergeEvents(current: TimelineEvent[], incoming: TimelineEvent[]): TimelineEvent[] {
  if (incoming.length === 0) return current;
  const bySeq = new Map<number, TimelineEvent>();
  for (const e of current) bySeq.set(e.sequence, e);
  let changed = false;
  for (const e of incoming) {
    if (!bySeq.has(e.sequence)) {
      bySeq.set(e.sequence, e);
      changed = true;
    }
  }
  if (!changed) return current;
  return [...bySeq.values()].sort((a, b) => a.sequence - b.sequence);
}

export function deriveCouncil(events: TimelineEvent[]): CouncilView {
  const seats: Record<CouncilSeat, SeatState> = { george: 'waiting', fable: 'waiting', arty: 'waiting' };
  let gate: GateState = 'none';
  let terminal: CouncilView['terminal'] = null;
  let lastSequence = -1;
  for (const e of events) {
    lastSequence = Math.max(lastSequence, e.sequence);
    const seat = e.node_id as CouncilSeat | null;
    switch (e.event_type) {
      case 'SEAT_STARTED':
        if (seat && seat in seats) seats[seat] = 'running';
        break;
      case 'SEAT_COMPLETED':
      case 'RISK_ASSESSED':
        if (seat && seat in seats) seats[seat] = 'done';
        break;
      case 'APPROVAL_REQUIRED':
        gate = 'pending';
        break;
      case 'APPROVAL_APPLIED':
        gate = e.payload.decision === 'approve' ? 'approved' : 'rejected';
        break;
      case 'MISSION_COMPLETED':
        terminal = 'completed';
        break;
      case 'MISSION_REJECTED':
        terminal = 'rejected';
        if (seats.arty === 'waiting') seats.arty = 'skipped';
        break;
      case 'MISSION_BLOCKED':
        terminal = 'blocked';
        seats.fable = 'blocked';
        if (seats.arty === 'waiting') seats.arty = 'skipped';
        break;
      case 'MISSION_FAILED':
        terminal = 'failed';
        for (const s of Object.keys(seats) as CouncilSeat[]) if (seats[s] === 'running') seats[s] = 'blocked';
        break;
      case 'MISSION_RETRYING':
      case 'MISSION_RECOVERING':
        terminal = null;
        break;
      case 'MISSION_CANCELLED':
        terminal = 'cancelled';
        break;
    }
  }
  return { seats, gate, terminal, lastSequence };
}

const TITLES: Record<string, string> = {
  MISSION_QUEUED: 'Mission queued',
  MISSION_STARTED: 'Council convened',
  SEAT_STARTED: 'Seat started',
  SEAT_COMPLETED: 'Seat finished',
  RISK_ASSESSED: 'Security review finished',
  CHECKPOINT_SAVED: 'Checkpoint saved',
  APPROVAL_REQUIRED: 'Sentinel gate: approval required',
  approval_decided: 'Reviewer decided',
  MISSION_RESUMING: 'Resuming from checkpoint',
  APPROVAL_APPLIED: 'Decision applied at the gate',
  TOOL_INVOKED: 'Approved tool ran',
  MISSION_COMPLETED: 'Mission completed',
  MISSION_REJECTED: 'Mission rejected',
  MISSION_BLOCKED: 'Blocked by policy',
  MISSION_FAILED: 'Mission failed',
  CANCEL_REQUESTED: 'Cancellation requested',
  MISSION_CANCELLED: 'Mission cancelled',
  MISSION_RETRYING: 'Retrying from checkpoint',
  MISSION_RECOVERING: 'Recovering after interruption',
};

const SEAT_NAME: Record<string, string> = { george: 'George', fable: 'Fable/Cipher', arty: 'Arty', sentinel_gate: 'Sentinel' };

export function describeEvent(e: TimelineEvent): { title: string; detail: string; tone: Tone } {
  const p = e.payload as Record<string, unknown>;
  const who = e.node_id ? SEAT_NAME[e.node_id] ?? e.node_id : null;
  const title = `${TITLES[e.event_type] ?? e.event_type}${who && e.event_type.startsWith('SEAT') ? ` · ${who}` : ''}`;
  let detail = '';
  let tone: Tone = 'neutral';
  switch (e.event_type) {
    case 'SEAT_COMPLETED':
      detail = String(p.summary ?? '');
      tone = 'success';
      break;
    case 'RISK_ASSESSED': {
      const findings = Array.isArray(p.findings) ? (p.findings as { code: string }[]).map((f) => f.code).join(', ') : '';
      detail = `Risk ${String(p.level)}${findings ? ` · ${findings}` : ''}${p.requires_approval ? ' · approval required' : ''}`;
      tone = p.level === 'HIGH' || p.level === 'CRITICAL' ? 'danger' : 'warning';
      break;
    }
    case 'APPROVAL_REQUIRED':
      detail = `${(p.requested_actions as unknown[] | undefined)?.length ?? 0} requested action(s) at risk ${String(p.risk_level)}`;
      tone = 'warning';
      break;
    case 'approval_decided':
    case 'APPROVAL_APPLIED':
      detail = `${String(p.decision)}${p.reviewer ? ` by ${String(p.reviewer)}` : ''}${p.reason ? ` · ${String(p.reason)}` : ''}`;
      tone = p.decision === 'approve' ? 'success' : 'danger';
      break;
    case 'TOOL_INVOKED':
      detail = `${String(p.tool_id)} wrote ${(p.written as unknown[] | undefined)?.length ?? 0} file(s)`;
      tone = 'info';
      break;
    case 'MISSION_COMPLETED':
      tone = 'success';
      detail = `${(p.components as unknown[] | undefined)?.length ?? 0} component(s) in the scaffold`;
      break;
    case 'MISSION_FAILED':
      detail = String(p.code ?? '');
      tone = 'danger';
      break;
    case 'MISSION_REJECTED':
    case 'MISSION_BLOCKED':
      detail = String(p.reason ?? (Array.isArray(p.findings) ? (p.findings as string[]).join(', ') : ''));
      tone = 'danger';
      break;
    case 'CHECKPOINT_SAVED':
      detail = `#${String(p.seq)} · ${String(p.phase)}${p.native_checkpoint_id ? ' · LangGraph checkpoint' : ''}`;
      break;
    case 'MISSION_QUEUED':
      detail = `${String(p.engine)} engine · ${p.model_mode === 'MOCK_DETERMINISTIC' ? 'deterministic mock model' : 'model provider'}`;
      break;
  }
  return { title, detail, tone };
}

export const isActive = (status: MissionStatus) => status === 'queued' || status === 'running' || status === 'resuming';
