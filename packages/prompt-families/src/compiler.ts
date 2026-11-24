/**
 * Prompt-family compiler (twin of `agency/prompt_families/compiler.py`): family
 * spec -> instances -> the guidance prompt compiler.
 *
 * 1. freeze invariants; 2. select a variation combination deterministically;
 * 3. write the concept thesis before any styling; 4. compare with the
 * ConceptLedger and repair duplicates, highest-level variable first, at most
 * three passes; 5. compile every accepted instance through
 * `compilePromptPackages` so the claim, evidence, exact-text and firewall gates
 * apply unchanged; 6. record accepted and rejected signatures in a new ledger.
 *
 * There is no generation step: the terminal state is `PROMPT_PACKAGE_READY` or
 * `BLOCKED`.
 */
import type { CanonicalFloat } from '@amc/canonical';
import {
  ASSET_REQUIREMENT,
  compilePromptPackages,
  parse,
  pyFloat,
  roundTo,
  stableHash,
  type AssetRequirement,
  type CompileOptions,
  type PromptCompilerRequest,
  type PromptCompilerResult,
  type PyValue,
} from '@amc/guidance';
import { conceptSignature, duplicateReason, recordInstances, repairVariation } from './ledger';
import {
  AXIS_PRIORITY,
  EXECUTION_STATEMENT,
  FAMILY_ENGINE_VERSION,
  UNKNOWN,
  invariantLines,
  unknownVendorFields,
  type ConceptLedger,
  type ConceptLedgerEntry,
  type HookCandidate,
  type PaidMediaCreativeSpec,
  type PromptFamilyEvaluation,
  type PromptFamilyInstance,
  type PromptFamilyRequest,
  type PromptFamilySpec,
} from './models';
import { functionalRolesFor } from './roles';

export const GENERATION_FIREWALL = 'PROMPT_PACKAGE_READY';

export interface PromptFamilyResult {
  readonly engine_version: string;
  readonly family_id: string;
  readonly family_version: string;
  readonly family_hash: string;
  readonly instances: readonly PromptFamilyInstance[];
  readonly ledger: ConceptLedger;
  readonly compiler_result: PromptCompilerResult;
  readonly evaluation: PromptFamilyEvaluation;
  readonly responsible_functional_roles: readonly string[];
  readonly hooks: readonly HookCandidate[];
  readonly paid_media: readonly PaidMediaCreativeSpec[];
  readonly terminal_state: 'PROMPT_PACKAGE_READY' | 'BLOCKED';
  readonly blocked_reasons: readonly string[];
  readonly execution_statement: string;
}

export function familyHash(spec: PromptFamilySpec): string {
  return stableHash(spec as unknown as PyValue);
}

/** Instance `index` takes option `index` on every axis (cycled): a pure function of the spec. */
function initialVariation(spec: PromptFamilySpec, index: number): Map<string, string> {
  const variation = new Map<string, string>();
  for (const axis of AXIS_PRIORITY) {
    const options = spec.variation_axes.get(axis);
    if (options !== undefined) variation.set(axis, options[index % options.length] as string);
  }
  return variation;
}

function conceptThesis(spec: PromptFamilySpec, variation: ReadonlyMap<string, string>): string {
  const metaphor = variation.get('concept_metaphor');
  const campaign = spec.campaign;
  const anchor = campaign === null ? null : campaign.verbal_thesis || campaign.promise;
  const core = anchor || spec.business_objective;
  return metaphor ? `${metaphor} — ${core}` : core;
}

function planOne(spec: PromptFamilySpec, index: number, accepted: ConceptLedgerEntry['signature'][]): PromptFamilyInstance {
  const repaired = repairVariation(initialVariation(spec, index), spec.variation_axes, accepted);
  const signature = conceptSignature(repaired.variation);
  const repairs = [...repaired.log];
  let status: PromptFamilyInstance['status'] = 'ACCEPTED';
  if (duplicateReason(signature, accepted) !== null) {
    status = 'REJECTED_DUPLICATE';
    repairs.push('repair budget exhausted: concept still repeats an accepted concept');
  } else accepted.push(signature);
  return {
    family_id: spec.family_id,
    instance_id: `${spec.family_id}.${String(index + 1).padStart(2, '0')}`,
    concept_thesis: conceptThesis(spec, repaired.variation),
    variation: repaired.variation,
    signature,
    status,
    repairs,
  };
}

