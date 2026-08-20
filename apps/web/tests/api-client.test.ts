import { AgencyRunSchema } from '@amc/shared';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from '../lib/api/client';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiFetch runtime boundary', () => {
  it('rejects schema-invalid successful payloads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'not-a-uuid', status: 'not-real' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    ));

    await expect(apiFetch('/test', {}, AgencyRunSchema)).rejects.toThrow();
  });

  it('surfaces FastAPI detail errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Resource belongs to a different tenant' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      })
    ));

    await expect(apiFetch('/test')).rejects.toMatchObject({
      status: 403,
      message: 'Resource belongs to a different tenant',
    });
  });
});
