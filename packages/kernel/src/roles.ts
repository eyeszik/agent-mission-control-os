/**
 * N3 — role contracts (twin of `agency/kernel/roles.py`).
 *
 * What a role may produce, what it consumes, its evidence floor, and its
 * authority flags. Role identity never grants publish/spend authority:
 * `external_side_effect` roles still require human approval.
 */
import { KernelValueError, OntologyError, RoleContractError } from './errors';
import { isMember } from './models';
import {
  ARTIFACT_TYPES,
  DEPARTMENTS,
  assertDepartmentOwns,
  departmentDefinition,
  type ArtifactType,
  type Capability,
  type Department,
} from './ontology';
import { pyRepr, pySorted, pyStr } from './pyformat';

export const ROLE_CONTRACT_VERSION = 'amc-agency-roles/n3-v1';

export interface RoleContract {
  readonly role_id: string;
  readonly department: Department;
  readonly mandate: string;
  readonly capabilities: ReadonlySet<Capability>;
  readonly produces: ReadonlySet<ArtifactType>;
  readonly consumes: ReadonlySet<ArtifactType>;
  readonly min_evidence: number;
  readonly requires_human_approval: boolean;
  readonly external_side_effect: boolean;
}

/**
 * Python's `role_id` validator: non-empty, and alphanumeric once `_` and `-`
 * are removed. Python's `str.isalnum()` is Unicode-aware; `\p{L}\p{N}` is the
 * JS equivalent (letters and numbers of every script).
 */
export function isRoleIdSlug(value: string): boolean {
  const stripped = value.replace(/[_-]/g, '');
  return stripped.length > 0 && /^[\p{L}\p{N}]+$/u.test(stripped);
}

interface ContractOptions {
  readonly consumes?: readonly ArtifactType[];
  readonly min_evidence?: number;
  readonly requires_human_approval?: boolean;
  readonly external_side_effect?: boolean;
}

function contract(
  roleId: string,
  department: Department,
  mandate: string,
  capabilities: readonly Capability[],
  produces: readonly ArtifactType[],
  options: ContractOptions = {},
): RoleContract {
  if (!isRoleIdSlug(roleId)) throw new KernelValueError(`role_id must be a non-empty slug, got '${roleId}'`);
  const minEvidence = options.min_evidence ?? 0;
  if (!Number.isInteger(minEvidence) || minEvidence < 0) throw new KernelValueError('min_evidence must be >= 0');
  return {
    role_id: roleId,
    department,
    mandate,
    capabilities: new Set(capabilities),
    produces: new Set(produces),
    consumes: new Set(options.consumes ?? []),
    min_evidence: minEvidence,
    requires_human_approval: options.requires_human_approval ?? true,
    external_side_effect: options.external_side_effect ?? false,
  };
}

const CONTRACTS: readonly RoleContract[] = [
  contract('market_researcher', 'research',
    'Collect and synthesize external evidence about the category and audience.',
    ['research_synthesis'], ['research_brief', 'market_analysis', 'knowledge_capsule'], { min_evidence: 3 }),
  contract('brand_strategist', 'strategy',
    'Derive a defensible position and the commercial model that carries it.',
    ['positioning'], ['positioning_statement', 'business_model_spec', 'offer_definition'],
    { consumes: ['research_brief', 'market_analysis'], min_evidence: 2 }),
  contract('brand_architect', 'brand',
    'Author the canonical brand object and the identity system derived from it.',
    ['naming', 'identity_system'],
    ['brand_platform', 'naming_candidate', 'identity_guidelines', 'brand_core', 'brand_guidelines_doc'],
    { consumes: ['positioning_statement'], min_evidence: 2 }),
  contract('creative_director', 'creative',
    'Generate campaign concepts and the reproducible prompts that realize them.',
    ['concepting', 'art_direction'], ['creative_concept', 'asset_prompt_set', 'media_asset'],
    { consumes: ['brand_platform', 'positioning_statement', 'brand_core'] }),
  contract('copywriter', 'copy', 'Write channel-ready language for approved concepts.',
    ['copywriting'], ['copy_variant'], { consumes: ['creative_concept', 'brand_platform'] }),
  contract('design_lead', 'design',
    'Compile the brand object into tokens, components, and page composition.',
    ['art_direction'], ['design_brief', 'design_token_set', 'design_system_spec', 'website_lockup_spec'],
    { consumes: ['creative_concept', 'identity_guidelines', 'brand_core'] }),
  contract('product_manager', 'product', 'Define the offer and its acceptance criteria.',
    ['product_definition'], ['product_spec'], { consumes: ['positioning_statement'], min_evidence: 1 }),
  contract('implementation_lead', 'engineering',
    'Specify technical delivery, whether an application build or an automation.',
    ['implementation'], ['implementation_plan', 'app_build_spec', 'automation_spec'],
    { consumes: ['product_spec', 'design_system_spec'] }),
  contract('growth_lead', 'growth', 'Assemble the campaign package from approved components.',
    ['campaign_planning'], ['campaign_package'], { consumes: ['copy_variant', 'design_brief', 'creative_concept'] }),
  contract('media_planner', 'media', 'Plan paid distribution. Spend requires escrowed authorization.',
    ['media_planning'], ['media_plan'], { consumes: ['campaign_package'], external_side_effect: true }),
  contract('analytics_lead', 'analytics', 'Define measurement against a verified data source.',
    ['measurement'], ['measurement_plan'], { consumes: ['campaign_package'], min_evidence: 1 }),
  contract('brand_safety_reviewer', 'quality', 'Adjudicate brand safety and evidence sufficiency before release.',
    ['brand_safety_review'], ['qa_report'],
    { consumes: ['campaign_package', 'copy_variant'], requires_human_approval: false }),
  contract('release_manager', 'operations', 'Execute release mechanics once every gate has cleared.',
    ['release_management'], ['release_record'],
    { consumes: ['campaign_package', 'qa_report'], external_side_effect: true }),
];

