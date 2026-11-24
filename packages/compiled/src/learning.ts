/**
 * Twin of `agency/compiled/learning.py` (T23): the LearningQuarantine.
 * Append-only, hash-chained and non-authoritative. A signal aimed at a
 * protected target becomes a GovernanceProposal for human review; the ledger
 * has deliberately no update, delete or apply path.
 */
import type { PyFloat } from '@amc/kernel';
import { LearningLedgerError } from './errors';
import { semanticHash, type HashValue } from './hashing';

export const GENESIS = '0'.repeat(64);

export const ALLOWED_HEURISTICS: ReadonlySet<string> = new Set([
  'routing_ranking', 'context_requirements', 'dependency_templates', 'validator_selection', 'estimation_hints',
  'tool_reliability_recommendations', 'validated_reusable_templates',
]);
export const PROTECTED_TARGETS: ReadonlySet<string> = new Set([
  'permissions', 'n1_ownership', 'n2_lifecycle', 'n3_authority', 'approval_requirements', 'security_policy',
  'privacy_policy', 'legal_policy', 'provider_permissions', 'secrets', 'governance_thresholds',
]);

export type SignalStatus = 'QUARANTINED' | 'GOVERNANCE_PROPOSAL' | 'REJECTED';

export interface LearningSignal {
  readonly id: string;
  readonly tenant_scope: string;
  readonly run_refs: readonly string[];
  readonly observation: string;
  readonly evidence_refs: readonly string[];
  readonly target_heuristic: string;
  readonly confidence: PyFloat | null;
  readonly status: SignalStatus;
  readonly created_at: string | null;
  readonly prev_hash: string;
  readonly hash: string;
}

export interface GovernanceProposal {
  readonly signal_id: string;
  readonly target: string;
  readonly rationale: string;
  readonly requires: string;
}

const signalHash = (s: LearningSignal): string => semanticHash(s as unknown as HashValue, ['hash']);

function classify(signal: LearningSignal): SignalStatus {
  if (PROTECTED_TARGETS.has(signal.target_heuristic)) return 'GOVERNANCE_PROPOSAL';
  if (!ALLOWED_HEURISTICS.has(signal.target_heuristic)) return 'REJECTED';
  return signal.evidence_refs.length ? 'QUARANTINED' : 'REJECTED';
}

export class LearningLedger {
  private log: LearningSignal[] = [];
  readonly proposals: GovernanceProposal[] = [];

  append(signal: LearningSignal): LearningSignal {
    if (!signal.tenant_scope) throw new LearningLedgerError('tenant_scope is required');
    if (this.log.some((e) => e.id === signal.id)) throw new LearningLedgerError(`duplicate signal id ${signal.id}`);
    const status = classify(signal);
    if (PROTECTED_TARGETS.has(signal.target_heuristic)) {
      this.proposals.push({
        signal_id: signal.id, target: signal.target_heuristic, rationale: signal.observation,
        requires: 'human governance review and approval',
      });
    }
    const prev = this.log[this.log.length - 1]?.hash ?? GENESIS;
    const staged: LearningSignal = { ...signal, status, prev_hash: prev, hash: '' };
    const sealed: LearningSignal = { ...staged, hash: signalHash(staged) };
    this.log.push(sealed);
    return sealed;
  }

  /** Tenant-isolated read: no cross-tenant leakage. */
  entries(tenantScope: string): LearningSignal[] {
    return this.log.filter((e) => e.tenant_scope === tenantScope);
  }

  verifyChain(): boolean {
    let prev = GENESIS;
    for (const entry of this.log) {
      if (entry.prev_hash !== prev || entry.hash !== signalHash(entry)) return false;
      prev = entry.hash;
    }
    return true;
  }

  static replay(entries: Iterable<LearningSignal>): LearningLedger {
    const ledger = new LearningLedger();
    ledger.log = [...entries];
    if (!ledger.verifyChain()) throw new LearningLedgerError('STATE_CORRUPTION: learning ledger hash chain broken');
    return ledger;
  }
}
