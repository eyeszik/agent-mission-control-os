/**
 * Twin of `agency/compiled/authority.py` (T11): the Authority Shadow Graph and
 * the RoleOS → N3 AuthorityBridge.
 *
 * Two different things are bound here and never equated (spec §23): the RoleOS
 * specialist (expertise, routing, procedure) and the N3 RoleContract (the
 * runtime permission envelope). The side-effect ceiling is the intersection of
 * both; RoleOS runtime authority is DENY_CONSEQUENTIAL_BY_DEFAULT, so no
 * specialist lifts a binding above DRAFT. Consequential work additionally needs
 * an explicit AuthorityGrant plus an exact approval.
 */
import { ROLE_REGISTRY } from '@amc/kernel';
import { CompiledKeyError, RoleResolutionError } from './errors';
import { pyRepr } from '@amc/kernel';
import { semanticHash, type HashValue } from './hashing';
import { compareCodePoints, sortStrings, uniqueSorted } from './python';
import { resolveRoles, type RoleOSRegistry } from './roleos';

export const SIDE_EFFECT_RANK: Readonly<Record<string, number>> = {
  PURE: 0, DRAFT: 1, REVERSIBLE_WRITE: 2, IRREVERSIBLE_WRITE: 3,
};
export const CONSEQUENTIAL: ReadonlySet<string> = new Set(['REVERSIBLE_WRITE', 'IRREVERSIBLE_WRITE']);

export interface SpecialistQuery {
  readonly skill_name: string;
  readonly department: string;
}

const q = (skill_name: string, department: string): SpecialistQuery => ({ skill_name, department });

/** N3 runtime role → the sealed RoleOS specialist that carries its expertise. */
export const N3_SPECIALISTS: ReadonlyMap<string, SpecialistQuery> = new Map([
  ['market_researcher', q('market-researcher', 'strategy')],
  ['brand_strategist', q('brand-strategist', 'brand')],
  ['brand_architect', q('brand-architecture-strategist', 'brand')],
  ['creative_director', q('creative-director', 'creative')],
  ['copywriter', q('copywriter', 'creative')],
  ['design_lead', q('art-director', 'creative')],
  ['product_manager', q('product-manager', 'experience-product')],
  ['implementation_lead', q('engineering-manager', 'technology')],
  ['growth_lead', q('creative-producer', 'production')],
  ['media_planner', q('media-planner', 'growth-media')],
  ['analytics_lead', q('measurement-strategist', 'ai-data')],
  ['brand_safety_reviewer', q('qa-engineer', 'technology')],
  ['release_manager', q('project-manager', 'client-delivery')],
]);

export type BindingStatus = 'RESOLVED' | 'CAPABILITY_GAP' | 'AUTHORITY_UNRESOLVED';

/** A delegated consequential authority; fields mirror the sealed grant contract. */
export interface AuthorityGrant {
  readonly grant_id: string;
  readonly actor_role_id: string;
  readonly operation: string;
  readonly target: string;
  readonly issued_by: string;
  readonly expires_at: string;
}

export interface SpecialistBinding {
  readonly specialist_role_id: string | null;
  readonly required_capabilities: readonly string[];
  readonly source_skill_hashes: readonly string[];
  readonly runtime_authority_role_id: string;
  readonly permitted_artifacts: readonly string[];
  readonly permitted_tools: readonly string[];
  readonly side_effect_ceiling: string;
  readonly approval_requirements: readonly string[];
  readonly segregation_constraints: readonly string[];
  readonly status: BindingStatus;
  readonly blockers: readonly string[];
  readonly binding_hash: string;
}

/** Highest side-effect class a sealed RoleOS authority block permits. */
export function roleosCeiling(authority: Readonly<Record<string, unknown>>): string {
  if (authority['can_execute_irreversible']) return 'IRREVERSIBLE_WRITE';
  if (authority['can_execute_reversible_external']) return 'REVERSIBLE_WRITE';
  if (authority['can_execute_draft']) return 'DRAFT';
  return 'PURE';
}

/** `SIDE_EFFECT_RANK[x]`: Python raises KeyError for an unknown class. */
function rankOf(cls: string): number {
  const rank = SIDE_EFFECT_RANK[cls];
  if (rank === undefined) throw new CompiledKeyError(pyRepr(cls));
  return rank;
}

function minClass(a: string, b: string): string {
  return (SIDE_EFFECT_RANK[a] ?? 0) <= (SIDE_EFFECT_RANK[b] ?? 0) ? a : b;
}

export function grantContractFailures(grant: AuthorityGrant, requiredFields: Iterable<string>, asOf: string): string[] {
  const record = grant as unknown as Readonly<Record<string, string | undefined>>;
  const failures = [...requiredFields].filter((f) => !record[f]).map((f) => `GRANT_FIELD_MISSING:${f}`);
  if (grant.expires_at && compareCodePoints(grant.expires_at, asOf) <= 0) failures.push('GRANT_EXPIRED');
  if (grant.issued_by === grant.actor_role_id) failures.push('GRANT_SELF_ISSUED');
  return failures;
}

export interface BindInput {
  readonly runtime_role_id: string;
  readonly side_effect_class: string;
  readonly operation: string;
  readonly target: string;
  readonly grants?: readonly AuthorityGrant[];
  readonly approval_refs?: readonly string[];
  readonly as_of: string;
  readonly creator_role_id?: string | null;
}

