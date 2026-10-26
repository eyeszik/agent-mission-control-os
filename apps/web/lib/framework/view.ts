import type { AfApplicability, AfCounts, AfGateStatus, AfTaskState } from '@amc/shared';

// Pure view helpers for the agency operating framework. Every status is shown as
// words; colour is a second cue, never the only one. The transition table mirrors
// MANUAL_TRANSITIONS in services/langgraph/agency/operating_framework/contracts.py
// (tests/framework-view.test.ts pins it): the UI offers a move only if the server
// would accept it, and the server still decides.

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export const STATE_LABEL: Record<AfTaskState, string> = {
  BACKLOG: 'Backlog',
  READY: 'Ready',
  ACTIVE: 'In progress',
  IN_REVIEW: 'In review',
  VERIFIED: 'Verified',
  APPROVED: 'Approved',
  BLOCKED: 'Blocked',
  INVALIDATED: 'Invalidated',
  NOT_APPLICABLE: 'Not applicable',
};

export const STATE_TONE: Record<AfTaskState, Tone> = {
  BACKLOG: 'neutral',
  READY: 'info',
  ACTIVE: 'info',
  IN_REVIEW: 'warning',
  VERIFIED: 'success',
  APPROVED: 'success',
  BLOCKED: 'danger',
  INVALIDATED: 'danger',
  NOT_APPLICABLE: 'neutral',
};

export const APPLICABILITY_LABEL: Record<AfApplicability, string> = {
  UNASSESSED: 'Not assessed',
  REQUIRED: 'Required',
  CONDITIONAL: 'Conditional',
  NOT_APPLICABLE: 'Not applicable',
};

export const GATE_LABEL: Record<AfGateStatus, string> = {
  NOT_ASSESSED: 'Not assessed',
  BLOCKED: 'Blocked',
  NEEDS_HUMAN: 'Ready for a reviewer',
  APPROVAL_PENDING: 'Approval pending',
  PASSED: 'Passed',
  STALE: 'Approval stale',
};

export const GATE_TONE: Record<AfGateStatus, Tone> = {
  NOT_ASSESSED: 'neutral',
  BLOCKED: 'danger',
  NEEDS_HUMAN: 'warning',
  APPROVAL_PENDING: 'warning',
  PASSED: 'success',
  STALE: 'danger',
};

export const GATE_TITLE: Record<string, string> = {
  '01_DISCOVERY': 'Discovery',
  '02_STRATEGY': 'Strategy',
  '03_PRODUCTION': 'Production',
  '04_ACTIVATION': 'Activation',
  '05_GROWTH': 'Growth',
};

export const MANUAL_TRANSITIONS: Record<AfTaskState, AfTaskState[]> = {
  BACKLOG: ['READY', 'BLOCKED'],
  READY: ['ACTIVE', 'BACKLOG', 'BLOCKED'],
  ACTIVE: ['IN_REVIEW', 'READY', 'BLOCKED'],
  IN_REVIEW: ['ACTIVE', 'BLOCKED'],
  VERIFIED: ['ACTIVE', 'BLOCKED'],
  INVALIDATED: ['ACTIVE'],
  BLOCKED: [],
  APPROVED: [],
  NOT_APPLICABLE: [],
};

export const MOVE_LABEL: Partial<Record<AfTaskState, string>> = {
  READY: 'Mark ready',
  ACTIVE: 'Start work',
  IN_REVIEW: 'Submit for review',
  BACKLOG: 'Back to backlog',
  BLOCKED: 'Block',
};

/** "3 of 8 required verified", or the honest "Not measured" when nothing is required. */
export function ratioLabel(c: AfCounts): string {
  if (c.required_verified_ratio === 'NOT_MEASURED') {
    return c.unassessed > 0 ? `Not measured · ${c.unassessed} not assessed` : 'Not measured · nothing required';
  }
  return `${c.required_verified} of ${c.required} required verified`;
}

export function ratioPercent(c: AfCounts): number | null {
  return c.required_verified_ratio === 'NOT_MEASURED' ? null : Math.round(c.required_verified_ratio * 100);
}

export const shortHash = (h: string | null | undefined) => (h ? `${h.slice(0, 12)}…` : '—');

/** Parse one ref per line; blank lines are ignored. */
export const parseRefs = (text: string): string[] =>
  text.split('\n').map((s) => s.trim()).filter(Boolean);
