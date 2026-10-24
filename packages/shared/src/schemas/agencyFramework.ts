import { z } from 'zod';

// Zod twins of the agency operating framework API (services/langgraph/api/routes/agency_framework.py).
// Parity: services/langgraph/tests/test_agency_framework_contracts.py records real responses in
// tests/fixtures/agency-framework.json and checks every enum below against its Python vocabulary;
// tests/agencyFramework.test.ts parses that fixture.

export const AfTaskStateSchema = z.enum(['BACKLOG', 'READY', 'ACTIVE', 'IN_REVIEW', 'VERIFIED', 'APPROVED', 'BLOCKED', 'INVALIDATED', 'NOT_APPLICABLE']);
export const AfApplicabilitySchema = z.enum(['UNASSESSED', 'REQUIRED', 'CONDITIONAL', 'NOT_APPLICABLE']);
export const AfGateStatusSchema = z.enum(['NOT_ASSESSED', 'BLOCKED', 'NEEDS_HUMAN', 'APPROVAL_PENDING', 'PASSED', 'STALE']);
export const AfEvidenceOriginSchema = z.enum(['CUSTOMER_SOURCED', 'PUBLIC_SOURCE', 'INTERNAL_RECORD', 'INFERENCE', 'SYNTHETIC']);
export const AfArchetypeSchema = z.enum(['B2C_PHYSICAL_PRODUCT', 'B2B_PROFESSIONAL_SERVICES', 'SAAS_SUBSCRIPTION', 'OTHER']);
export const AfStageGateSchema = z.enum(['01_DISCOVERY', '02_STRATEGY', '03_PRODUCTION', '04_ACTIVATION', '05_GROWTH']);
export const AfDisciplineSchema = z.enum(['Discover', 'Strategize', 'Design', 'Build', 'Activate', 'Optimize']);
export const AfOutputClassSchema = z.enum(['evidence', 'decision', 'artifact', 'approval_or_plan', 'measurement']);
export const AfCoverageSchema = z.enum(['EXACT', 'NEAREST', 'NO_N3_ROLE']);
export const AfCapabilitySchema = z.enum(['LOCAL_AVAILABLE', 'DRY_RUN_ONLY', 'PLANNING_ONLY', 'HUMAN_ONLY', 'PROVIDER_GAP']);
export const AfExternalEffectSchema = z.enum(['none', 'publish', 'spend', 'send', 'outreach']);
export const AfAssuranceKindSchema = z.enum(['meaning', 'mutation', 'probe', 'renewal', 'review']);

const NotMeasured = z.literal('NOT_MEASURED');

export const AfBindingSchema = z.object({
  n3_role: z.string(),
  artifact_type: z.string(),
  coverage: AfCoverageSchema,
  native_owner: z.string(),
  capability: AfCapabilitySchema,
  external_effect: AfExternalEffectSchema,
  note: z.string(),
});

export const AfModuleSchema = z.object({
  module_id: z.string(),
  title: z.string(),
  phase: AfDisciplineSchema,
  stage_gate: AfStageGateSchema,
  expected_task_count: z.number().int(),
  depends_on_modules: z.array(z.string()),
  required_deliverable: z.string(),
  owner_role: z.string(),
  acceptance_policy: z.string(),
  binding: AfBindingSchema,
});

export const AfCatalogSchema = z.object({
  catalog_id: z.string(),
  catalog_version: z.string(),
  sha256: z.string(),
  module_count: z.number().int(),
  task_count: z.number().int(),
  user_supplied_task_count: z.number().int(),
  newly_authored_task_count: z.number().int(),
  per_discipline: z.record(z.string(), z.number()),
  per_stage_gate: z.record(z.string(), z.number()),
  per_module: z.record(z.string(), z.number()),
  stage_gates: z.record(z.string(), z.string()),
  modules: z.array(AfModuleSchema),
});

