"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CONTENT_TRANSITIONS, type ContentItem, type ContentState } from '@amc/shared';
import { getCalendar, transitionContentItem, type CalendarView } from '../../lib/api/projects';
import { useProjectStore } from '../../lib/stores/projectStore';

// Operator actions only. Publication states (DUE → VERIFIED) are entered by
// the scheduler and the publication worker, never by a button.
const OPERATOR_TARGETS: ContentState[] = ['PLANNED', 'IN_PRODUCTION', 'REVIEW', 'APPROVED', 'READY', 'ARCHIVED'];

function ItemRow({ item, onMove }: { item: ContentItem; onMove: (item: ContentItem, target: ContentState) => void }) {
  const targets = CONTENT_TRANSITIONS[item.state].filter((target) => OPERATOR_TARGETS.includes(target));
  return (
    <li className="text-xs border-b border-zinc-800/40 py-1.5 last:border-0 flex flex-col gap-1">
      <div className="flex justify-between gap-2">
        <span className="text-zinc-200 truncate">{item.title}</span>
        <span className="font-mono text-zinc-400 shrink-0">{item.state} · v{item.version}</span>
      </div>
      {targets.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {targets.map((target) => (
            <button key={target} type="button" onClick={() => onMove(item, target)}
              className="px-1.5 py-0.5 rounded border border-zinc-700 text-zinc-300 hover:text-zinc-100">
              → {target}
            </button>
          ))}
        </div>
      )}
    </li>
  );
}

export function ContentCalendarPanel() {
  const projectId = useProjectStore((state) => state.activeProjectId);
  const [view, setView] = useState<CalendarView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId) {
      setView(null);
      return;
    }
    try {
      setView(await getCalendar(projectId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load calendar');
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // ⚡ Bolt: upcoming window computed once per payload.
  const upcoming = useMemo(() => {
    const now = Date.now();
    const horizon = now + 14 * 24 * 3600 * 1000;
    return (view?.slots ?? []).filter((slot) => {
      const at = Date.parse(slot.scheduled_for);
      return at >= now && at < horizon && slot.state !== 'cancelled';
    });
  }, [view]);
  const blocked = useMemo(() => (view?.jobs ?? []).filter((job) => job.status === 'BLOCKED'), [view]);

  const onMove = async (item: ContentItem, target: ContentState) => {
    if (!projectId) return;
    try {
      await transitionContentItem(projectId, item.content_item_id, target, item.version);
      await refresh();
    } catch (err) {
      // Approval separation of duties and lifecycle guards surface here.
      setError(err instanceof Error ? err.message : 'Transition refused');
    }
  };

  if (!projectId) return null;
  return (
    <section aria-labelledby="content-calendar-heading" className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3 flex flex-col gap-3 min-h-0">
      <h2 id="content-calendar-heading" className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Content &amp; Calendar</h2>
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div><p className="text-zinc-500">Next 14 days</p><p className="text-zinc-100 font-mono">{upcoming.length} slots</p></div>
        <div><p className="text-zinc-500">Blocked jobs</p><p className={`font-mono ${blocked.length ? 'text-amber-300' : 'text-zinc-100'}`}>{blocked.length}</p></div>
      </div>
      {blocked.length > 0 && (
        <ul className="text-xs flex flex-col gap-1">
          {blocked.map((job) => (
            <li key={job.job_id} className="text-amber-300 font-mono truncate" title={job.block_reasons.join(', ')}>
              {job.job_kind} · {job.block_reasons.join(', ')}
            </li>
          ))}
        </ul>
      )}
      <ul className="overflow-auto max-h-64">{(view?.items ?? []).map((item) => <ItemRow key={item.content_item_id} item={item} onMove={onMove} />)}</ul>
    </section>
  );
}
