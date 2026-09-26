import { z } from 'zod';

export const ProofStatusSchema = z.enum(['PROVED', 'UNPROVED', 'UNKNOWN']);
export const ResearchStatusSchema = z.enum(['READY', 'NEEDS_EXTERNAL_EVIDENCE']);
export const VerificationStatusSchema = z.enum(['PASS', 'FAIL', 'NOT_RUN', 'NOT_APPLICABLE']);
export const LicenseStatusSchema = z.enum(['SOURCE_ATTACHED', 'UNKNOWN', 'NOT_REQUIRED']);
export const PortfolioPermissionSchema = z.enum(['GRANTED', 'DENIED', 'UNKNOWN']);
export const LegalStatusSchema = z.enum(['UNKNOWN', 'SOURCE_ATTACHED', 'COUNSEL_REQUIRED']);
export const TelemetryStatusSchema = z.enum(['BOUND', 'PARTIAL', 'UNBOUND']);
export const ModelCardStatusSchema = z.enum(['COMPLETE', 'INCOMPLETE']);

export const ResearchEvidenceInputSchema = z.object({
  evidence_id: z.string().min(1),
  source_ref: z.string().min(1),
  summary: z.string().min(1),
  source_class: z.enum(['USER_ASSERTION', 'PRIMARY', 'SECONDARY', 'REPOSITORY']).default('USER_ASSERTION'),
  verified: z.boolean().default(false),
});

export const ClaimProofInputSchema = z
  .object({
    claim: z.string().min(1),
    proof_status: ProofStatusSchema.default('UNKNOWN'),
    evidence_refs: z.array(z.string()).default([]),
    ship_as_fact: z.boolean().default(false),
  })
  .superRefine((value, ctx) => {
    if (value.proof_status === 'PROVED' && value.evidence_refs.length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['evidence_refs'],
        message: 'PROVED claims require at least one evidence_ref',
      });
    }
  });

export const AssetRightsInputSchema = z
  .object({
    asset_id: z.string().min(1),
    owner: z.string().nullable().optional(),
    license_status: LicenseStatusSchema.default('UNKNOWN'),
    license_ref: z.string().nullable().optional(),
    release_use_authorized: z.boolean().default(false),
    portfolio_permission: PortfolioPermissionSchema.default('UNKNOWN'),
    territory: z.string().nullable().optional(),
    expires_at: z.string().nullable().optional(),
    access_expires_at: z.string().nullable().optional(),
    contact: z.string().nullable().optional(),
    offboarding_action: z.string().nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.license_status === 'SOURCE_ATTACHED' && !value.license_ref) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['license_ref'],
        message: 'SOURCE_ATTACHED license_status requires license_ref',
      });
    }
  });

export const AccessibilityCheckInputSchema = z
  .object({
    check: z.enum(['contrast', 'keyboard', 'assistive_technology', 'reduced_motion']),
    status: VerificationStatusSchema,
    evidence_ref: z.string().nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (value.status === 'PASS' && !value.evidence_ref) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['evidence_ref'],
        message: 'PASS accessibility checks require evidence_ref',
      });
    }
  });

export const MediaPlanningInputSchema = z.object({
  markets: z.array(z.string()).default([]),
  flight_start: z.string().nullable().optional(),
  flight_end: z.string().nullable().optional(),
  budget_minor: z.number().int().nonnegative().nullable().optional(),
  currency: z.string().length(3).nullable().optional(),
  kpis: z.array(z.string()).default([]),
  creative_specs: z.array(z.string()).default([]),
  execution_requested: z.boolean().default(false),
});

export const ResearchPackageSchema = z.object({
  status: ResearchStatusSchema,
  verified_evidence_count: z.number().int().nonnegative(),
  audience_brief: z.string(),
  interview_guide: z.array(z.string()),
  competitive_audit: z.array(z.string()),
  stakeholder_map: z.array(z.string()),
  perception_gap: z.array(z.string()),
  category_language: z.array(z.string()),
  evidence_refs: z.array(z.string()),
  limitations: z.array(z.string()),
});

export const ClaimProofRecordSchema = z.object({
  claim_id: z.string(),
  claim: z.string(),
  proof_status: ProofStatusSchema,
  evidence_refs: z.array(z.string()),
  ship_as_fact: z.boolean(),
});

export const ClaimsProofRegistrySchema = z.object({
  claims: z.array(ClaimProofRecordSchema),
  blocking_reasons: z.array(z.string()),
});

export const RightsRecordSchema = z.object({
  asset_id: z.string(),
  owner: z.string().nullable(),
  license_status: LicenseStatusSchema,
  license_ref: z.string().nullable(),
  release_use_authorized: z.boolean(),
  portfolio_permission: PortfolioPermissionSchema,
  territory: z.string().nullable(),
  expires_at: z.string().nullable(),
  access_expires_at: z.string().nullable(),
  contact: z.string().nullable(),
  offboarding_action: z.string().nullable(),
});

