import type { AvicCapabilities } from '@amc/shared';

/**
 * What the intake knows about the host's capabilities so far.
 *
 * A load has three states, not two. "No data yet" and "the request failed" are
 * different statements, and collapsing them makes a still-loading panel look
 * like a host without a renderer.
 */
export type CapabilitiesState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; data: AvicCapabilities };

/**
 * Why Compile is disabled, or null when it may be enabled.
 *
 * Compile starts a real render, so it stays disabled until the intake is valid
 * *and* the host's renderer is confirmed. Each of those states has to say which
 * one it is: a disabled button with no stated reason cannot be told apart from
 * a broken one, and a hosted E2E run spent its whole budget clicking at "element
 * is not enabled" while the page was already rendering the sentence beside it.
 *
 * Pure on purpose -- the reasons are the contract, so they are asserted without
 * a browser, a server or React.
 */
export function compileBlockedReason(input: {
  requirement: string;
  parseError: string | null;
  capabilities: CapabilitiesState;
  chosenProfile: string;
  seed: string;
}): string | null {
  const { requirement, parseError, capabilities, chosenProfile, seed } = input;
  if (!requirement.trim()) return 'Paste an AssetRequirement JSON (the "requirement" in sample_avic_request.json).';
  if (parseError) return `The requirement is not valid JSON: ${parseError}`;
  if (capabilities.status === 'loading') return 'Checking the API host for a renderer…';
  if (capabilities.status === 'error') return `Could not read the API host's capabilities: ${capabilities.error}`;
  const data = capabilities.data;
  const implemented = (data.style_profiles ?? []).filter((p) => p.state === 'IMPLEMENTED_VERIFIED');
  if (!chosenProfile || !implemented.some((p) => p.profile_id === chosenProfile)) {
    return 'No implemented style profile is available.';
  }
  const seedValue = Number.parseInt(seed, 10);
  if (!Number.isInteger(seedValue) || seedValue < 0) return 'Seed must be a whole number of 0 or more.';
  if (data.renderer.state !== 'IMPLEMENTED_VERIFIED') {
    return `Renderer unavailable on the API host: ${(data.renderer.blockers ?? []).join('; ')}`;
  }
  return null;
}
