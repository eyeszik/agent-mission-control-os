import type { AgencyRun } from '@amc/shared';

type ProvenanceEntry = NonNullable<AgencyRun['generation_provenance']>[number];

export type AIInvolvement = 'AI_GENERATED' | 'PARTIALLY_AI_GENERATED' | 'FALLBACK_TEMPLATE' | 'NOT_GENERATED' | 'UNKNOWN';
export type TrustTone = 'provider' | 'degraded' | 'unavailable';

export interface ProvenanceSummary {
  involvement: AIInvolvement;
  label: string;
  tone: TrustTone;
  /** Provider/model pairs exactly as reported by the backend; never inferred. */
  providers: string[];
  /** Per-stage lines, e.g. "brand_strategy: fallback template (degraded)". */
  stages: string[];
  reviewStatus: string;
  /** The backend has no calibrated confidence contract, so none is shown. */
  confidence: 'Confidence not measured';
}

const NON_PROVIDER_LABEL: Record<Exclude<ProvenanceEntry['mode'], 'PROVIDER_SUCCESS'>, string> = {
  FALLBACK_DEGRADED: 'fallback template (degraded)',
  VALIDATION_FAILED: 'model output failed validation; fallback used',
  PROVIDER_FAILED: 'provider call failed; fallback used',
  BLOCKED: 'generation blocked',
};

function providerLabel(entry: ProvenanceEntry): string {
  if (entry.provider && entry.model) return `${entry.provider} / ${entry.model}`;
  if (entry.provider) return `${entry.provider} / model not disclosed`;
  return 'Provider not disclosed';
}

/**
 * Summarize backend-reported generation provenance truthfully.
 *
 * Rules: only PROVIDER_SUCCESS counts as AI output; every other mode is named
 * for what it is. Nothing is inferred when the backend reports nothing, and no
 * numeric confidence is ever produced.
 */
export function summarizeProvenance(
  entries: readonly ProvenanceEntry[] | undefined,
  options: { pendingApproval: boolean }
): ProvenanceSummary {
  const reviewStatus = options.pendingApproval ? 'Awaiting human approval' : 'Not yet reviewed';
  const base = { reviewStatus, confidence: 'Confidence not measured' as const };
  if (!entries || entries.length === 0) {
    return {
      ...base,
      involvement: 'UNKNOWN',
      label: 'AI involvement not reported',
      tone: 'unavailable',
      providers: [],
      stages: [],
    };
  }

  const succeeded = entries.filter((entry) => entry.mode === 'PROVIDER_SUCCESS');
  const providers = Array.from(new Set(succeeded.map(providerLabel)));
  const stages = entries.map((entry) =>
    entry.mode === 'PROVIDER_SUCCESS'
      ? `${entry.task}: AI-generated (${providerLabel(entry)})`
      : `${entry.task}: ${NON_PROVIDER_LABEL[entry.mode]}`
  );

  if (succeeded.length === entries.length) {
    return { ...base, involvement: 'AI_GENERATED', label: 'AI-generated', tone: 'provider', providers, stages };
  }
  if (succeeded.length > 0) {
    return {
      ...base,
      involvement: 'PARTIALLY_AI_GENERATED',
      label: `Partially AI-generated (${succeeded.length} of ${entries.length} stages)`,
      tone: 'degraded',
      providers,
      stages,
    };
  }
  if (entries.every((entry) => entry.mode === 'BLOCKED')) {
    return { ...base, involvement: 'NOT_GENERATED', label: 'Generation blocked', tone: 'unavailable', providers: [], stages };
  }
  return {
    ...base,
    involvement: 'FALLBACK_TEMPLATE',
    label: 'Fallback template — not AI output',
    tone: 'degraded',
    providers: [],
    stages,
  };
}
