"use client";

import { LazyMotion, MotionConfig, domAnimation, m } from 'framer-motion';
import type { TimelineEvent } from '@amc/shared';
import { MOTION } from '../../lib/design/motion';
import { describeEvent, type Tone } from '../../lib/missions/council';
import type { StreamState } from '../../lib/missions/useMissionLive';
import { Badge, Empty } from '../agency/ui';

const DOT: Record<Tone, string> = {
  success: 'bg-status-success',
  warning: 'bg-status-warning',
  danger: 'bg-status-danger',
  info: 'bg-status-info',
  neutral: 'bg-line-strong',
};

const enter = { duration: MOTION.hover, ease: [...MOTION.standard] as [number, number, number, number] };

function time(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/**
 * The mission's persisted events in sequence order. New rows fade in as the
 * stream delivers them (opacity only when the user prefers reduced motion);
 * the newest event is announced once through a polite live region.
 */
export function MissionTimeline({ events, stream }: { events: TimelineEvent[]; stream: StreamState }) {
  const latest = events.length > 0 ? describeEvent(events[events.length - 1]) : null;
  return (
    <section aria-labelledby="mission-timeline-title" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="mission-timeline-title" className="text-sm font-semibold text-fg-strong">Timeline</h3>
        <Badge label={stream === 'live' ? 'Live' : stream === 'ended' ? 'Stream closed' : 'Not streaming'} tone={stream === 'live' ? 'info' : 'neutral'} />
      </div>
      <p role="status" aria-live="polite" className="sr-only">{latest ? `${latest.title}${latest.detail ? `: ${latest.detail}` : ''}` : ''}</p>
      {events.length === 0 ? (
        <Empty title="No events yet">Events appear here as each council seat runs.</Empty>
      ) : (
        <LazyMotion features={domAnimation} strict>
          <MotionConfig reducedMotion="user">
            <ol className="relative flex flex-col gap-0 border-l border-line pl-4" aria-label="Mission events">
              {events.map((e) => {
                const d = describeEvent(e);
                return (
                  <m.li key={e.sequence} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={enter}
                    className="relative flex min-w-0 flex-col gap-0.5 py-2">
                    <span aria-hidden="true" className={`absolute -left-[1.3rem] top-3.5 h-2 w-2 rounded-full ${DOT[d.tone]}`} />
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="text-sm font-medium text-fg-strong">{d.title}</span>
                      <span className="font-mono text-xs text-fg">#{e.sequence} · <time dateTime={e.observed_at}>{time(e.observed_at)}</time></span>
                    </div>
                    {d.detail && <p className="break-words text-xs text-fg">{d.detail}</p>}
                  </m.li>
                );
              })}
            </ol>
          </MotionConfig>
        </LazyMotion>
      )}
    </section>
  );
}
