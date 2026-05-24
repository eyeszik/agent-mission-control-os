import { z } from 'zod';

export const ApprovalRequestSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  node_id: z.string(),
  action_type: z.enum(['external_write', 'pii_release', 'canonical_publish', 'high_cost_execution']),
  description: z.string(),
  context: z.record(z.unknown()),
  status: z.enum(['pending', 'approved', 'rejected']),
  requested_at: z.string().datetime(),
  resolved_at: z.string().datetime().optional(),
  resolved_by: z.string().optional()
});

export type ApprovalRequest = z.infer<typeof ApprovalRequestSchema>;
