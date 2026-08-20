import { z } from 'zod';

export const ApprovalRequestSchema = z.object({
  approval_id: z.string().uuid(),
  run_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  reason: z.string(),
  confidence: z.number().nullable(),
  status: z.enum(['pending', 'resolved']),
  reviewer: z.string().nullable(),
  decision: z.enum(['approve', 'reject']).nullable(),
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
