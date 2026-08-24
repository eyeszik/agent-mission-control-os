import { z } from 'zod';

export const ApprovalRequestSchema = z.object({
  approval_id: z.string().uuid(),
  run_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  reason: z.string(),
  confidence: z.number().nullable(),
  status: z.enum(['pending', 'resolved', 'stale']),
  reviewer: z.string().nullable(),
  decision: z.enum(['approve', 'reject']).nullable(),
  subject_type: z.string().nullable().optional(),
  subject_ref: z.string().nullable().optional(),
  subject_version_ref: z.string().nullable().optional(),
  subject_hash: z.string().nullable().optional(),
  authority_ref: z.string().nullable().optional(),
  policy_version: z.string().nullable().optional(),
  stale_reason: z.string().nullable().optional(),
  staled_at: z.string().nullable().optional(),
  created_at: z.string(),
  decided_at: z.string().nullable(),
});

export const ApprovalListSchema = z.array(ApprovalRequestSchema);

export const ApprovalDecisionResponseSchema = z.object({
  approval_id: z.string().uuid(),
  status: z.literal('resolved'),
  decision: z.enum(['approve', 'reject']),
  reviewer: z.string(),
  decided_at: z.string(),
});

export type ApprovalRequest = z.infer<typeof ApprovalRequestSchema>;
export type ApprovalDecisionResponse = z.infer<typeof ApprovalDecisionResponseSchema>;
