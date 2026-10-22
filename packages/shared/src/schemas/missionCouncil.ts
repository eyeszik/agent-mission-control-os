import { z } from 'zod';

// Zod twins of the mission council API (services/langgraph/api/routes/missions.py).
// Parity: services/langgraph/tests/test_council_contracts.py records real responses
// in tests/fixtures/mission-council.json and checks every enum below against its
// Python vocabulary; tests/missionCouncil.test.ts parses that fixture.

export const CouncilEngineSchema = z.enum(['langgraph', 'crewai', 'autogen']);
export const MissionStatusSchema = z.enum(['queued', 'running', 'needs_approval', 'resuming', 'completed', 'rejected', 'failed', 'cancelled']);
export const MissionPhaseSchema = z.enum(['STRATEGY', 'AUDIT', 'GATE', 'PROTOTYPE', 'DONE']);
export const CouncilSeatSchema = z.enum(['george', 'fable', 'arty']);
export const RiskSeveritySchema = z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);
export const ModelModeSchema = z.enum(['MOCK_DETERMINISTIC', 'PROVIDER']);
export const SensitivitySchema = z.enum(['READ', 'WRITE', 'SHELL', 'EXTERNAL']);
export const CouncilEventTypeSchema = z.enum([
  'MISSION_QUEUED',
  'MISSION_STARTED',
  'SEAT_STARTED',
  'SEAT_COMPLETED',
  'RISK_ASSESSED',
  'CHECKPOINT_SAVED',
  'APPROVAL_REQUIRED',
  'approval_decided',
  'MISSION_RESUMING',
  'APPROVAL_APPLIED',
  'TOOL_INVOKED',
  'MISSION_COMPLETED',
  'MISSION_REJECTED',
  'MISSION_BLOCKED',
  'MISSION_FAILED',
  'CANCEL_REQUESTED',
  'MISSION_CANCELLED',
  'MISSION_RETRYING',
  'MISSION_RECOVERING',
]);

// A council mission's run_events, as streamed by /runs/{mission_id}/events (same envelope as RunEventSchema).
export const CouncilStreamEventSchema = z.object({
  event_id: z.string(),
  run_id: z.string(),
  sequence: z.number().int().nonnegative(),
  schema_version: z.literal('run-event-v2'),
  event_type: CouncilEventTypeSchema,
  node_id: z.string().nullable(),
  observed_at: z.string(),
  safe_payload: z.record(z.string(), z.unknown()),
});

export const EngineInfoSchema = z.object({ engine: CouncilEngineSchema, available: z.boolean(), detail: z.string() });
export const EnginesResponseSchema = z.object({
  engines: z.array(EngineInfoSchema),
  model_mode: ModelModeSchema,
  real_models_enabled: z.boolean(),
  default_provider: z.string(),
});

export const ToolSpecSchema = z.object({
  tool_id: z.string(),
  provider: z.enum(['local', 'mcp']),
  description: z.string(),
  sensitivity: SensitivitySchema,
  scopes: z.array(z.string()),
  requires_approval: z.boolean(),
  enabled: z.boolean(),
  timeout_s: z.number(),
});
export const ToolsResponseSchema = z.object({
  tools: z.array(ToolSpecSchema),
  mcp_installed: z.boolean(),
  mcp_config_errors: z.array(z.string()),
});

