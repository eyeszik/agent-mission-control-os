import { describe, it, expect } from 'vitest';
import { AgentRunSchema, RunStateSchema } from '../src/schemas/run';
import { ApprovalRequestSchema } from '../src/schemas/approvals';
import { AgencyRunSchema, CampaignBriefSchema } from '../src/schemas/agency';
import { BrandCoreSchema, MINIMUM_COLOR_STORY_DISTINCTION_RATIO } from '../src/schemas/brand';
import { contrastRatio } from '../src/schemas/colorContrast';

describe('Shared Schemas', () => {
  describe('AgentRunSchema', () => {
    const validRun = {
      id: '123e4567-e89b-12d3-a456-426614174000',
      tenant_id: 'tenant-1',
      project_id: 'proj-1',
      status: 'idle',
      created_at: '2026-01-01T00:00:00.000Z',
      updated_at: '2026-01-01T00:00:00.000Z',
    };

    it('should validate a correct run object', () => {
      expect(AgentRunSchema.safeParse(validRun).success).toBe(true);
    });

    it('should reject invalid UUIDs', () => {
      const result = AgentRunSchema.safeParse({ ...validRun, id: 'not-a-uuid' });
      expect(result.success).toBe(false);
    });

    it('should enforce valid state transitions in types', () => {
      expect(RunStateSchema.safeParse('needs_approval').success).toBe(true);
      expect(RunStateSchema.safeParse('bogus_state').success).toBe(false);
      const result = AgentRunSchema.safeParse({ ...validRun, status: 'bogus_state' });
      expect(result.success).toBe(false);
    });
  });

  describe('ApprovalRequestSchema', () => {
    it('matches the real backend row shape (approval_id, reason, confidence, reviewer, decision)', () => {
      const row = {
        approval_id: '123e4567-e89b-12d3-a456-426614174000',
        run_id: 'run-1',
        tenant_id: 'tenant-1',
        project_id: 'proj-1',
        reason: 'Campaign package ready for human review before external publish.',
        confidence: 0.76,
        status: 'pending',
        reviewer: null,
        decision: null,
        created_at: '2026-01-01T00:00:00',
        decided_at: null,
      };
      expect(ApprovalRequestSchema.safeParse(row).success).toBe(true);
    });

    it('rejects the old, wrong shape (id/node_id/action_type/description/context)', () => {
      const oldShape = {
        id: '123e4567-e89b-12d3-a456-426614174000',
        run_id: 'run-1',
        node_id: 'hitl_gate',
        action_type: 'canonical_publish',
        description: 'Please review',
        context: {},
        status: 'pending',
        requested_at: '2026-01-01T00:00:00.000Z',
      };
      expect(ApprovalRequestSchema.safeParse(oldShape).success).toBe(false);
    });
  });

  describe('CampaignBriefSchema', () => {
    it('requires brand_name and target_audience', () => {
      expect(CampaignBriefSchema.safeParse({}).success).toBe(false);
      expect(
        CampaignBriefSchema.safeParse({ brand_name: 'Acme', target_audience: 'Devs' }).success
      ).toBe(true);
    });

    it('defaults array fields to empty arrays when omitted', () => {
      const parsed = CampaignBriefSchema.parse({ brand_name: 'Acme', target_audience: 'Devs' });
      expect(parsed.goals).toEqual([]);
      expect(parsed.channels).toEqual([]);
      expect(parsed.constraints).toEqual([]);
    });
  });

  describe('AgencyRunSchema', () => {
    it('accepts the minimal resume response shape (only run_id/status/delivery)', () => {
      const resumeResponse = {
        run_id: '123e4567-e89b-12d3-a456-426614174000',
        status: 'completed',
        delivery: null,
      };
      expect(AgencyRunSchema.safeParse(resumeResponse).success).toBe(true);
    });

    it('rejects an unknown status value', () => {
      const result = AgencyRunSchema.safeParse({
        run_id: '123e4567-e89b-12d3-a456-426614174000',
        status: 'not_a_real_status',
      });
      expect(result.success).toBe(false);
    });
  });

  describe('BrandCoreSchema', () => {
    const primaryLockup = {
      lockup_id: 'primary-full-color',
      lockup_type: 'primary',
      usage_context: 'Default mark for all digital and print surfaces.',
      minimum_size: '24px height digital / 0.5in height print',
      clear_space_rule: 'Clear space on all sides equal to the cap height of the wordmark.',
      placement_notes: 'Top-left on digital surfaces; bottom-right on print collateral.',
      generation_reference:
        'A rounded wordmark in deep indigo with a small compass-needle mark to the left.',
    };

    const validBrandCore = {
      brand_name: 'Northwind Coffee',
      positioning_essence: 'The coffee for people who take their mornings seriously.',
      voice: {
        tone_attributes: ['confident', 'warm', 'direct'],
        writing_dos: ['Use short sentences.'],
        writing_donts: ['Never use exclamation points.'],
      },
      color_story: [
        { role: 'primary', description: "A deep, confident blue that carries the brand's authority." },
      ],
      typography_direction: 'A humanist serif for headlines, a clean grotesk for body copy.',
      imagery_style: 'Natural light, unstyled hands, no studio gloss.',
      motion: {
        pace: 'Brisk, confident deceleration, minimal overshoot.',
        emphasis_moments: ['primary CTA activation', 'order confirmation'],
        reduced_motion_fallback: 'Cross-fade only; no translation or scale.',
      },
      logo_lockups: [primaryLockup],
    };

    it('accepts a valid brand core with exactly one primary lockup', () => {
      expect(BrandCoreSchema.safeParse(validBrandCore).success).toBe(true);
    });

    it('rejects zero primary lockups', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        logo_lockups: [{ ...primaryLockup, lockup_id: 'icon', lockup_type: 'icon_only' }],
      });
      expect(result.success).toBe(false);
    });

    it('rejects a second primary lockup', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        logo_lockups: [primaryLockup, { ...primaryLockup, lockup_id: 'primary-b' }],
      });
      expect(result.success).toBe(false);
    });

    it('rejects duplicate lockup_id values', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        logo_lockups: [
          primaryLockup,
          { ...primaryLockup, lockup_type: 'icon_only' },
        ],
      });
      expect(result.success).toBe(false);
    });

    it('rejects an unknown lockup_type', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        logo_lockups: [{ ...primaryLockup, lockup_type: 'holographic' }],
      });
      expect(result.success).toBe(false);
    });

    it('defaults writing_dos and writing_donts to empty arrays', () => {
      const parsed = BrandCoreSchema.parse({
        ...validBrandCore,
        voice: { tone_attributes: ['confident'] },
      });
      expect(parsed.voice.writing_dos).toEqual([]);
      expect(parsed.voice.writing_donts).toEqual([]);
    });

    it('requires at least one color_story entry', () => {
      const result = BrandCoreSchema.safeParse({ ...validBrandCore, color_story: [] });
      expect(result.success).toBe(false);
    });

    it('requires motion', () => {
      const { motion, ...withoutMotion } = validBrandCore;
      expect(BrandCoreSchema.safeParse(withoutMotion).success).toBe(false);
    });

    it('rejects motion with zero emphasis_moments', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        motion: { ...validBrandCore.motion, emphasis_moments: [] },
      });
      expect(result.success).toBe(false);
    });

    it('requires reduced_motion_fallback', () => {
      const { reduced_motion_fallback, ...motionWithoutFallback } = validBrandCore.motion;
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        motion: motionWithoutFallback,
      });
      expect(result.success).toBe(false);
    });

    it('accepts a valid reference_hex on a color role', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        color_story: [{ ...validBrandCore.color_story[0], reference_hex: '#1a2b4c' }],
      });
      expect(result.success).toBe(true);
    });

    it('rejects a non-hex reference_hex value', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        color_story: [{ ...validBrandCore.color_story[0], reference_hex: 'blue' }],
      });
      expect(result.success).toBe(false);
    });

    it('accepts two distinguishable reference_hex colors', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        color_story: [
          { role: 'primary', description: 'Deep blue.', reference_hex: '#1a2b4c' },
          { role: 'accent', description: 'Warm amber.', reference_hex: '#e08a2c' },
        ],
      });
      expect(result.success).toBe(true);
    });

    it('rejects two near-identical reference_hex colors', () => {
      const result = BrandCoreSchema.safeParse({
        ...validBrandCore,
        color_story: [
          { role: 'primary', description: 'Deep blue.', reference_hex: '#1a2b4c' },
          { role: 'accent', description: 'Almost the same blue.', reference_hex: '#1a2b4d' },
        ],
      });
      expect(result.success).toBe(false);
    });

    it('the near-identical fixture is below the documented distinction ratio', () => {
      expect(contrastRatio('#1a2b4c', '#1a2b4d')).toBeLessThan(
        MINIMUM_COLOR_STORY_DISTINCTION_RATIO
      );
    });
  });
});
