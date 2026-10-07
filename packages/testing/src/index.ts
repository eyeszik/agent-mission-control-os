/**
 * Test helpers shared by workspace packages and apps/web.
 *
 * Import only from test files: this module imports `vitest`.
 */

import { type AppConfig, type EnvRecord, loadAppConfig } from '@amc/config';
import { type LogFields, type Logger, type LogLevel, type LogSink, createLogger } from '@amc/logger';
import { afterEach, vi } from 'vitest';

export interface LogRecord {
  level: LogLevel;
  message: string;
  fields?: unknown;
}

export interface TestContext {
  env: EnvRecord;
  config: AppConfig;
  logger: Logger;
  /** Every line the context logger emitted, in order. */
  logs: LogRecord[];
}

export const DEFAULT_TEST_ENV: EnvRecord = {
  NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8000',
  NEXT_PUBLIC_AUTH_MODE: 'local',
  NEXT_PUBLIC_LOG_LEVEL: 'debug',
};

/** A validated config plus a capturing logger, built from a test env. */
export function createTestContext(options: { env?: EnvRecord; name?: string } = {}): TestContext {
  const env = { ...DEFAULT_TEST_ENV, ...(options.env ?? {}) };
  const config = loadAppConfig(env);
  const logs: LogRecord[] = [];
  const capture = (level: LogLevel) => (message: unknown, fields?: unknown) => {
    logs.push({ level, message: String(message), ...(fields === undefined ? {} : { fields }) });
  };
  const sink: LogSink = { debug: capture('debug'), info: capture('info'), warn: capture('warn'), error: capture('error') };
  const logger = createLogger({ level: config.logLevel, sink, name: options.name ?? 'test' });
  return { env, config, logger, logs };
}

export interface MockResponseInit {
  status?: number;
  headers?: Record<string, string>;
}

/**
 * A real `Response` with a JSON body (or raw text when `body` is a string),
 * suitable for stubbing `fetch`.
 */
export function createMockResponse(body: unknown = null, init: MockResponseInit = {}): Response {
  const isText = typeof body === 'string';
  const headers = new Headers(init.headers ?? {});
  if (!headers.has('content-type')) headers.set('content-type', isText ? 'text/plain' : 'application/json');
  const status = init.status ?? 200;
  const payload = status === 204 || status === 304 ? null : isText ? body : JSON.stringify(body);
  return new Response(payload, { status, headers });
}

export interface VitestHookOptions {
  restoreMocks?: boolean;
  unstubGlobals?: boolean;
  unstubEnvs?: boolean;
}

/** Register afterEach hooks that undo mocks and stubs between tests. */
export function setupVitestHooks(options: VitestHookOptions = {}): void {
  const { restoreMocks = true, unstubGlobals = true, unstubEnvs = true } = options;
  afterEach(() => {
    if (restoreMocks) vi.restoreAllMocks();
    if (unstubGlobals) vi.unstubAllGlobals();
    if (unstubEnvs) vi.unstubAllEnvs();
  });
}

export type { LogFields };