export const HandoffRightsManifestSchema = z.object({
  assets: z.array(RightsRecordSchema),
  blocking_reasons: z.array(z.string()),
  notes: z.array(z.string()),
});

export const AccessibilityCheckSchema = z.object({
  check: z.string(),
  status: VerificationStatusSchema,
  evidence_ref: z.string().nullable(),
});

export const AccessibilityEvidenceSchema = z.object({
  applicable: z.boolean(),
  standard: z.literal('WCAG 2.2'),
  checks: z.array(AccessibilityCheckSchema),
  blocking_reasons: z.array(z.string()),
  limitations: z.array(z.string()),
});

export const MediaTraffickingRowSchema = z.object({
  channel: z.string(),
  market: z.string().nullable(),
  flight_start: z.string().nullable(),
  flight_end: z.string().nullable(),
  creative_spec: z.string(),
  status: z.literal('PLANNING_ONLY'),
});

export const MediaPlanSchema = z.object({
  execution_mode: z.literal('PLANNING_ONLY'),
  audience: z.string(),
  markets: z.array(z.string()),
  flight_start: z.string().nullable(),
  flight_end: z.string().nullable(),
  budget_minor: z.number().int().nonnegative().nullable(),
  currency: z.string().nullable(),
  kpis: z.array(z.string()),
  creative_specs: z.array(z.string()),
  trafficking_sheet: z.array(MediaTraffickingRowSchema),
  execution_requested: z.boolean(),
  blocking_reasons: z.array(z.string()),
  notes: z.array(z.string()),
});

export const LegalReadinessSchema = z.object({
  status: LegalStatusSchema,
  regulatory_context: z.array(z.string()),
  source_refs: z.array(z.string()),
  blocking_reasons: z.array(z.string()),
  note: z.string(),
});

export const TelemetrySignalSchema = z.object({
  signal: z.enum(['events', 'logs', 'metrics', 'traces']),
  status: TelemetryStatusSchema,
  evidence_ref: z.string().nullable(),
  owner: z.string(),
  retention: z.string(),
  alert_condition: z.string(),
});

export const ObservabilityContractSchema = z.object({
  schema_version: z.literal('amc-observability/v1'),
  service_identity: z.literal('UNBOUND'),
  status: z.literal('PARTIAL'),
  signals: z.array(TelemetrySignalSchema),
  notes: z.array(z.string()),
});

export const SLOObjectiveSchema = z.object({
  name: z.string(),
  indicator: z.string(),
  target: z.number().nullable(),
  target_status: z.literal('BASELINE_REQUIRED'),
  owner: z.string(),
  evidence_refs: z.array(z.string()),
});

export const SLOContractSchema = z.object({
  schema_version: z.literal('amc-slo/v1'),
  status: z.literal('BASELINE_REQUIRED'),
  objectives: z.array(SLOObjectiveSchema),
  notes: z.array(z.string()),
});

export const ModelCardSchema = z.object({
  task: z.string(),
  provider: z.string().nullable(),
  model: z.string().nullable(),
  mode: z.string(),
  schema_version: z.string(),
  prompt_version: z.string(),
  prompt_hash: z.string(),
  status: ModelCardStatusSchema,
  evaluation_mode: z.literal('HEURISTIC_ONLY'),
  limitations: z.array(z.string()),
});

export const FullServicePlanSchema = z.object({
  schema_version: z.literal('amc-full-service/v1'),
  market: z.string().nullable(),
  language: z.string().nullable(),
  locale: z.string().nullable(),
  research: ResearchPackageSchema,
  claims: ClaimsProofRegistrySchema,
  handoff_rights: HandoffRightsManifestSchema,
  accessibility: AccessibilityEvidenceSchema,
  media: MediaPlanSchema,
  legal_readiness: LegalReadinessSchema,
  observability: ObservabilityContractSchema,
  slo: SLOContractSchema,
  model_cards: z.array(ModelCardSchema),
  blocking_reasons: z.array(z.string()),
  advisories: z.array(z.string()),
});

export type ResearchEvidenceInput = z.infer<typeof ResearchEvidenceInputSchema>;
export type ClaimProofInput = z.infer<typeof ClaimProofInputSchema>;
export type AssetRightsInput = z.infer<typeof AssetRightsInputSchema>;
export type AccessibilityCheckInput = z.infer<typeof AccessibilityCheckInputSchema>;
export type MediaPlanningInput = z.infer<typeof MediaPlanningInputSchema>;
export type FullServicePlan = z.infer<typeof FullServicePlanSchema>;
