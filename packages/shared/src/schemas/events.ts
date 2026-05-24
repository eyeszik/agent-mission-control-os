import { z } from 'zod';

export const RunEventSchema = z.object({
  event_id: z.string().uuid(),
  run_id: z.string().uuid(),
  node_id: z.string(),
  type: z.enum(['node_start', 'node_complete', 'node_error', 'artifact_generated', 'approval_requested']),
  payload: z.record(z.unknown()),
  timestamp: z.string().datetime()
});

export type RunEvent = z.infer<typeof RunEventSchema>;
