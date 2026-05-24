import { z } from 'zod';

export const ArtifactSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  node_id: z.string(),
  type: z.enum(['code', 'document', 'spec', 'data']),
  content: z.string(),
  metadata: z.record(z.unknown()).optional(),
  created_at: z.string().datetime()
});

export type Artifact = z.infer<typeof ArtifactSchema>;
