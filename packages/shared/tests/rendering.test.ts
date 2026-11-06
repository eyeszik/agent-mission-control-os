import { describe, it, expect } from 'vitest';
import { RenderCapabilitiesSchema, RenderEngineIdSchema } from '../src/schemas/rendering';
describe('render engine capability contract', () => {
  it('keeps rendering separate from orchestration engines', () => {
    expect(RenderEngineIdSchema.safeParse('langgraph').success).toBe(false);
    expect(RenderEngineIdSchema.options).toHaveLength(8);
  });
  it('does not accept fabricated arbitrary-code or remote-storage capabilities', () => {
    const engine = {engine: 'rough_js', adapter_version: 'rough-svg/v1', available: true, profiles: ['svg:typed-primitives'], blockers: [], arbitrary_code: false, remote_storage: false, isolation_profile: 'typed-primitives/process-v1'};
    expect(RenderCapabilitiesSchema.safeParse({engines:[engine], external_effects:'none'}).success).toBe(true);
    expect(RenderCapabilitiesSchema.safeParse({engines:[{...engine, arbitrary_code:true}], external_effects:'none'}).success).toBe(false);
  });
});
