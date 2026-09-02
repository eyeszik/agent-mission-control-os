import { z } from 'zod';

/**
 * N1 — department ontology, mirrored from
 * services/langgraph/agency/kernel/ontology.py.
 *
 * Both halves are verified against each other by
 * scripts/verify_ontology_parity.py, which fails CI on drift. Edit the two
 * files together or the parity gate will block.
 */

export const ONTOLOGY_VERSION = 'amc-agency-ontology/n1-v1';

export const DEPARTMENTS = [
  'strategy',
  'research',
  'brand',
  'creative',
  'copy',
  'design',
  'product',
  'engineering',
  'growth',
  'media',
  'analytics',
  'quality',
  'operations'
] as const;

export const CAPABILITIES = [
  'research_synthesis',
  'positioning',
  'naming',
  'identity_system',
  'concepting',
  'copywriting',
  'art_direction',
  'product_definition',
  'implementation',
  'campaign_planning',
  'media_planning',
  'measurement',
  'brand_safety_review',
  'release_management'
] as const;

export const AGENCY_ARTIFACT_TYPES = [
  'research_brief',
  'market_analysis',
  'positioning_statement',
  'brand_platform',
  'naming_candidate',
  'identity_guidelines',
  'creative_concept',
  'copy_variant',
  'design_brief',
  'campaign_package',
  'product_spec',
  'implementation_plan',
  'media_plan',
  'measurement_plan',
  'qa_report',
  'release_record',
  'brand_core',
  'brand_guidelines_doc',
  'design_token_set',
  'design_system_spec',
  'website_lockup_spec',
  'asset_prompt_set',
  'business_model_spec',
  'offer_definition',
  'app_build_spec',
  'automation_spec',
  'knowledge_capsule'
] as const;

export const DepartmentSchema = z.enum(DEPARTMENTS);
export const CapabilitySchema = z.enum(CAPABILITIES);
export const AgencyArtifactTypeSchema = z.enum(AGENCY_ARTIFACT_TYPES);

export const DepartmentDefinitionSchema = z.object({
  department: DepartmentSchema,
  mandate: z.string().min(1),
  capabilities: z.array(CapabilitySchema),
  owned_artifact_types: z.array(AgencyArtifactTypeSchema),
  release_reviewers: z.array(DepartmentSchema)
});

export const OntologySnapshotSchema = z.object({
  ontology_version: z.literal(ONTOLOGY_VERSION),
  departments: z.array(DepartmentDefinitionSchema)
});

export type Department = z.infer<typeof DepartmentSchema>;
export type Capability = z.infer<typeof CapabilitySchema>;
export type AgencyArtifactType = z.infer<typeof AgencyArtifactTypeSchema>;
export type DepartmentDefinition = z.infer<typeof DepartmentDefinitionSchema>;
export type OntologySnapshot = z.infer<typeof OntologySnapshotSchema>;

/** Which department owns each artifact type. Ownership is exclusive. */
export const ARTIFACT_TYPE_OWNER: Record<AgencyArtifactType, Department> = {
  research_brief: 'research',
  market_analysis: 'research',
  positioning_statement: 'strategy',
  brand_platform: 'brand',
  naming_candidate: 'brand',
  identity_guidelines: 'brand',
  creative_concept: 'creative',
  copy_variant: 'copy',
  design_brief: 'design',
  campaign_package: 'growth',
  product_spec: 'product',
  implementation_plan: 'engineering',
  media_plan: 'media',
  measurement_plan: 'analytics',
  qa_report: 'quality',
  release_record: 'operations',
  brand_core: 'brand',
  brand_guidelines_doc: 'brand',
  design_token_set: 'design',
  design_system_spec: 'design',
  website_lockup_spec: 'design',
  asset_prompt_set: 'creative',
  business_model_spec: 'strategy',
  offer_definition: 'strategy',
  app_build_spec: 'engineering',
  automation_spec: 'engineering',
  knowledge_capsule: 'research'
};

export function owningDepartment(artifactType: AgencyArtifactType): Department {
  return ARTIFACT_TYPE_OWNER[artifactType];
}
