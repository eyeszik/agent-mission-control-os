import { z } from 'zod';

// Mirrors the actual runtime shape returned by
// services/langgraph/persistence/approvals.py / GET|POST /approvals — the
// previous version of this schema (id/node_id/action_type/description/context)
// never matched what the backend returns and nothing in the frontend caught it
// because nothing called the API. Corrected to the real row shape.
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

export type ApprovalRequest = z.infer<typeof ApprovalRequestSchema>;
