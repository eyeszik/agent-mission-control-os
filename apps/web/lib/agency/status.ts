// User-readable status mapping and tone for the Agency OS. Every status is
// shown as words; colour is a second cue, never the only one (WCAG 1.4.1).

export const STATUS_LABELS: Record<string, string> = {
  PROVIDER_GAP: 'Tool not connected',
  BLOCKED_DEPENDENCY: 'Waiting on prerequisite',
  AWAITING_APPROVAL: 'Approval required',
  RECONCILING: 'Checking outcome',
  LIVE_GATED: 'External action disabled',
  VERIFIED: 'Independently checked',
  PROPOSED: 'Proposed',
  VALIDATED: 'Validated',
  PREPARED: 'Prepared',
  AUTHORIZED: 'Ready to run',
  RESERVED: 'Budget reserved',
  DISPATCHING: 'Running',
  OBSERVING: 'Reading back the result',
  COMPLETED: 'Done and checked',
  REJECTED: 'Rejected',
  BLOCKED: 'Blocked',
  EXPIRED: 'Expired',
  CANCELLED: 'Cancelled',
  FAILED: 'Failed',
  UNKNOWN: 'Outcome unknown',
  NEEDS_HUMAN: 'Needs a person',
  NOT_IMPLEMENTED: 'Not available',
  UNAVAILABLE: 'Unavailable here',
  IMPLEMENTED: 'Available locally',
  TESTED: 'Available locally (tested)',
  VOID_DETECTED: 'No source definition',
  DONE: 'Done',
  IN_PROGRESS: 'In progress',
  NOT_STARTED: 'Not started',
  NOT_MEASURED: 'Not measured',
  ATTENTION: 'Needs attention',
  READY: 'Ready',
  READY_TO_LAUNCH: 'Ready to launch',
  NEEDS_CLARIFICATION: 'Needs clarification',
  EXECUTABLE: 'Ready to run',
  PASSED: 'Passed',
  INCONCLUSIVE: 'Inconclusive',
  ACTIVE: 'Active',
  OFFBOARDING: 'Offboarding',
  ARCHIVED: 'Archived',
  SIMULATED: 'Simulated (sandbox)',
  WOULD_RUN_WITHOUT_APPROVAL: 'Would run without approval',
  WOULD_REQUEST_APPROVAL: 'Would ask for approval',
  WOULD_BE_BLOCKED: 'Would be blocked',
  NEEDS_HUMAN_STATE: 'Needs a person',
};

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const TONES: Record<Tone, string[]> = {
  success: ['COMPLETED', 'VERIFIED', 'DONE', 'IMPLEMENTED', 'TESTED', 'PASSED', 'READY_TO_LAUNCH', 'AUTHORIZED', 'ACTIVE', 'READY',
    'EXECUTABLE', 'WOULD_RUN_WITHOUT_APPROVAL', 'approve', 'SIGNED', 'RECORDED'],
  warning: ['AWAITING_APPROVAL', 'PENDING', 'pending', 'IN_PROGRESS', 'RECONCILING', 'UNKNOWN', 'NEEDS_HUMAN', 'OFFBOARDING',
    'BLOCKED_DEPENDENCY', 'NEEDS_CLARIFICATION', 'WOULD_REQUEST_APPROVAL', 'RESERVED', 'DISPATCHING', 'OBSERVING', 'INCONCLUSIVE',
    'UNSIGNED', 'NOT_RECORDED', 'ATTENTION', 'PROVIDER_GAP'],
  danger: ['FAILED', 'REJECTED', 'BLOCKED', 'EXPIRED', 'WOULD_BE_BLOCKED', 'reject', 'stale', 'ARCHIVED'],
  info: ['LIVE_GATED', 'SIMULATED', 'NOT_MEASURED', 'VOID_DETECTED', 'NOT_IMPLEMENTED', 'UNAVAILABLE', 'CANCELLED', 'NOT_STARTED'],
  neutral: [],
};

export function toneOf(status: string | null | undefined): Tone {
  if (!status) return 'neutral';
  for (const tone of ['success', 'warning', 'danger', 'info'] as const) if (TONES[tone].includes(status)) return tone;
  return 'neutral';
}

export function labelOf(status: string | null | undefined): string {
  if (!status) return 'Unknown';
  return STATUS_LABELS[status] ?? status.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export const RISK_LABELS: Record<string, string> = {
  R0: 'R0 · View or research',
  R1: 'R1 · Local create or prepare',
  R2: 'R2 · External unpublished draft',
  R3: 'R3 · Publish or communicate',
  R4: 'R4 · Spend or budget',
  R5: 'R5 · Critical asset or data change',
  R6: 'R6 · Governance or permission change',
};

export function riskTone(risk: string | null | undefined): Tone {
  if (!risk) return 'neutral';
  const rank = Number(risk.slice(1));
  if (rank >= 5) return 'danger';
  if (rank >= 3) return 'warning';
  if (rank === 2) return 'info';
  return 'neutral';
}

export function formatMinor(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount == null) return '—';
  if (!currency) return amount === 0 ? 'No cost' : `${amount} (minor units)`;
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount / 100);
  } catch {
    return `${amount} ${currency} (minor units)`;
  }
}

export function shortHash(value: string | null | undefined, n = 12): string {
  return value ? `${value.slice(0, n)}…` : '—';
}