export function planInstances(spec: PromptFamilySpec, prior: readonly ConceptLedgerEntry[]): PromptFamilyInstance[] {
  const accepted = prior.map((entry) => entry.signature);
  return Array.from({ length: spec.instance_count }, (_, index) => planOne(spec, index, accepted));
}

interface ProductionLines {
  readonly content: string[];
  readonly quality: string[];
  readonly negative: string[];
}

function productionLines(spec: PromptFamilySpec): ProductionLines {
  const target = spec.production;
  const content: string[] = [];
  const negative: string[] = [];
  const quality = [
    `EDITABLE_MASTER: ${target.editable_master}`,
    'PRODUCTION_EXPORT: compiled separately from the editable master for the stated medium.',
  ];
  for (const field of unknownVendorFields(target)) {
    quality.push(`Vendor specification ${field}=${UNKNOWN}: confirm with the printer or vendor before production.`);
  }
  if (target.medium === 'MERCH') {
    content.push('Flat standalone artwork, independent of any product; clear silhouette and printable detail density.');
    if (target.background !== 'UNSPECIFIED') content.push(`Artwork background: ${target.background}.`);
    negative.push('No product mockup, garment, model or scene inside the artwork.');
  }
  return { content, quality, negative };
}

function seriesBinding(spec: PromptFamilySpec, instance: PromptFamilyInstance): PyValue {
  return {
    family_id: spec.family_id,
    family_version: spec.version,
    instance_id: instance.instance_id,
    campaign_ref: spec.campaign === null ? null : spec.campaign.campaign_id,
    concept_thesis: instance.concept_thesis,
    emotional_function: spec.emotional_function,
    signature_devices: [...spec.invariants.signature_devices],
    series_invariants: invariantLines(spec.invariants),
    variation: new Map(instance.variation),
    concept_signature: instance.signature.signature_hash,
  };
}

function requirementFor(spec: PromptFamilySpec, instance: PromptFamilyInstance, lines: ProductionLines): AssetRequirement {
  const content = [...spec.content_requirements, ...lines.content];
  if (spec.campaign !== null && spec.campaign.cta) content.push(`Campaign CTA: ${spec.campaign.cta}`);
  return parse(ASSET_REQUIREMENT, {
    asset_id: instance.instance_id,
    family: spec.surface_family,
    asset_type: spec.asset_type,
    objective: `${spec.business_objective} Concept: ${instance.concept_thesis}`,
    audience: spec.audience,
    channel: spec.channel,
    destination: spec.destination,
    business_reason: spec.niche,
    content_requirements: content,
    negative_constraints: [...spec.negative_constraints, ...lines.negative],
    quality_constraints: lines.quality,
    production: spec.production.export,
    exact_text: [...spec.exact_text],
    references: [...spec.references],
    series: seriesBinding(spec, instance),
  });
}

export function buildRequirements(spec: PromptFamilySpec, instances: readonly PromptFamilyInstance[]): AssetRequirement[] {
  const lines = productionLines(spec);
  return instances.filter((item) => item.status === 'ACCEPTED').map((instance) => requirementFor(spec, instance, lines));
}

export function evaluate(spec: PromptFamilySpec, instances: readonly PromptFamilyInstance[], compiled: PromptCompilerResult): PromptFamilyEvaluation {
  const lines = invariantLines(spec.invariants);
  const packages = compiled.prompt_packages;
  const hard: string[] = [];
  const held = packages.every((pkg) => {
    const series = pkg.prompt_ir.series;
    return series !== null && series.series_invariants.length === lines.length && series.series_invariants.every((line, i) => line === lines[i]);
  });
  if (!held) hard.push('brand-invariant break: an instance does not carry the frozen invariants');
  const exactOk = packages.every((pkg) => !pkg.validation.issues.some((issue) => issue.startsWith('required text not preserved')));
  if (!exactOk) hard.push('required-text corruption');
  const accepted = instances.filter((item) => item.status === 'ACCEPTED');
  const hashes = accepted.map((item) => item.signature.signature_hash);
  if (hashes.length !== new Set(hashes).size) hard.push('duplicate concept signature among accepted instances');
  return finishEvaluation(spec, instances, accepted, held, exactOk, hard);
}

