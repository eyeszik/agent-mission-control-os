import { z } from 'zod';

export const RunStateSchema = z.enum([
  'idle', 'queued', 'running', 'completed', 'failed', 'paused', 'needs_approval', 'resumed', 'cancelled'
]);

export const AgentRunSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.string(),
  project_id: z.string(),
  status: RunStateSchema,
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  metadata: z.record(z.unknown()).optional(),
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.unknown()).optional()
  }).optional()
});

export type RunState = z.infer<typeof RunStateSchema>;
export type AgentRun = z.infer<typeof AgentRunSchema>;
