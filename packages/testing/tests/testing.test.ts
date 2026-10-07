import { describe, expect, it, vi } from 'vitest';
import { createMockResponse, createTestContext, setupVitestHooks } from '../src/index.js';

setupVitestHooks();

describe('@amc/testing', () => {
  it('builds a validated context with a capturing logger', () => {
    const ctx = createTestContext({ env: { NEXT_PUBLIC_AUTH_MODE: 'supabase' } });
    expect(ctx.config.authMode).toBe('supabase');
    expect(ctx.config.apiBaseUrl).toBe('http://127.0.0.1:8000');
    ctx.logger.debug('hello', { token: 't' });
    expect(ctx.logs).toEqual([{ level: 'debug', message: '[test] hello', fields: { token: '[REDACTED]' } }]);
  });

  it('creates real Responses for fetch stubs', async () => {
    const json = createMockResponse({ ok: true }, { status: 201 });
    expect(json.status).toBe(201);
    expect(json.headers.get('content-type')).toBe('application/json');
    expect(await json.json()).toEqual({ ok: true });
    expect(await createMockResponse('plain').text()).toBe('plain');
    expect(createMockResponse(null, { status: 204 }).body).toBeNull();
  });

  it('restores stubbed globals between tests (part 1)', () => {
    vi.stubGlobal('fetch', vi.fn());
    expect(vi.isMockFunction(globalThis.fetch)).toBe(true);
  });

  it('restores stubbed globals between tests (part 2)', () => {
    expect(vi.isMockFunction(globalThis.fetch)).toBe(false);
  });
});