/** Resolves specialist + runtime authority for a work node without inflating either. */
export class AuthorityBridge {
  private readonly sourceHashes: ReadonlyMap<string, string>;

  constructor(readonly registry: RoleOSRegistry, sourceHashes: ReadonlyMap<string, string> = new Map()) {
    this.sourceHashes = new Map(sourceHashes);
  }

  /** Exact skill-name selection. A partial token overlap is not a specialist. */
  resolveSpecialist(query: SpecialistQuery): string | null {
    let matches;
    try {
      matches = resolveRoles(this.registry, [query.skill_name], { department_hint: query.department, limit: 3 });
    } catch (error) {
      if (error instanceof RoleResolutionError) return null;
      throw error;
    }
    for (const match of matches) {
      const role = this.registry.getRole(match.role_id);
      if (role.skill_name === query.skill_name) return role.role_id;
    }
    return null;
  }

  private consequentialBlockers(input: BindInput, specialistId: string | null, hasContract: boolean, external: boolean): string[] {
    const blockers: string[] = [];
    const required = this.registry.grant_contract.required ?? [];
    if (!hasContract || !external) {
      blockers.push(`AUTHORITY_UNRESOLVED:N3 ${input.runtime_role_id} declares no external side effect`);
    }
    const matching = (input.grants ?? []).filter((g) => (g.actor_role_id === input.runtime_role_id
      || g.actor_role_id === specialistId) && g.operation === input.operation && g.target === input.target);
    if (!matching.some((g) => !grantContractFailures(g, required, input.as_of).length)) {
      const reasons = uniqueSorted(matching.flatMap((g) => grantContractFailures(g, required, input.as_of)));
      blockers.push(`AUTHORITY_UNRESOLVED:no valid grant${reasons.length ? ` (${reasons.join(', ')})` : ''}`);
    }
    const needsApproval = this.registry.grant_contract.high_consequence_requires_exact_approval_ref ?? true;
    if (needsApproval && !(input.approval_refs ?? []).length) blockers.push('AUTHORITY_UNRESOLVED:missing exact approval ref');
    return blockers;
  }

  bind(input: BindInput): SpecialistBinding {
    const contract = ROLE_REGISTRY.get(input.runtime_role_id);
    const blockers: string[] = [];
    if (contract === undefined) blockers.push(`AUTHORITY_UNRESOLVED:no N3 contract ${input.runtime_role_id}`);
    const query = N3_SPECIALISTS.get(input.runtime_role_id);
    const specialistId = query ? this.resolveSpecialist(query) : null;
    if (specialistId === null) blockers.push(`CAPABILITY_GAP:${input.runtime_role_id}`);
    let ceiling = 'PURE';
    if (specialistId !== null && contract !== undefined) {
      const n3Ceiling = contract.external_side_effect ? 'IRREVERSIBLE_WRITE' : 'DRAFT';
      ceiling = minClass(roleosCeiling(this.registry.getRole(specialistId).runtime_authority), n3Ceiling);
    }
    const approvalRequirements: string[] = [];
    if (contract !== undefined && contract.requires_human_approval) approvalRequirements.push('HUMAN_APPROVAL_BEFORE_CLIENT_VISIBLE');
    if (CONSEQUENTIAL.has(input.side_effect_class)) {
      approvalRequirements.push('EXACT_APPROVAL_REF');
      blockers.push(...this.consequentialBlockers(input, specialistId, contract !== undefined, contract?.external_side_effect ?? false));
    } else if (rankOf(input.side_effect_class) > rankOf(ceiling)) {
      blockers.push(`AUTHORITY_UNRESOLVED:${input.side_effect_class} exceeds ceiling ${ceiling}`);
    }
    if (input.creator_role_id && input.creator_role_id === input.runtime_role_id && CONSEQUENTIAL.has(input.side_effect_class)) {
      blockers.push('SEGREGATION_CONFLICT:creator cannot release own work');
    }
    return this.seal(input, contract, specialistId, ceiling, approvalRequirements, blockers);
  }

  private seal(
    input: BindInput, contract: ReturnType<typeof ROLE_REGISTRY.get>, specialistId: string | null, ceiling: string,
    approvalRequirements: string[], blockers: string[],
  ): SpecialistBinding {
    let status: BindingStatus = 'RESOLVED';
    if (blockers.some((b) => b.startsWith('CAPABILITY_GAP'))) status = 'CAPABILITY_GAP';
    else if (blockers.length) status = 'AUTHORITY_UNRESOLVED';
    const body = {
      specialist_role_id: specialistId,
      required_capabilities: contract ? sortStrings(contract.capabilities) : [],
      source_skill_hashes: sortStrings([...this.sourceHashes].filter(([r]) => r === specialistId).map(([, h]) => h)),
      runtime_authority_role_id: input.runtime_role_id,
      permitted_artifacts: contract ? sortStrings(contract.produces) : [],
      permitted_tools: ceiling === 'PURE' || ceiling === 'DRAFT' ? ['langgraph.workflow'] : [],
      side_effect_ceiling: ceiling,
      approval_requirements: approvalRequirements,
      segregation_constraints: ['CREATOR_NOT_SOLE_REVIEWER'],
      status,
      blockers: uniqueSorted(blockers),
    };
    return { ...body, binding_hash: semanticHash(body as unknown as HashValue) };
  }
}