function variedFraction(spec: PromptFamilySpec, accepted: readonly PromptFamilyInstance[]): number[] {
  const axes = Array.from(spec.variation_axes.keys());
  return accepted.slice(1).map((right, index) => {
    const left = accepted[index] as PromptFamilyInstance;
    return axes.filter((axis) => left.variation.get(axis) !== right.variation.get(axis)).length / axes.length;
  });
}

function finishEvaluation(
  spec: PromptFamilySpec,
  instances: readonly PromptFamilyInstance[],
  accepted: readonly PromptFamilyInstance[],
  held: boolean,
  exactOk: boolean,
  hard: string[],
): PromptFamilyEvaluation {
  const diffs = variedFraction(spec, accepted);
  const varied = diffs.length > 0 ? roundTo(diffs.reduce((total, value) => total + value, 0) / diffs.length, 6) : 0;
  const notes = ['series_consistency and novelty_budget are advisory configuration, not probabilities.'];
  if (diffs.length > 0 && varied < spec.novelty_budget.value) notes.push('Consecutive instances vary fewer axes than the novelty budget suggests.');
  return {
    invariants_held: held,
    exact_text_preserved: exactOk,
    accepted_instances: accepted.length,
    rejected_duplicates: instances.filter((item) => item.status === 'REJECTED_DUPLICATE').length,
    repairs: instances.reduce((total, item) => total + item.repairs.length, 0),
    varied_axis_fraction: pyFloat(varied),
    novelty_budget: spec.novelty_budget,
    series_consistency: spec.series_consistency,
    hard_failures: hard,
    advisory_notes: notes,
  };
}

function compilerRequest(request: PromptFamilyRequest, requirements: AssetRequirement[]): PromptCompilerRequest {
  return {
    project_name: request.project_name,
    content: request.content,
    claims: request.claims,
    evidence: request.evidence,
    brand_core: request.brand_core,
    asset_requirements: requirements,
    providers: request.providers,
    computations: request.computations,
    extract_content_claims: true,
  };
}

/** `compile_prompt_family`: ends at PROMPT_PACKAGE_READY, or BLOCKED with every reason recorded. */
export function compilePromptFamily(request: PromptFamilyRequest, options: CompileOptions): PromptFamilyResult {
  const spec = request.family;
  const instances = planInstances(spec, request.ledger.entries.filter((entry) => entry.status === 'ACCEPTED'));
  const requirements = buildRequirements(spec, instances);
  const compiled = compilePromptPackages(compilerRequest(request, requirements), options);
  const evaluation = evaluate(spec, instances, compiled);
  const blocked: string[] = [];
  if (requirements.length === 0) blocked.push('no accepted instance: every concept repeated the ledger');
  if (compiled.final_state !== 'PROMPT_PACKAGE_READY') blocked.push(`prompt compiler terminal state ${compiled.final_state}`);
  blocked.push(...evaluation.hard_failures);
  return {
    engine_version: FAMILY_ENGINE_VERSION,
    family_id: spec.family_id,
    family_version: spec.version,
    family_hash: familyHash(spec),
    instances,
    ledger: recordInstances(request.ledger, instances),
    compiler_result: compiled,
    evaluation,
    responsible_functional_roles: functionalRolesFor(spec.surface_family, spec.production.medium),
    hooks: [...request.hooks],
    paid_media: [...request.paid_media],
    terminal_state: blocked.length > 0 ? 'BLOCKED' : GENERATION_FIREWALL,
    blocked_reasons: blocked,
    execution_statement: EXECUTION_STATEMENT,
  };
}
