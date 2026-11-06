/**
 * Leveled console logger.
 *
 * Fields are passed to the console as a structured object (readable in both
 * browser devtools and Node). Values under secret-shaped keys are redacted
 * and Error objects are reduced to name/message so tokens, keys or stack
 * internals never reach a log line by accident.
 */

import { AMC_LOG_LEVELS, type AmcLogLevel, isOneOf } from '@amc/constants';

export type LogLevel = AmcLogLevel;
export const LOG_LEVELS = AMC_LOG_LEVELS;

export type LogFields = Record<string, unknown>;

export interface Logger {
  readonly level: LogLevel;
  debug(message: string, fields?: LogFields): void;
  info(message: string, fields?: LogFields): void;
  warn(message: string, fields?: LogFields): void;
  error(message: string, fields?: LogFields): void;
  child(bindings: LogFields): Logger;
}

/** Where log lines go. `console` satisfies it; tests pass a capturing sink. */
export interface LogSink {
  debug(...args: unknown[]): void;
  info(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error(...args: unknown[]): void;
}

export interface LoggerOptions {
  name?: string;
  level?: LogLevel;
  bindings?: LogFields;
  sink?: LogSink;
}

const RANK: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const SECRET_KEY = /(token|secret|password|passwd|authorization|cookie|api[-_]?key|private[-_]?key|session)/i;
export const REDACTED = '[REDACTED]';

/** Accepts a level string from config; anything unknown falls back. */
export function parseLogLevel(value: unknown, fallback: LogLevel = 'info'): LogLevel {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : value;
  if (normalized === 'warning') return 'warn';
  return isOneOf(LOG_LEVELS, normalized) ? normalized : fallback;
}

function sanitize(value: unknown, depth = 0): unknown {
  if (value instanceof Error) return { name: value.name, message: value.message };
  if (depth >= 4 || value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((item) => sanitize(item, depth + 1));
  const out: LogFields = {};
  for (const [key, item] of Object.entries(value as LogFields)) {
    out[key] = SECRET_KEY.test(key) ? REDACTED : sanitize(item, depth + 1);
  }
  return out;
}

export class ConsoleLogger implements Logger {
  readonly level: LogLevel;
  private readonly name: string | undefined;
  private readonly bindings: LogFields;
  private readonly sink: LogSink;

  constructor(options: LoggerOptions = {}) {
    this.level = options.level ?? 'info';
    this.name = options.name;
    this.bindings = options.bindings ?? {};
    this.sink = options.sink ?? console;
  }

  debug(message: string, fields?: LogFields): void {
    this.write('debug', message, fields);
  }

  info(message: string, fields?: LogFields): void {
    this.write('info', message, fields);
  }

  warn(message: string, fields?: LogFields): void {
    this.write('warn', message, fields);
  }

  error(message: string, fields?: LogFields): void {
    this.write('error', message, fields);
  }

  child(bindings: LogFields): Logger {
    return new ConsoleLogger({
      level: this.level,
      sink: this.sink,
      bindings: { ...this.bindings, ...bindings },
      ...(this.name === undefined ? {} : { name: this.name }),
    });
  }

  private write(level: LogLevel, message: string, fields?: LogFields): void {
    if (RANK[level] < RANK[this.level]) return;
    const prefix = this.name ? `[${this.name}] ${message}` : message;
    const merged = { ...this.bindings, ...(fields ?? {}) };
    if (Object.keys(merged).length === 0) this.sink[level](prefix);
    else this.sink[level](prefix, sanitize(merged));
  }
}

export function createLogger(options: LoggerOptions = {}): Logger {
  return new ConsoleLogger(options);
}
