"use client";

import { createContext, useContext, type ReactNode } from 'react';
import { AlertTriangle, Ban, Cpu } from 'lucide-react';
import type { ProvenanceSummary, TrustTone } from '../../lib/ai/provenance';

// One provenance scope per AI response: a nested envelope renders its children
// only, so a response can never carry two (possibly contradicting) labels.
const AITrustScope = createContext(false);

const TONE_CLASS: Record<TrustTone, string> = {
  provider: 'text-ai-trust-provider',
  degraded: 'text-ai-trust-degraded',
  unavailable: 'text-ai-trust-unavailable',
};

const TONE_ICON: Record<TrustTone, typeof Cpu> = {
  provider: Cpu,
  degraded: AlertTriangle,
  unavailable: Ban,
};

export function AITrustEnvelope({
  summary,
  children,
}: {
  summary: ProvenanceSummary;
  children?: ReactNode;
}) {
  const insideScope = useContext(AITrustScope);
  if (insideScope) return <>{children}</>;

  const Icon = TONE_ICON[summary.tone];
  return (
    <AITrustScope.Provider value={true}>
      <section
        aria-label="AI provenance"
        data-ai-trust-scope=""
        className="rounded-ai-trust border border-ai-trust-border bg-ai-trust-surface p-3 flex flex-col gap-2"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${TONE_CLASS[summary.tone]}`}>
            <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
            {summary.label}
          </span>
          <span className="text-xs text-ai-trust-detail">{summary.reviewStatus}</span>
          <span className="text-xs text-ai-trust-detail">{summary.confidence}</span>
        </div>
        <p className="text-xs text-ai-trust-detail break-words">
          {summary.providers.length > 0 ? `Provider: ${summary.providers.join(', ')}` : 'Provider: none reported'}
        </p>
        {summary.stages.length > 0 && (
          <details className="text-xs text-ai-trust-detail">
            <summary className="cursor-pointer rounded-sm text-ai-trust-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus">
              Per-stage provenance ({summary.stages.length})
            </summary>
            <ul className="mt-1 flex flex-col gap-0.5 break-words">
              {summary.stages.map((stage) => (
                <li key={stage}>{stage}</li>
              ))}
            </ul>
          </details>
        )}
        {children}
      </section>
    </AITrustScope.Provider>
  );
}
