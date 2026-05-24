import { z } from 'zod';

export const QualityScoreSchema = z.object({
  id: z.string().uuid(),
  run_id: z.string().uuid(),
  node_id: z.string(),
  metrics: z.object({
    faithfulness: z.number().min(0).max(1),
    hallucination_rate: z.number().min(0).max(1),
    tool_selection_accuracy: z.number().min(0).max(1),
    output_relevance: z.number().min(0).max(1)
  }),
  threshold_passed: z.boolean(),
  summary: z.string(),
  timestamp: z.string().datetime()
});

export type QualityScore = z.infer<typeof QualityScoreSchema>;