export const AfTaskDefinitionSchema = z.object({
  task_id: z.string(),
  module_id: z.string(),
  sequence: z.number().int(),
  title: z.string(),
  definition_source: z.enum(['user_supplied', 'newly_authored_expansion']),
  owner_role: z.string(),
  phase: AfDisciplineSchema,
  stage_gate: AfStageGateSchema,
  depends_on_modules: z.array(z.string()),
  output_class: AfOutputClassSchema,
  module_deliverable: z.string(),
  acceptance: z.string(),
});

export const AfCountsSchema = z.object({
  defined: z.number(),
  unassessed: z.number(),
  required: z.number(),
  conditional: z.number(),
  not_applicable: z.number(),
  applicable: z.number(),
  backlog: z.number(),
  in_progress: z.number(),
  in_review: z.number(),
  verified: z.number(),
  approved: z.number(),
  blocked: z.number(),
  required_verified: z.number(),
  required_verified_ratio: z.union([z.number(), NotMeasured]),
});

export const AfProgressSchema = z.object({
  overall: AfCountsSchema,
  catalog_totals: z.record(z.string(), z.number()),
  modules: z.record(z.string(), AfCountsSchema),
  stage_gates: z.record(z.string(), AfCountsSchema),
  disciplines: z.record(z.string(), AfCountsSchema),
});

export const AfGateSchema = z.object({
  stage_gate: AfStageGateSchema,
  status: AfGateStatusSchema,
  evaluation_hash: z.string(),
  required_count: z.number().int(),
  unassessed: z.array(z.string()),
  unmet: z.array(z.object({ task_id: z.string(), state: AfTaskStateSchema, reason: z.string() })),
  evidence_origins: z.array(z.string()),
  synthetic_only: z.boolean(),
  no_required_tasks: z.boolean(),
  approval_id: z.string().nullable(),
  reasons: z.array(z.string()),
  criteria: z.string(),
});

export const AfPlanRecordSchema = z.object({
  plan_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  catalog_id: z.string(),
  catalog_version: z.string(),
  catalog_sha256: z.string(),
  archetype: AfArchetypeSchema,
  engagement_scope: z.string(),
  created_by: z.string(),
  created_at: z.string(),
});

export const AfReadinessSchema = z.object({
  tasks_specified: z.number(),
  required_tasks: z.number(),
  required_verified: z.boolean(),
  required_approved: z.boolean(),
  all_gates_passed: z.boolean(),
  synthetic_evidence_present: z.boolean(),
  release_eligible: z.literal(false),
  release_eligibility_owner: z.string(),
  externally_executed: z.literal(false),
  external_actions: z.string(),
});

export const AfPlanViewSchema = z.object({
  plan: AfPlanRecordSchema,
  catalog: z.object({ catalog_id: z.string(), catalog_version: z.string(), sha256: z.string(), pinned: z.boolean() }),
  progress: AfProgressSchema,
  gates: z.array(AfGateSchema),
  readiness: AfReadinessSchema,
  created: z.boolean().optional(),
});

export const AfPlanListSchema = z.object({ items: z.array(AfPlanRecordSchema) });

export const AfTaskRowSchema = z.object({
  task_id: z.string(),
  module_id: z.string(),
  stage_gate: AfStageGateSchema,
  title: z.string(),
  phase: AfDisciplineSchema,
  output_class: AfOutputClassSchema,
  definition_source: z.string(),
  owner_role: z.string(),
  assignee_role: z.string(),
  applicability: AfApplicabilitySchema,
  state: AfTaskStateSchema,
  status_reason: z.string().nullable(),
  version: z.number().int(),
  ref_count: z.number().int(),
  approval_ref: z.string().nullable(),
  updated_at: z.string(),
});
export const AfTaskListSchema = z.object({ items: z.array(AfTaskRowSchema) });

export const AfRefCheckSchema = z.object({
  ref: z.string(),
  kind: z.string(),
  status: z.string(),
  ok: z.boolean(),
  attachable: z.boolean(),
  origin: AfEvidenceOriginSchema.nullable(),
  content_hash: z.string().nullable(),
  fresh_until: z.string().nullable(),
  detail: z.string(),
});

