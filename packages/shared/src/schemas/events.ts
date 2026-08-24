import { z } from 'zod';

export const RunEventSchema = z.object({
  event_id: z.string().uuid(),
  run_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  sequence: z.number().int().nonnegative(),
  schema_version: z.literal('run-event-v2'),
  event_type: z.enum([
    'node_complete',
    'node_error',
    'artifact_generated',
    'approval_requested',
    'approval_decided',
    'recovery_case_updated',
    'outbox_updated',
  ]),
  node_id: z.string().nullable(),
  observed_at: z.string().datetime({ offset: true }),
  started_at: z.string().datetime({ offset: true }).nullable(),
  completed_at: z.string().datetime({ offset: true }).nullable(),
  persisted_at: z.string().datetime({ offset: true }),
  checkpoint_ref: z.string().nullable(),
  safe_payload: z.record(z.unknown()),
  redactions_applied: z.array(z.string()),
});

export type RunEvent = z.infer<typeof RunEventSchema>;
