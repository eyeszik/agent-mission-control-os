import { z } from 'zod';
import { RunProofSchema, DispatchPermitSchema, ExecutionReceiptSchema, ObservationReceiptSchema, FailureFingerprintSchema } from './agency';
import { ApprovalRequestSchema } from './approvals';

const hash = z.string().regex(/^[a-f0-9]{64}$/);
// Canonical fabric IDs are content-derived, not agency workflow UUIDs. Preserve
// the agency schema and narrow only this feature's proof projection.
const fabricRunId = z.string().regex(/^fabric-[a-f0-9]{24}$/);
const FabricProofSchema = RunProofSchema.extend({
  dispatch_permits: z.array(DispatchPermitSchema.extend({ run_id: fabricRunId })),
  execution_receipts: z.array(ExecutionReceiptSchema.extend({ run_id: fabricRunId })),
  observation_receipts: z.array(ObservationReceiptSchema.extend({ run_id: fabricRunId })),
  failure_fingerprints: z.array(FailureFingerprintSchema.extend({ run_id: fabricRunId })),
});
const route = z.object({ provider: z.enum(['openai', 'anthropic', 'gemini', 'ollama']), model: z.string().min(1).max(128) }).strict();
const profile = z.object({ schema_version: z.literal('amc.model-profile/v1'), source: z.enum(['run', 'project', 'tenant', 'deployment']), primary: route, fallbacks: z.array(route).max(0) }).strict();
export const InnovationGenerationSpecSchema = z.object({
  schema_version: z.literal('unbound.generation-spec/v1'), run_id: z.string(), source_artifact_id: z.string(), source_version: z.number().int().positive(), source_hash: hash, brief_hash: hash,
  provider_profile: profile, profile_hash: hash, prompt_version: z.literal('unbound-raw-ideas/v1'), graph_version: z.literal('unbound-generation/v1'),
  max_output_tokens: z.literal(8192), max_prompt_bytes: z.literal(60000), max_calls: z.literal(1), timeout_seconds: z.literal(30), max_cost_usd: z.literal(0),
}).strict();
const generatedIdea = z.object({ title: z.string().min(3).max(120), mechanism: z.string().min(20).max(1200), lens_ids: z.array(z.string()).min(1).max(12), assumptions: z.array(z.string().trim().min(1).max(300)).min(1).max(10), concept_id: z.string(), provenance: z.literal('MODEL_GENERATED'), evidence_class: z.literal('HYPOTHESIS'), content_hash: hash }).strict();
const invocation = z.object({ provider: z.string(), model: z.string(), prompt_hash: hash, profile_hash: hash, started_at: z.string(), completed_at: z.string(), usage: z.record(z.string(), z.number().int()).nullable(), cost_usd: z.null(), attempts: z.literal(1), outcome: z.enum(['OUTPUT_VALIDATED', 'OUTPUT_REJECTED']) }).strict();
export const InnovationGenerationResultSchema = z.object({ schema_version: z.literal('unbound.generation-result/v1'), state: z.enum(['GENERATED', 'PARTIAL', 'FAILED']), ideas: z.array(generatedIdea).max(50), coverage: z.array(z.string()), duplicate_groups: z.array(z.array(z.string())), limitations: z.array(z.string()), receipt: invocation.nullable(), evidence_class: z.literal('HYPOTHESIS') }).strict();
export const InnovationGenerationStageSchema = z.object({
  schema_version: z.literal('unbound-generation-stage/v1'), artifact_id: z.string(), version: z.number().int().positive(), content_hash: hash, job_id: z.string(),
  spec: InnovationGenerationSpecSchema, approval: ApprovalRequestSchema.nullable(), status: z.string(), reasons: z.array(z.string()), output: InnovationGenerationResultSchema.nullable(),
}).strict();
const measurements = z.object({ case_count: z.number().int().nonnegative(), baseline_retained_items: z.number().int().nonnegative(), candidate_retained_items: z.number().int().nonnegative(), baseline_redundant_items: z.number().int().nonnegative(), candidate_redundant_items: z.number().int().nonnegative(), unit: z.literal('items') }).strict();
export const InnovationLocalComputationSchema = z.object({
  schema_version: z.literal('innovation.local-experiment/v1'), status: z.literal('COMPLETED'), execution_mode: z.literal('LOCAL_COMPUTATION'), experiment_id: z.string(), input_provenance: z.literal('SIMULATED_OFFLINE_FIXTURE'),
  source_ref: z.string(), source_hash: hash, plan_ref: z.string(), plan_hash: hash, result_ref: z.string(), result_hash: hash, input_hash: hash, executor_version: z.literal('innovation.lexical-normalization/v1'),
  measurements, fabric_run_id: fabricRunId, learning: z.object({ decision: z.enum(['SUPPORTED', 'DISCONFIRMED']), rule: z.string(), interpretation: z.string(), next_action: z.string(), limitations: z.array(z.string()) }).strict(),
  release_authorized: z.literal(false), proof: FabricProofSchema, replayed: z.boolean(),
}).strict();
export const InnovationLocalExperimentSchema = z.union([InnovationLocalComputationSchema, z.object({ schema_version: z.literal('innovation.local-experiment/v1'), status: z.literal('BLOCKED'), report: z.record(z.string(), z.unknown()), limitations: z.array(z.string()) }).strict()]);
export type InnovationGenerationStage = z.infer<typeof InnovationGenerationStageSchema>;
export type InnovationLocalExperiment = z.infer<typeof InnovationLocalExperimentSchema>;