export const AfInstanceSchema = z.object({
  plan_id: z.string(),
  task_id: z.string(),
  tenant_id: z.string(),
  project_id: z.string(),
  module_id: z.string(),
  stage_gate: AfStageGateSchema,
  applicability: AfApplicabilitySchema,
  applicability_reason: z.string().nullable(),
  applicability_by: z.string().nullable(),
  state: AfTaskStateSchema,
  blocked_from: z.string().nullable(),
  status_reason: z.string().nullable(),
  assignee_role: z.string(),
  evidence_refs: z.array(z.string()),
  artifact_refs: z.array(z.string()),
  decision_refs: z.array(z.string()),
  submitted_by: z.string().nullable(),
  verification: z
    .object({
      result: z.enum(['PASSED', 'FAILED']),
      verified_by: z.string(),
      at: z.string(),
      checks: z.array(AfRefCheckSchema),
      origins: z.array(z.string()),
      proof_hash: z.string().optional(),
    })
    .nullable(),
  approval_ref: z.string().nullable(),
  version: z.number().int(),
  updated_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const AfEventSchema = z.object({
  event_id: z.string(),
  sequence: z.number().int(),
  event_type: z.string(),
  actor: z.string(),
  subject_ref: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string(),
}).passthrough();

export const AfTaskDetailSchema = z.object({
  definition: AfTaskDefinitionSchema,
  binding: AfBindingSchema,
  instance: AfInstanceSchema,
  ref_checks: z.array(AfRefCheckSchema),
  required_ref_kinds: z.array(z.string()),
  upstream_modules: z.record(z.string(), z.object({ required: z.number(), verified: z.number() })),
  downstream_modules: z.array(z.string()),
  approval: z
    .object({
      approval_id: z.string(),
      status: z.string(),
      decision: z.string().nullable(),
      reviewer: z.string().nullable(),
      subject_hash: z.string().nullable(),
      stale_reason: z.string().nullable(),
    })
    .nullable(),
  events: z.array(AfEventSchema),
});

export const AfApplicabilityResultSchema = z.object({
  applied: z.array(z.object({ task_id: z.string(), applicability: AfApplicabilitySchema, state: AfTaskStateSchema, version: z.number() })),
  skipped: z.array(z.object({ task_id: z.string(), code: z.string(), detail: z.string() })),
});

export const AfGatesSchema = z.object({ gates: z.array(AfGateSchema) });
export const AfAuditSchema = z.object({ events: z.array(AfEventSchema) });

export const AfMetricSchema = z.object({
  metric_id: z.string(),
  category: z.string(),
  label: z.string(),
  unit: z.string(),
  value: z.union([z.number(), NotMeasured]),
  reason: z.string().nullable(),
  inputs: z.array(z.string()),
  origin: z.enum(['MEASURED', 'SYNTHETIC', 'MIXED']).nullable(),
  windows: z.array(z.string()).optional(),
  window_consistent: z.boolean().optional(),
});
export const AfMetricsSchema = z.object({
  plan_id: z.string(),
  metrics: z.array(AfMetricSchema),
  measured: z.number().int(),
  not_measured: z.number().int(),
});

export const AfAssuranceRowSchema = z.object({
  record_id: z.string(),
  kind: AfAssuranceKindSchema,
  status: z.string(),
  created_at: z.string(),
  author_actor_id: z.string(),
  task_ids: z.array(z.string()),
  subject_refs: z.array(z.string()),
  record_hash: z.string(),
  supersedes_ref: z.string().nullable(),
  is_head: z.boolean(),
});
export const AfAssuranceListSchema = z.object({ items: z.array(AfAssuranceRowSchema) });

/** Use-time facts about a sealed delivery release candidate, as a Review binds and re-reads it. */
export const AfReleaseCandidateInspectionSchema = z
  .object({
    ref: z.string().regex(/^release-candidate:/),
    run_id: z.string(),
    contract_mode: z.string().nullable(),
    status: z.enum(['CURRENT', 'BLOCKED', 'NOT_SEALED', 'INVALID']),
    blocking: z.array(z.string()),
    release_authority: z.string(),
    candidate_manifest_hash: z.string().nullable(),
    approval_subject_hash: z.string().nullable(),
    artifact_refs: z.array(
      z.object({ artifact_id: z.string(), version_ref: z.string(), content_hash: z.string().nullable() }).strict(),
    ),
    payload_checks: z.array(
      z
        .object({
          artifact_id: z.string(),
          hash_verified: z.boolean(),
          bytes_read: z.number().int().nullable(),
          detail: z.string(),
        })
        .strict(),
    ),
    freshness: z
      .object({
        manifest_hash_verified: z.boolean(),
        approval_subject_verified: z.boolean(),
        artifacts_current: z.boolean(),
        dependencies_current: z.boolean(),
      })
      .strict()
      .nullable(),
    native_approval: z
      .object({
        approval_id: z.string(),
        status: z.string().nullable(),
        policy_version: z.string().nullable(),
        subject_bound: z.boolean(),
        decide_route: z.string(),
      })
      .strict()
      .nullable(),
  })
  .passthrough();

export const AfAssuranceRecordSchema = z.object({
  record: z
    .object({
      record_id: z.string(),
      schema_version: z.literal('amc-assurance/v1'),
      kind: AfAssuranceKindSchema,
      plan_id: z.string(),
      status: z.string(),
      subject_refs: z.array(z.string()),
      subject_content_hash: z.string().nullable(),
      evidence_refs: z.array(z.object({ ref: z.string(), status: z.string(), origin: z.string().nullable() })),
      dependency_snapshot_hash: z.string(),
      record_hash: z.string(),
      supersedes_ref: z.string().nullable(),
      authority: z.string(),
      body: z.record(z.string(), z.unknown()),
    })
    .passthrough(),
  integrity: z.object({ status: z.enum(['VERIFIED', 'INTEGRITY_FAILED']), problems: z.array(z.string()) }),
  subject_now: z
    .union([
      z.object({ subjects: z.array(z.object({ ref: z.string(), status: z.string() })), subject_current: z.boolean() }),
      z.object({
        release_candidate: z.union([
          AfReleaseCandidateInspectionSchema,
          z.object({ status: z.literal('NOT_FOUND'), blocking: z.array(z.string()) }),
        ]),
        subject_current: z.boolean(),
      }),
    ])
    .nullable(),
  superseded_by: z.array(z.string()),
  artifact_id: z.string(),
  artifact_version: z.number().int(),
  content_hash: z.string(),
});

export type AfTaskState = z.infer<typeof AfTaskStateSchema>;
export type AfApplicability = z.infer<typeof AfApplicabilitySchema>;
export type AfGateStatus = z.infer<typeof AfGateStatusSchema>;
export type AfArchetype = z.infer<typeof AfArchetypeSchema>;
export type AfStageGate = z.infer<typeof AfStageGateSchema>;
export type AfAssuranceKind = z.infer<typeof AfAssuranceKindSchema>;
export type AfCatalog = z.infer<typeof AfCatalogSchema>;
export type AfModule = z.infer<typeof AfModuleSchema>;
export type AfCounts = z.infer<typeof AfCountsSchema>;
export type AfGate = z.infer<typeof AfGateSchema>;
export type AfPlanView = z.infer<typeof AfPlanViewSchema>;
export type AfPlanRecord = z.infer<typeof AfPlanRecordSchema>;
export type AfTaskRow = z.infer<typeof AfTaskRowSchema>;
export type AfTaskDetail = z.infer<typeof AfTaskDetailSchema>;
export type AfRefCheck = z.infer<typeof AfRefCheckSchema>;
export type AfMetric = z.infer<typeof AfMetricSchema>;
export type AfMetrics = z.infer<typeof AfMetricsSchema>;
export type AfAssuranceRow = z.infer<typeof AfAssuranceRowSchema>;
export type AfAssuranceRecord = z.infer<typeof AfAssuranceRecordSchema>;
export type AfReleaseCandidateInspection = z.infer<typeof AfReleaseCandidateInspectionSchema>;
export type AfApplicabilityResult = z.infer<typeof AfApplicabilityResultSchema>;
