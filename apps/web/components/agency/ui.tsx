"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { labelOf, toneOf, type Tone } from '../../lib/agency/status';
import { useAgencyStore } from '../../lib/stores/agencyStore';

// Agency OS primitives. Semantic token classes only (bg-surface, text-fg,
// border-line, text-status-*), so every surface follows data-amc-theme.

export const focusRing = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1 focus-visible:ring-offset-canvas';
export const inputClass = `w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-fg-strong placeholder:text-fg-muted ${focusRing}`;

const BUTTON = {
  primary: 'bg-accent text-canvas border border-accent hover:opacity-90',
  secondary: 'bg-surface text-fg-strong border border-line-strong hover:bg-surface-raised',
  ghost: 'text-fg-strong border border-transparent hover:bg-surface-raised',
  danger: 'bg-surface text-status-danger border border-status-danger hover:bg-surface-raised',
} as const;

export function Button({ variant = 'secondary', children, className = '', ...rest }:
  React.ComponentProps<'button'> & { variant?: keyof typeof BUTTON }) {
  return (
    <button type="button" {...rest}
      className={`inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON[variant]} ${focusRing} ${className}`}>
      {children}
    </button>
  );
}

const TONE_CLASS: Record<Tone, string> = {
  success: 'text-status-success border-status-success',
  warning: 'text-status-warning border-status-warning',
  danger: 'text-status-danger border-status-danger',
  info: 'text-status-info border-status-info',
  neutral: 'text-fg border-line-strong',
};

export function Badge({ status, label, tone, wrap = false }: { status?: string | null; label?: string; tone?: Tone; wrap?: boolean }) {
  const t = tone ?? toneOf(status);
  return (
    <span className={`inline-flex items-center ${wrap ? 'max-w-full break-words' : 'whitespace-nowrap'} rounded border px-1.5 py-0.5 text-xs ${TONE_CLASS[t]}`} title={status ?? undefined}>
      {label ?? labelOf(status)}
    </span>
  );
}

export function Card({ title, description, actions, children, id }: { title?: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={title && id ? `${id}-title` : undefined} aria-label={title && !id ? title : undefined}
      className="flex min-w-0 flex-col gap-4 rounded-lg border border-line bg-surface p-4 sm:p-6">
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 id={id ? `${id}-title` : undefined} className="text-base font-semibold text-fg-strong">{title}</h2>}
            {description && <p className="mt-1 text-sm text-fg">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={htmlFor} className="text-sm font-medium text-fg-strong">{label}</label>
      {children}
      {hint && <p className="text-xs text-fg">{hint}</p>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong p-6 text-center">
      <p className="text-sm font-medium text-fg-strong">{title}</p>
      {children && <div className="mt-1 text-sm text-fg">{children}</div>}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="flex flex-col gap-2">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="h-4 animate-pulse rounded bg-surface-raised" />)}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-status-danger p-3 text-sm text-status-danger">
      <span>{error}</span>
      {onRetry && <Button variant="ghost" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function StatusNote({ children }: { children: ReactNode }) {
  return <p role="status" className="rounded-md border border-line-strong p-3 text-sm text-fg-strong">{children}</p>;
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-fg">{k}</dt>
          <dd className="min-w-0 break-words text-fg-strong">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Hash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-fg">—</span>;
  return <code className="break-all font-mono text-xs text-fg-strong" title={value}>{value.length > 20 ? `${value.slice(0, 16)}…` : value}</code>;
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

/** Load data with loading/error state; reloads on the store's refresh tick. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const tick = useAgencyStore((s) => s.refreshTick);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [local, setLocal] = useState(0);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    let alive = true;
    setLoading(true);
    loader.current()
      .then((value) => { if (alive) { setData(value); setError(null); } })
      .catch((err) => { if (alive) setError(errorMessage(err)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, local, ...deps]);
  const reload = useCallback(() => setLocal((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Run one async action at a time, with a status message and an error. */
export function useRunner(): { busy: boolean; message: string | null; error: string | null; run: (label: string, fn: () => Promise<string | void>) => Promise<void>; clear: () => void } {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (label: string, fn: () => Promise<string | void>) => {
    setBusy(true);
    setError(null);
    setMessage(`${label}…`);
    try {
      const result = await fn();
      setMessage(result ?? `${label}: done`);
    } catch (err) {
      setMessage(null);
      setError(`${label}: ${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  }, []);
  const clear = useCallback(() => { setMessage(null); setError(null); }, []);
  return { busy, message, error, run, clear };
}

export function RunnerOutput({ message, error }: { message: string | null; error: string | null }) {
  return (
    <>
      {message && <StatusNote>{message}</StatusNote>}
      {error && <ErrorNote error={error} />}
    </>
  );
}
