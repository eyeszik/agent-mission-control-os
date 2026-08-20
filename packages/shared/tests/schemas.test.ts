import { describe, it, expect } from 'vitest';
import { AgentRunSchema, RunStateSchema } from '../src/schemas/run';
import { ApprovalRequestSchema } from '../src/schemas/approvals';
import { AgencyRunSchema, CampaignBriefSchema } from '../src/schemas/agency';

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
});
