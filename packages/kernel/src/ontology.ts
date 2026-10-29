/**
 * N1 — department ontology (twin of `agency/kernel/ontology.py`).
 *
 * A closed vocabulary: departments, their capabilities, and the artifact types
 * each one owns. Every artifact type has exactly one owner; unknown values fail
 * closed with `OntologyError`.
 */
import { OntologyError } from './errors';
import { isMember } from './models';
import { pyStr, pySorted } from './pyformat';

export const ONTOLOGY_VERSION = 'amc-agency-ontology/n1-v1';

export const DEPARTMENTS = [
  'strategy', 'research', 'brand', 'creative', 'copy', 'design', 'product', 'engineering', 'growth', 'media',
  'analytics', 'quality', 'operations',
] as const;
export type Department = (typeof DEPARTMENTS)[number];

export const CAPABILITIES = [
  'research_synthesis', 'positioning', 'naming', 'identity_system', 'concepting', 'copywriting', 'art_direction',
  'product_definition', 'implementation', 'campaign_planning', 'media_planning', 'measurement',
  'brand_safety_review', 'release_management',
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const ARTIFACT_TYPES = [
  'research_brief', 'market_analysis', 'positioning_statement', 'brand_platform', 'naming_candidate',
  'identity_guidelines', 'creative_concept', 'copy_variant', 'design_brief', 'campaign_package', 'product_spec',
  'implementation_plan', 'media_plan', 'measurement_plan', 'qa_report', 'release_record',
  // compiler artifacts
  'brand_core', 'brand_guidelines_doc', 'design_token_set', 'design_system_spec', 'website_lockup_spec',
  'asset_prompt_set', 'business_model_spec', 'offer_definition', 'app_build_spec', 'automation_spec',
  'knowledge_capsule',
  // project OS
  'media_asset',
] as const;
export type ArtifactType = (typeof ARTIFACT_TYPES)[number];

export interface DepartmentDefinition {
  readonly department: Department;
  readonly mandate: string;
  readonly capabilities: ReadonlySet<Capability>;
  readonly owned_artifact_types: ReadonlySet<ArtifactType>;
  /** Departments whose approval is required before this department's artifacts leave the agency. */
  readonly release_reviewers: ReadonlySet<Department>;
}

function definition(
  department: Department,
  mandate: string,
  capabilities: readonly Capability[],
  owned: readonly ArtifactType[],
  releaseReviewers: readonly Department[] = [],
): DepartmentDefinition {
  return {
    department,
    mandate,
    capabilities: new Set(capabilities),
    owned_artifact_types: new Set(owned),
    release_reviewers: new Set(releaseReviewers),
  };
}

const DEFINITIONS: readonly DepartmentDefinition[] = [
  definition('research', 'Gather and synthesize external evidence about market, audience, and category.',
    ['research_synthesis', 'measurement'], ['research_brief', 'market_analysis', 'knowledge_capsule']),
  definition('strategy', 'Convert evidence into a defensible market position and engagement plan.',
    ['positioning', 'campaign_planning'], ['positioning_statement', 'business_model_spec', 'offer_definition']),
  definition('brand', 'Own brand platform, naming, and identity coherence across every surface.',
    ['naming', 'identity_system', 'positioning'],
    ['brand_platform', 'naming_candidate', 'identity_guidelines', 'brand_core', 'brand_guidelines_doc'], ['quality']),
  definition('creative', 'Translate strategy into distinct campaign concepts.',
    ['concepting', 'art_direction'], ['creative_concept', 'asset_prompt_set', 'media_asset'], ['quality']),
  definition('copy', 'Write channel-ready language consistent with the brand platform.',
    ['copywriting'], ['copy_variant'], ['quality']),
  definition('design', 'Specify and direct visual execution.', ['art_direction', 'identity_system'],
    ['design_brief', 'design_token_set', 'design_system_spec', 'website_lockup_spec'], ['quality']),
  definition('product', 'Define what is being taken to market and its acceptance criteria.',
    ['product_definition'], ['product_spec']),
  definition('engineering', 'Plan and carry out technical implementation.',
    ['implementation'], ['implementation_plan', 'app_build_spec', 'automation_spec']),
  definition('growth', 'Assemble campaigns and own the growth loop.',
    ['campaign_planning', 'measurement'], ['campaign_package'], ['quality']),
  definition('media', 'Plan paid distribution. Spend authority is escrowed, never implicit.',
    ['media_planning'], ['media_plan'], ['quality', 'operations']),
  definition('analytics', 'Define measurement and report outcomes against a verified data source.',
    ['measurement'], ['measurement_plan']),
  definition('quality', 'Adjudicate brand safety and evidence sufficiency before release.',
    ['brand_safety_review'], ['qa_report']),
  definition('operations', 'Own release mechanics and external-side-effect authorization.',
    ['release_management'], ['release_record']),
];

export const DEPARTMENT_REGISTRY: ReadonlyMap<Department, DepartmentDefinition> = new Map(
  DEFINITIONS.map((item) => [item.department, item]),
);

function buildOwnerIndex(): ReadonlyMap<ArtifactType, Department> {
  const owners = new Map<ArtifactType, Department>();
  for (const item of DEFINITIONS) {
    for (const artifactType of item.owned_artifact_types) {
      if (owners.has(artifactType)) {
        throw new Error(`Artifact type ${artifactType} is owned by more than one department`);
      }
      owners.set(artifactType, item.department);
    }
  }
  return owners;
}

/** Reverse index: the single department that owns each artifact type. */
export const ARTIFACT_TYPE_OWNER: ReadonlyMap<ArtifactType, Department> = buildOwnerIndex();

/** Coerce a stored string into a Department, failing closed on unknowns. */
export function resolveDepartment(value: unknown): Department {
  if (isMember(DEPARTMENTS, value)) return value;
  throw new OntologyError(
    `Unknown department '${pyStr(value)}'. Known departments: ${pySorted(DEPARTMENTS).join(', ')}`,
  );
}

export function resolveArtifactType(value: unknown): ArtifactType {
  if (isMember(ARTIFACT_TYPES, value)) return value;
  throw new OntologyError(
    `Unknown artifact type '${pyStr(value)}'. Known artifact types: ${pySorted(ARTIFACT_TYPES).join(', ')}`,
  );
}

function lookup<K, V>(map: ReadonlyMap<K, V>, key: K): V {
  const value = map.get(key);
  if (value === undefined) throw new Error(`kernel table is missing ${String(key)}`);
  return value;
}

export function departmentDefinition(value: unknown): DepartmentDefinition {
  return lookup(DEPARTMENT_REGISTRY, resolveDepartment(value));
}

export function owningDepartment(artifactType: unknown): Department {
  return lookup(ARTIFACT_TYPE_OWNER, resolveArtifactType(artifactType));
}

/** Fail closed when a department claims an artifact type it does not own. */
export function assertDepartmentOwns(department: unknown, artifactType: unknown): void {
  const resolvedDepartment = resolveDepartment(department);
  const resolvedType = resolveArtifactType(artifactType);
  const owner = lookup(ARTIFACT_TYPE_OWNER, resolvedType);
  if (owner !== resolvedDepartment) {
    throw new OntologyError(
      `Department '${resolvedDepartment}' does not own artifact type '${resolvedType}' (owned by '${owner}')`,
    );
  }
}

/** Python checks `capability in definition.capabilities`, so an unknown capability is simply false. */
export function hasCapability(department: unknown, capability: string): boolean {
  return (departmentDefinition(department).capabilities as ReadonlySet<string>).has(capability);
}

export interface DepartmentSnapshot {
  readonly department: Department;
  readonly mandate: string;
  readonly capabilities: Capability[];
  readonly owned_artifact_types: ArtifactType[];
  readonly release_reviewers: Department[];
}

/** Serializable view of the ontology, identical to Python's `ontology_snapshot()`. */
export function ontologySnapshot(): { ontology_version: string; departments: DepartmentSnapshot[] } {
  const ordered = [...DEFINITIONS].sort((a, b) => (a.department < b.department ? -1 : 1));
  return {
    ontology_version: ONTOLOGY_VERSION,
    departments: ordered.map((item) => ({
      department: item.department,
      mandate: item.mandate,
      capabilities: pySorted(item.capabilities),
      owned_artifact_types: pySorted(item.owned_artifact_types),
      release_reviewers: pySorted(item.release_reviewers),
    })),
  };
}
