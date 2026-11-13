import { describe, expect, it } from 'vitest';
import type { AvicCapabilities } from '@amc/shared';
import { compileBlockedReason, type CapabilitiesState } from '../lib/avic/intake';

// The hosted E2E failure was not a slow render: Compile never became enabled,
// and the reason it was disabled was never stated anywhere a failure report
// could read. These tests pin every reason, including the one that only exists
// while capabilities are still loading.

const PROFILE = 'post-surrealist-editorial';

function caps(overrides: { rendererState?: string; blockers?: string[]; profiles?: { profile_id: string; state: string }[] } = {}): CapabilitiesState {
  return {
    status: 'ready',
    data: {
      capabilities: [],
      style_profiles: (overrides.profiles ?? [{ profile_id: PROFILE, state: 'IMPLEMENTED_VERIFIED' }]),
      renderer: { name: 'raster.chromium', state: overrides.rendererState ?? 'IMPLEMENTED_VERIFIED', blockers: overrides.blockers ?? [], concurrency: 2 },
      brand: {},
    } as unknown as AvicCapabilities,
  };
}

const valid = { requirement: '{"asset_id":"a"}', parseError: null, capabilities: caps(), chosenProfile: PROFILE, seed: '0' };

describe('compileBlockedReason', () => {
  it('allows Compile only when intake is valid and the renderer is verified', () => {
    expect(compileBlockedReason(valid)).toBeNull();
  });

  it('names the missing brief before anything else', () => {
    expect(compileBlockedReason({ ...valid, requirement: '  ' })).toContain('Paste an AssetRequirement');
  });

  it('says the JSON is invalid instead of failing silently', () => {
    expect(compileBlockedReason({ ...valid, parseError: 'unexpected token' })).toContain('not valid JSON');
  });

  it('distinguishes "still loading" from "no renderer"', () => {
    // The bug that ate five minutes of a hosted run: while the capabilities
    // request was in flight, Compile was disabled with no explanation at all.
    const loading = compileBlockedReason({ ...valid, capabilities: { status: 'loading' } });
    expect(loading).toContain('Checking the API host');
    expect(loading).not.toContain('Renderer unavailable');
  });

  it('carries a capabilities failure into the reason', () => {
    const reason = compileBlockedReason({ ...valid, capabilities: { status: 'error', error: 'Failed to fetch' } });
    expect(reason).toContain('Failed to fetch');
  });

  it('refuses a profile that is not implemented', () => {
    expect(compileBlockedReason({ ...valid, capabilities: caps({ profiles: [{ profile_id: PROFILE, state: 'PROPOSED' }] }) }))
      .toContain('No implemented style profile');
    expect(compileBlockedReason({ ...valid, chosenProfile: '' })).toContain('No implemented style profile');
  });

  it('refuses a seed that is not a whole number', () => {
    expect(compileBlockedReason({ ...valid, seed: 'x' })).toContain('Seed must be a whole number');
    expect(compileBlockedReason({ ...valid, seed: '-1' })).toContain('Seed must be a whole number');
  });

  it('repeats the host blocker verbatim, so the reason is the host\'s own words', () => {
    const reason = compileBlockedReason({
      ...valid,
      capabilities: caps({ rendererState: 'BLOCKED', blockers: ['MISSING_DEPENDENCY:chromium'] }),
    });
    expect(reason).toContain('MISSING_DEPENDENCY:chromium');
  });
});
