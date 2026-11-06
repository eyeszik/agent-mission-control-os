import { AMC_AGENCY_RUN_STATES } from '@amc/constants';
import { isAMCError } from '@amc/errors';
import { AgencyRunStatusSchema } from '@amc/shared';
import { createMockResponse, setupVitestHooks } from '@amc/testing';
import { describe, expect, it, vi } from 'vitest';
import { ServiceError, apiFetch } from '../lib/api/client';
import { getAppConfig, usesSupabaseAuth } from '../lib/config';

setupVitestHooks();

describe('web app configuration', () => {
  it('defaults to the local backend and auth mode', () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', '');
    vi.stubEnv('NEXT_PUBLIC_AUTH_MODE', '');
    expect(getAppConfig()).toMatchObject({ apiBaseUrl: 'http://localhost:8000', authMode: 'local', supabase: null });
    expect(usesSupabaseAuth()).toBe(false);
  });

  it('reads public env values and rejects an unknown auth mode', () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test');
    vi.stubEnv('NEXT_PUBLIC_AUTH_MODE', 'supabase');
    expect(getAppConfig().apiBaseUrl).toBe('https://api.example.test');
    expect(usesSupabaseAuth()).toBe(true);
    vi.stubEnv('NEXT_PUBLIC_AUTH_MODE', 'anonymous');
    expect(() => getAppConfig()).toThrow(/NEXT_PUBLIC_AUTH_MODE/);
  });

  it('calls the configured base URL', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test');
    const fetchMock = vi.fn().mockResolvedValue(createMockResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/health');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('https://api.example.test/health');
  });

  it('raises ServiceError as an AMCError and reads the AMC envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      createMockResponse({ detail: 'stale', error: { code: 'APPROVAL_STALE', message: 'Approval is stale', status: 409 } }, { status: 409 }),
    ));
    const error = await apiFetch('/approvals/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ServiceError);
    expect(isAMCError(error)).toBe(true);
    expect(error).toMatchObject({ status: 409, code: 'APPROVAL_STALE', message: 'Approval is stale' });
  });

  it('keeps run-state constants in step with the shared schema', () => {
    expect([...AMC_AGENCY_RUN_STATES]).toEqual(AgencyRunStatusSchema.options);
  });
});