export const IdeaSchema = z.object({
  idea_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  title: z.string(),
  description: z.string(),
  status: z.enum(['OPEN', 'PROMOTED']),
  created_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const TaskNodeSchema = z.object({
  id: z.string(),
  title: z.string(),
  seat: CouncilSeatSchema,
  depends_on: z.array(z.string()),
  acceptance: z.string(),
});
export const StrategySchema = z.object({
  summary: z.string(),
  goals: z.array(z.string()),
  architecture: z.array(z.string()),
  tasks: z.array(TaskNodeSchema),
});
export const RequestedActionSchema = z.object({ tool_id: z.string(), sensitivity: SensitivitySchema, target: z.string() });
export const RiskFindingSchema = z.object({
  code: z.string(),
  severity: RiskSeveritySchema,
  detail: z.string(),
  source: z.enum(['POLICY', 'MODEL']),
});
export const RiskAssessmentSchema = z.object({
  level: RiskSeveritySchema,
  findings: z.array(RiskFindingSchema),
  requires_approval: z.boolean(),
  blocked: z.boolean(),
  requested_actions: z.array(RequestedActionSchema),
  narrative: z.string(),
  policy_version: z.string(),
});
export const GateSchema = z.object({
  subject_hash: z.string(),
  risk_level: RiskSeveritySchema.nullable(),
  findings: z.array(z.string()),
  requested_actions: z.array(RequestedActionSchema),
});
export const DecisionSchema = z.object({
  approval_id: z.string().nullable(),
  decision: z.enum(['approve', 'reject']),
  decided_by: z.string().nullable(),
  subject_hash: z.string().nullable(),
  reason: z.string(),
});
export const ScaffoldViewSchema = z.object({
  summary: z.string(),
  components: z.array(z.object({ name: z.string(), purpose: z.string(), props: z.array(z.string()) })),
  design_tokens: z.array(z.string()),
  files: z.array(z.object({ path: z.string(), bytes: z.number() })),
});
export const MissionApprovalSchema = z.object({
  approval_id: z.string(),
  status: z.enum(['pending', 'resolved', 'stale']),
  decision: z.enum(['approve', 'reject']).nullable(),
  reviewer: z.string().nullable(),
  subject_hash: z.string().nullable(),
});
export const SeatResultSchema = z.object({
  seat: CouncilSeatSchema,
  engine: CouncilEngineSchema,
  model_mode: ModelModeSchema,
  attempts: z.number(),
  started_at: z.string(),
  completed_at: z.string(),
});

export const MissionSchema = z.object({
  mission_id: z.string(),
  thread_id: z.string(),
  idea_id: z.string(),
  project_id: z.string(),
  engine: CouncilEngineSchema,
  model_mode: ModelModeSchema,
  status: MissionStatusSchema,
  phase: MissionPhaseSchema,
  attempts: z.number(),
  last_error: z.string().nullable(),
  cancel_requested: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  initiated_by: z.string().nullable(),
  strategy: StrategySchema.nullable(),
  risk: RiskAssessmentSchema.nullable(),
  gate: GateSchema.nullable(),
  decision: DecisionSchema.nullable(),
  requested_actions: z.array(RequestedActionSchema),
  scaffold: ScaffoldViewSchema.nullable(),
  results: z.record(z.string(), SeatResultSchema),
  approval: MissionApprovalSchema.nullable(),
});

export const MissionPageSchema = z.object({ items: z.array(MissionSchema), next_cursor: z.string().nullable() });
export const IdeaPageSchema = z.object({ items: z.array(IdeaSchema), next_cursor: z.string().nullable() });

export const TimelineEventSchema = z.object({
  sequence: z.number().int(),
  event_type: z.string(),
  node_id: z.string().nullable(),
  observed_at: z.string(),
  payload: z.record(z.string(), z.unknown()),
});
export const TimelineSchema = z.object({ mission_id: z.string(), events: z.array(TimelineEventSchema), next_cursor: z.number() });

export const CouncilCheckpointSchema = z.object({
  checkpoint_id: z.string(),
  seq: z.number().int(),
  phase: MissionPhaseSchema,
  engine: CouncilEngineSchema,
  state_hash: z.string(),
  prev_hash: z.string(),
  native_checkpoint_id: z.string().nullable(),
  created_at: z.string(),
});
export const NativeCheckpointSchema = z.object({
  checkpoint_id: z.string().nullable(),
  next: z.array(z.string()),
  interrupted: z.boolean(),
  has_strategy: z.boolean(),
  has_risk: z.boolean(),
  has_scaffold: z.boolean(),
  terminal: z.string().nullable(),
});
export const CheckpointsSchema = z.object({
  mission_id: z.string(),
  chain_verified: z.boolean(),
  chain_detail: z.string(),
  checkpoints: z.array(CouncilCheckpointSchema),
  native: z.array(NativeCheckpointSchema),
});

export const ToolAuditSchema = z.object({
  audit_id: z.string(),
  tool_id: z.string(),
  seat: z.string().nullable(),
  sensitivity: z.string(),
  decision: z.enum(['ALLOWED', 'DENIED', 'FAILED', 'TIMEOUT']),
  reason_code: z.string(),
  created_at: z.string(),
});
export const ToolAuditListSchema = z.object({ items: z.array(ToolAuditSchema) });

export const BlueprintSchema = z.object({
  blueprint_id: z.string(),
  idea_id: z.string(),
  status: z.enum(['DRAFT', 'PROMOTED']),
  content_hash: z.string(),
  content: z.object({
    strategy: z.object({ summary: z.string(), source_engine: CouncilEngineSchema }).passthrough(),
    security: z.object({ level: RiskSeveritySchema, findings: z.array(z.object({ code: z.string(), severity: RiskSeveritySchema }).passthrough()) }).passthrough(),
    scaffold: z.object({ summary: z.string(), source_engine: CouncilEngineSchema, components: z.array(z.object({ name: z.string() }).passthrough()) }).passthrough(),
  }).passthrough(),
  sources: z.array(z.object({
    mission_id: z.string(),
    engine: CouncilEngineSchema,
    status: MissionStatusSchema,
    used_for: z.array(z.string()),
    excluded_reason: z.string().nullable(),
  })),
  verification: z.object({ verified: z.boolean() }).passthrough().nullable(),
  created_at: z.string(),
  promoted_at: z.string().nullable(),
});

export const IdeaDetailSchema = IdeaSchema.extend({ missions: z.array(MissionSchema), blueprints: z.array(BlueprintSchema) });

export type CouncilEngine = z.infer<typeof CouncilEngineSchema>;
export type CouncilEventType = z.infer<typeof CouncilEventTypeSchema>;
export type CouncilStreamEvent = z.infer<typeof CouncilStreamEventSchema>;
export type MissionStatus = z.infer<typeof MissionStatusSchema>;
export type CouncilSeat = z.infer<typeof CouncilSeatSchema>;
export type EnginesResponse = z.infer<typeof EnginesResponseSchema>;
export type ToolsResponse = z.infer<typeof ToolsResponseSchema>;
export type Idea = z.infer<typeof IdeaSchema>;
export type IdeaDetail = z.infer<typeof IdeaDetailSchema>;
export type Mission = z.infer<typeof MissionSchema>;
export type MissionPage = z.infer<typeof MissionPageSchema>;
export type IdeaPage = z.infer<typeof IdeaPageSchema>;
export type TimelineEvent = z.infer<typeof TimelineEventSchema>;
export type Checkpoints = z.infer<typeof CheckpointsSchema>;
export type Blueprint = z.infer<typeof BlueprintSchema>;
export type ToolAudit = z.infer<typeof ToolAuditSchema>;