export const ROLE_REGISTRY: ReadonlyMap<string, RoleContract> = new Map(CONTRACTS.map((c) => [c.role_id, c]));

export function getRole(roleId: string): RoleContract {
  const found = ROLE_REGISTRY.get(roleId);
  if (found) return found;
  throw new RoleContractError(`Unknown role '${roleId}'. Known roles: ${pySorted(ROLE_REGISTRY.keys()).join(', ')}`);
}

/** Python uses the bare enum constructor here, so an unknown value is a plain ValueError, not an OntologyError. */
function enumValue<T extends string>(members: readonly T[], value: unknown, enumName: string): T {
  if (isMember(members, value)) return value;
  const shown = typeof value === 'string' ? pyRepr(value) : pyStr(value);
  throw new KernelValueError(`${shown} is not a valid ${enumName}`);
}

export function rolesForDepartment(department: unknown): RoleContract[] {
  const resolved = enumValue(DEPARTMENTS, department, 'Department');
  return CONTRACTS.filter((c) => c.department === resolved).sort((a, b) => (a.role_id < b.role_id ? -1 : 1));
}

/** Fail closed when a role emits an artifact type outside its contract. */
export function assertRoleMayProduce(roleId: string, artifactType: unknown): void {
  const role = getRole(roleId);
  const resolved = enumValue(ARTIFACT_TYPES, artifactType, 'ArtifactType');
  if (!role.produces.has(resolved)) {
    throw new RoleContractError(
      `Role '${roleId}' may not produce artifact type '${resolved}'; ` +
        `declared outputs: ${pySorted(role.produces).join(', ')}`,
    );
  }
}

export function assertEvidenceSufficient(roleId: string, evidenceCount: number): void {
  const role = getRole(roleId);
  if (evidenceCount < role.min_evidence) {
    throw new RoleContractError(
      `Role '${roleId}' requires at least ${role.min_evidence} evidence item(s), got ${pyStr(evidenceCount)}`,
    );
  }
}

function contractProblems(role: RoleContract): string[] {
  const problems: string[] = [];
  for (const artifactType of pySorted(role.produces)) {
    try {
      assertDepartmentOwns(role.department, artifactType);
    } catch (error) {
      if (!(error instanceof OntologyError)) throw error;
      problems.push(`role '${role.role_id}': ${error.message}`);
    }
  }
  const departmental = departmentDefinition(role.department).capabilities;
  for (const capability of pySorted([...role.capabilities].filter((c) => !departmental.has(c)))) {
    problems.push(
      `role '${role.role_id}' claims capability '${capability}' that department '${role.department}' does not hold`,
    );
  }
  if (role.external_side_effect && !role.requires_human_approval) {
    problems.push(`role '${role.role_id}' can cause an external side effect but does not require human approval`);
  }
  return problems;
}

function coverageProblems(ordered: readonly RoleContract[]): string[] {
  const produced = new Set<ArtifactType>(ordered.flatMap((c) => [...c.produces]));
  const problems = pySorted(ARTIFACT_TYPES.filter((t) => !produced.has(t))).map(
    (t) => `artifact type '${t}' has no producing role`,
  );
  for (const role of ordered) {
    for (const t of pySorted([...role.consumes].filter((c) => !produced.has(c)))) {
      problems.push(`role '${role.role_id}' consumes '${t}', which no role produces`);
    }
  }
  return problems;
}

/** Structural self-check across N1 and N3. Returns every problem rather than throwing. */
export function validateRegistry(): string[] {
  const ordered = [...CONTRACTS].sort((a, b) => (a.role_id < b.role_id ? -1 : 1));
  return [...ordered.flatMap(contractProblems), ...coverageProblems(ordered)];
}

export interface RoleSnapshot {
  readonly role_id: string;
  readonly department: Department;
  readonly mandate: string;
  readonly capabilities: Capability[];
  readonly produces: ArtifactType[];
  readonly consumes: ArtifactType[];
  readonly min_evidence: number;
  readonly requires_human_approval: boolean;
  readonly external_side_effect: boolean;
}

export function roleSnapshotEntry(role: RoleContract): RoleSnapshot {
  return {
    ...role,
    capabilities: pySorted(role.capabilities),
    produces: pySorted(role.produces),
    consumes: pySorted(role.consumes),
  };
}

/** Serializable view, identical to Python's `role_snapshot()`. */
export function roleSnapshot(): { role_contract_version: string; roles: RoleSnapshot[] } {
  const ordered = [...CONTRACTS].sort((a, b) => (a.role_id < b.role_id ? -1 : 1));
  return { role_contract_version: ROLE_CONTRACT_VERSION, roles: ordered.map(roleSnapshotEntry) };
}
