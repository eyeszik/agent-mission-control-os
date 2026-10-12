"use client";

import { useCallback, useRef, useState, type ReactNode } from 'react';

// Small shared primitives for the VNEXUS studio. Tailwind token classes only;
// colours from data (palettes) are drawn as SVG fills, never inline styles.

export const inputClass =
  'w-full bg-zinc-950/50 border border-zinc-800/80 rounded-md p-2 text-sm text-zinc-200 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60';
export const buttonClass =
  'text-xs px-3 py-1.5 rounded-md border border-zinc-700 text-zinc-100 hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60';
export const tone = {
  ok: 'text-emerald-300 border-emerald-700/60',
  warn: 'text-amber-300 border-amber-700/60',
  bad: 'text-red-300 border-red-700/60',
  muted: 'text-zinc-400 border-zinc-700',
} as const;

export function stateTone(state: string): keyof typeof tone {
  if (['APPROVED', 'QC_PASSED', 'PASSED', 'VERIFIED', 'MASTER_READY', 'PROMOTED', 'WOULD_BE_PROMOTABLE', 'PROMPT_PACKAGE_READY'].includes(state)) return 'ok';
  if (['FAILED', 'REJECTED', 'BLOCKING', 'ERROR', 'WOULD_BLOCK', 'GENOME_INCOMPLETE', 'GENOME_REJECTED_BY_COMPILER', 'CANCELED'].includes(state)) return 'bad';
  if (['IN_REVIEW', 'WARNING', 'VALIDATED', 'QUEUED', 'RUNNING', 'SPEC_ONLY', 'INCOMPLETE', 'NOT_RUN', 'SIMULATED_ONLY'].includes(state)) return 'warn';
  return 'muted';
}

export function Badge({ value, label }: { value: string; label?: string }) {
  return <span className={`inline-block text-[11px] px-1.5 py-0.5 rounded-sm border ${tone[stateTone(value)]}`}>{label ?? value}</span>;
}

export function Panel({ title, description, children, actions }: { title: string; description?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-zinc-100">{title}</h3>
          {description && <p className="text-xs text-zinc-400 mt-0.5">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400 min-w-0">
      <span>{label}</span>
      {children}
      {hint && <span className="text-[11px] text-zinc-500">{hint}</span>}
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-xs text-zinc-500 border border-dashed border-zinc-800 rounded-md p-3">{children}</p>;
}

export function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-zinc-300">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect width="14" height="14" rx="3" fill={color} /></svg>
      <span>{label}</span>
    </span>
  );
}

export type AsyncState = { kind: 'idle' } | { kind: 'busy'; label: string } | { kind: 'error'; message: string } | { kind: 'done'; message: string };

/** One action at a time per area, with an honest status line. Only the latest run
 * reports: a superseded run (e.g. a load an effect re-ran) must not announce "done"
 * for work whose result was discarded. */
export function useAction() {
  const [state, setState] = useState<AsyncState>({ kind: 'idle' });
  const latest = useRef(0);
  const run = useCallback(async <T,>(label: string, fn: () => Promise<T>, done?: (r: T) => string): Promise<T | undefined> => {
    const seq = ++latest.current;
    setState({ kind: 'busy', label });
    try {
      const result = await fn();
      if (seq === latest.current) setState({ kind: 'done', message: done ? done(result) : `${label}: done` });
      return result;
    } catch (e) {
      if (seq === latest.current) setState({ kind: 'error', message: e instanceof Error ? e.message : String(e) });
      return undefined;
    }
  }, []);
  return { state, run, busy: state.kind === 'busy' };
}

export function StatusLine({ state }: { state: AsyncState }) {
  if (state.kind === 'idle') return null;
  if (state.kind === 'error') return <p role="alert" className="text-xs text-red-300">{state.message}</p>;
  return <p role="status" aria-live="polite" className={`text-xs ${state.kind === 'busy' ? 'text-zinc-400' : 'text-emerald-300'}`}>{state.kind === 'busy' ? `${state.label}…` : state.message}</p>;
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents"><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-200 break-all min-w-0">{v}</dd></div>
      ))}
    </dl>
  );
}

export const short = (s: string | null | undefined, n = 12) => (s ? (s.length > n ? `${s.slice(0, n)}…` : s) : '—');

export function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}
