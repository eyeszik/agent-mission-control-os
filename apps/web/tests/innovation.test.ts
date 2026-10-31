import { afterEach, describe, expect, it, vi } from 'vitest';
import { controlInnovationRun, createInnovationRun, getInnovationRun } from '../lib/api/innovation';

const malformed = () => new Response(JSON.stringify({ forged_approval: true }), { status: 200 });
afterEach(() => vi.unstubAllGlobals());

describe('Innovation Foundry API boundary', () => {
  it('rejects malformed persisted run responses and encodes project/run identifiers', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) => malformed());
    vi.stubGlobal('fetch', fetcher);
    await expect(getInnovationRun('project/a', 'run/b')).rejects.toThrow();
    expect(String(fetcher.mock.calls[0][0])).toContain('/innovation/projects/project%2Fa/runs/run%2Fb');
  });

  it('sends a stable submission key and explicit simulation without authority fields', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) => malformed());
    vi.stubGlobal('fetch', fetcher);
    const brief = { objective: 'Fictional innovation brief', mode: 'GENERAL' as const, provider: 'simulated' as const, constraints: [] };
    await expect(createInnovationRun('p', brief, 'retry-stable-key')).rejects.toThrow();
    const options = fetcher.mock.calls[0][1];
    expect(new Headers(options.headers).get('Idempotency-Key')).toBe('retry-stable-key');
    expect(JSON.parse(String(options.body))).toEqual(brief);
  });

  it('binds controls to the displayed version without client authority fields', async () => {
    const fetcher = vi.fn(async (_url: string, _options: RequestInit) => malformed());
    vi.stubGlobal('fetch', fetcher);
    await expect(controlInnovationRun('p', 'r', 4, 'cancel')).rejects.toThrow();
    expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual({ expected_version: 4, action: 'cancel' });
  });
});
