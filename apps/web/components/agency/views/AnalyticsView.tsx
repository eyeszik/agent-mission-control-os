"use client";

import { getAnalytics } from '../../../lib/api/agencyOs';
import { labelOf } from '../../../lib/agency/status';
import { useAgencyStore } from '../../../lib/stores/agencyStore';
import { Badge, Card, ErrorNote, Skeleton, useLoad } from '../ui';

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-fg">—</span>;
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-fg">None</span>;
    return (
      <ul className="flex flex-wrap gap-2">
        {entries.map(([k, v]) => <li key={k}><Badge status={k} label={`${labelOf(k)}: ${String(v)}`} /></li>)}
      </ul>
    );
  }
  return <span className="text-2xl font-semibold text-fg-strong">{String(value)}</span>;
}

export function AnalyticsView() {
  const projectId = useAgencyStore((s) => s.projectId);
  const analytics = useLoad(() => getAnalytics(projectId ?? undefined), [projectId]);
  return (
    <Card id="analytics" title="Analytics" description="Counts of stored records with their source. Nothing here is estimated, forecast or simulated.">
      {analytics.error && <ErrorNote error={analytics.error} onRetry={analytics.reload} />}
      {!analytics.data && !analytics.error && <Skeleton lines={4} />}
      {analytics.data && (
        <>
          <ul className="grid gap-4 md:grid-cols-2">
            {analytics.data.metrics.map((m) => (
              <li key={m.metric} className="flex flex-col gap-2 rounded-md border border-line p-4">
                <p className="text-sm font-medium text-fg-strong">{labelOf(m.metric)}</p>
                {m.status === 'NOT_MEASURED' ? <Badge status="NOT_MEASURED" /> : <Value value={m.value} />}
                <p className="text-xs text-fg">{m.definition}{m.source ? ` · source: ${m.source}` : ''}</p>
              </li>
            ))}
          </ul>
          <p className="text-xs text-fg">As of {new Date(analytics.data.as_of).toLocaleString()} · scope: {analytics.data.scope}. {analytics.data.note}</p>
        </>
      )}
    </Card>
  );
}
