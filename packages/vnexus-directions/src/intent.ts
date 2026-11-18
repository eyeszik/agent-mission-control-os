/**
 * Stages 1-2: intake decisions and the shared CreativeIntent (`directions/intent.py`).
 *
 * Pure. Three things stay in Python and enter the twin as typed input:
 * - the prompt compiler (`compile_genome_prompt`): `compileIntent` builds the prompt-genome document and calls the
 *   `compile` callback with it, so the caller can run the Python compiler and hand its output back;
 * - the AVIC prompt-injection / effect / third-party filters (`scan_forms` does NFKC normalisation and confusable
 *   folding): `prohibitedReason(text)` returns the reason text is prohibited, or null;
 * - the genome projection's grammar weights (`GenomeProjection.grammar_weights()`).
 */
import { CanonicalFloat } from '@amc/canonical';
import { canonicalHash, compareCodePoints, isPyDigit, pyStr, pyStrip, type PyValue } from '@amc/vnexus-brandbook';
import {
  INTENT_COMPILER_VERSION, NONE, SCHEMA, recordId, vectorNeed,
  type AssetRole, type CreativeIntent, type DirectionBrief, type FieldDecision, type SlotInstruction, type VectorInstructions,
} from './records';

/** `foundry.genome.MARKS`: the deterministic mark ids the local composer knows. */
export const FOUNDRY_MARKS: readonly string[] = ['circle_bar', 'stacked_bars', 'split_circle', 'triangle_notch', 'ring_dot', 'quarter_arcs'];
/** `bridge.PALETTE_ROLES`. */
export const PALETTE_ROLES: readonly string[] = ['ink', 'paper', 'accent', 'accent_2', 'muted'];
export const PROMPT_GENOME_SCHEMA = 'amc-vnexus-prompt-genome/v1';
/** Generic, brand-free exploration axes used only when the genome's grammars and the brief give fewer directions than requested. */
export const GENERIC_AXES: readonly string[] = ['reduction to the fewest distinct forms', 'negative-space emphasis',
  'modular construction from repeated units', 'single continuous gesture'];
export const COMPOSE_ROLES: ReadonlySet<AssetRole> = new Set<AssetRole>(['LOGO_MARK', 'ICON']);

type Weight = number | CanonicalFloat;

export interface GenomeProjectionInput {
  readonly values: { readonly [key: string]: PyValue };
  readonly genome_ref: string;
  readonly resolution_hash: string;
  /** `GenomeProjection.grammar_weights()`: grammar name -> weight in (0, 1]. */
  readonly grammar_weights: { readonly [grammar: string]: Weight };
}

export interface CompiledPrompt {
  readonly final_state: string;
  readonly package_hash?: string | null;
  readonly missing_genome_keys?: readonly string[] | null;
  readonly generation_firewall?: PyValue;
  readonly package?: { readonly generic_master_prompt?: string } | null;
}

/** `PromptGenomeDocument.model_dump(mode="json")` for the image family. */
export interface PromptGenomeDoc {
  readonly schema_version: string;
  readonly intent: string;
  readonly family: 'IMAGE';
  readonly asset_type: string;
  readonly audience: string;
  readonly channel: string;
  readonly destination: string;
  readonly constraints: readonly string[];
  readonly quality_rules: readonly string[];
  readonly exact_text: readonly string[];
  readonly creative_dna: readonly string[];
  readonly references: readonly never[];
  readonly capabilities: readonly string[];
  readonly output: { readonly width: number; readonly height: number };
  readonly template_of: string | null;
  readonly source_text: string | null;
}

export interface IntentArgs {
  readonly tenant_id: string;
  readonly project_id: string;
  readonly brand_id: string;
  readonly scope: string;
  readonly scope_ref: string;
  readonly projection: GenomeProjectionInput;
  readonly brand_constraints: ReadonlyArray<{ readonly key: string; readonly kind: string }>;
  readonly brief: DirectionBrief;
}

export interface IntentHooks {
  readonly prohibitedReason: (text: string) => string | null;
  readonly compile: (promptId: string, doc: PromptGenomeDoc) => CompiledPrompt;
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
}

function decision(field: string, value: unknown, consequence: string): FieldDecision {
  if (isEmpty(value)) return { field, status: 'UNKNOWN', consequence };
  if (value === NONE) return { field, status: 'NONE', consequence: '' };
  return { field, status: 'VALUE', consequence: '' };
}

function listOf(value: DirectionBrief['exact_text']): readonly string[] {
  return Array.isArray(value) ? (value as readonly string[]) : [];
}

function briefTexts(brief: DirectionBrief): string[] {
  const singles = [brief.audience, brief.category, brief.rights_constraints, brief.privacy_constraints]
    .filter((t): t is string => typeof t === 'string' && t !== NONE);
  return [brief.objective, ...singles, ...brief.directions, ...brief.emotional_targets, ...listOf(brief.exact_text), ...listOf(brief.applications)];
}

/** Intake decisions (which fields are VALUE, NONE or UNKNOWN) and the sorted reasons any brief text is prohibited. */
export function intake(brief: DirectionBrief, prohibitedReason: (text: string) => string | null): [FieldDecision[], string[]] {
  const decisions = [
    decision('audience', brief.audience, 'review cannot judge audience relevance (lens 01) without it'),
    decision('category', brief.category, 'category overlap (lens 10) stays UNKNOWN'),
    decision('exact_text', brief.exact_text, 'the exact identity text gate stays UNKNOWN; decide the text or @none'),
    decision('rights_constraints', brief.rights_constraints, "rights evidence must come from each candidate's import record"),
    decision('privacy_constraints', brief.privacy_constraints, 'privacy review relies on the default [PII] rules only'),
    decision('applications', brief.applications, 'application fitness (lens 12) cannot be assessed'),
  ];
  const reasons = new Set<string>();
  for (const text of briefTexts(brief)) {
    const why = prohibitedReason(text);
    if (why) reasons.add(why);
  }
  return [decisions, [...reasons].sort(compareCodePoints)];
}

function weight(w: Weight): number {
  return w instanceof CanonicalFloat ? w.value : w;
}

/** The bounded, conceptually distinct direction slots: the brief's own, then approved grammars, then generic axes. */
export function directions(brief: DirectionBrief, grammarWeights: GenomeProjectionInput['grammar_weights']): string[] {
  const out = [...new Set(brief.directions.map((d) => pyStrip(d)).filter((d) => d.length > 0))];
  const grammars = Object.entries(grammarWeights).sort(([an, aw], [bn, bw]) => (weight(bw) - weight(aw)) || compareCodePoints(an, bn));
  for (const [grammar] of grammars) {
    if (out.length >= brief.candidate_count) break;
    out.push(`led by the approved ${grammar.replace(/_/g, ' ')} grammar`);
  }
  for (const axis of GENERIC_AXES) {
    if (out.length >= brief.candidate_count) break;
    if (!out.includes(axis)) out.push(axis);
  }
  return out.slice(0, brief.candidate_count);
}

/** Deterministic rotation by the brief hash; the approved mark (if any) is not re-proposed as a "new" direction. */
export function marksFor(briefHash: string, count: number, approvedMark: PyValue | undefined): string[] {
  const filtered = FOUNDRY_MARKS.filter((m) => m !== approvedMark);
  const pool = filtered.length > 0 ? filtered : [...FOUNDRY_MARKS];
  const start = parseInt(briefHash.slice(0, 8), 16) % pool.length;
  return Array.from({ length: count }, (_, i) => pool[(start + i) % pool.length] as string);
}

const NEGATIVES: readonly string[] = [
  'no lettering, letters, words or numerals in the image: identity text is set later from the approved type',
  'no third-party logos, trademarks or recognisable real people', 'no photographs of identifiable individuals',
  'no embedded signatures or watermarks',
];

function negativesFor(role: AssetRole): string[] {
  return role === 'LOGO_MARK' || role === 'ICON' ? [...NEGATIVES, 'flat shapes only: no gradients, textures or photographic detail'] : [...NEGATIVES];
}

export function promptDocument(brief: DirectionBrief, negatives: readonly string[]): PromptGenomeDoc {
  return { schema_version: PROMPT_GENOME_SCHEMA, intent: brief.objective, family: 'IMAGE', asset_type: brief.asset_role.toLowerCase(),
    audience: typeof brief.audience === 'string' && brief.audience !== NONE ? brief.audience : '', channel: 'web', destination: 'unspecified',
    constraints: negatives, quality_rules: [], exact_text: [], creative_dna: [], references: [], capabilities: [],
    output: { width: brief.width, height: brief.height }, template_of: null, source_text: null };
}

/** `verbal.voice.tone` as up to six emotional targets when the brief names none. */
export function tone(values: GenomeProjectionInput['values']): string[] {
  const t = values['verbal.voice.tone'];
  if (Array.isArray(t)) return t.map((x: PyValue) => pyStr(x)).slice(0, 6);
  if (t === undefined || t === null || t === '' || t === 0 || t === false || (t instanceof CanonicalFloat && t.value === 0)
    || (typeof t === 'object' && !Array.isArray(t) && !(t instanceof CanonicalFloat) && Object.keys(t).length === 0)) return [];
  return pyStr(t).split(',').map((x) => pyStrip(x)).filter((x) => x.length > 0).slice(0, 6);
}

function exactTextRule(brief: DirectionBrief, exact: readonly string[]): string {
  if (exact.length > 0) return 'set each string verbatim from the approved display face as editable <text>; never trace generated lettering';
  return brief.exact_text === NONE ? 'text decided NONE' : 'exact text UNKNOWN: decide it before release';
}

function paletteOf(values: GenomeProjectionInput['values']): { [role: string]: string } {
  const out: { [role: string]: string } = {};
  for (const r of PALETTE_ROLES) {
    const v = values[`visual.color.${r}`];
    if (typeof v === 'string') out[r] = v;
  }
  return out;
}

function vectorInstructions(args: IntentArgs, exact: readonly string[]): VectorInstructions {
  const { brief, projection: p } = args;
  return {
    need: vectorNeed(brief.asset_role), palette_roles: paletteOf(p.values),
    fills: 'approved palette role colours only; no gradients unless the genome approves them', exact_text: exact,
    exact_text_rule: exactTextRule(brief, exact),
    approved_faces: { display: p.values['visual.typography.display'] ?? null, body: p.values['visual.typography.body'] ?? null },
    geometry: ['native shapes or paths only; an embedded raster is never vector', 'explicit viewBox; no clipping of the mark',
      'closed counters stay open at the smallest application size', 'no scripts, external references or foreignObject'],
    minimum_sizes: listOf(brief.applications).filter((a) => Array.from(a).some(isPyDigit)),
    protected: [...new Set(args.brand_constraints.filter((c) => c.kind === 'IMMUTABLE').map((c) => c.key))].sort(compareCodePoints),
  };
}

function slotsFor(brief: DirectionBrief, master: string, dirs: readonly string[], marks: readonly string[], negatives: readonly string[]): SlotInstruction[] {
  const negative = negatives.join('; ');
  return dirs.map((direction, i): SlotInstruction => {
    const prompt = `${master}\n\nDirection ${i + 1} of ${dirs.length}: ${direction}. Keep this direction conceptually distinct from the others.`;
    const parameters = { width: brief.width, height: brief.height, seed: null, count: 1 };
    return { slot: i + 1, direction, prompt, negative_prompt: negative, parameters,
      prompt_hash: canonicalHash({ prompt, negative, parameters }), compose_mark: marks.length > 0 ? (marks[i] as string) : null };
  });
}

function sharedOf(args: IntentArgs, dirs: readonly string[]): CreativeIntent['shared'] {
  const { brief, projection: p } = args;
  return { objective: brief.objective, audience: brief.audience, category: brief.category, applications: brief.applications,
    emotional_targets: brief.emotional_targets.length > 0 ? brief.emotional_targets : tone(p.values),
    emotional_targets_source: brief.emotional_targets.length > 0 ? 'brief' : 'genome verbal.voice.tone',
    imagery_style: p.values['visual.imagery.style'] ?? null, candidate_count: dirs.length, budget_minor: brief.budget_minor,
    references: brief.references as unknown as PyValue };
}

function blockersFor(prohibited: readonly string[], compiled: CompiledPrompt): string[] {
  const blockers = [...prohibited];
  if (compiled.final_state !== 'PROMPT_PACKAGE_READY') {
    blockers.push(`PROMPT_COMPILER_${compiled.final_state}: ` + (compiled.missing_genome_keys ?? []).join(', '));
  }
  return blockers;
}

/** The shared CreativeIntent: compiled once per (genome resolution, brief, compiler version). */
export function compileIntent(args: IntentArgs, hooks: IntentHooks): CreativeIntent {
  const { brief, projection: p } = args;
  const [decisions, prohibited] = intake(brief, hooks.prohibitedReason);
  const briefHash = canonicalHash(brief);
  const dependencyHash = canonicalHash({ resolution: p.resolution_hash, genome_ref: p.genome_ref, brief: briefHash, compiler: INTENT_COMPILER_VERSION });
  const exact = [...listOf(brief.exact_text)];
  const negatives = negativesFor(brief.asset_role);
  const compiled = hooks.compile(`direction-${brief.asset_role.toLowerCase()}`, promptDocument(brief, negatives));
  const blockers = blockersFor(prohibited, compiled);
  const master = compiled.package?.generic_master_prompt ?? '';
  const dirs = directions(brief, p.grammar_weights);
  const marks = COMPOSE_ROLES.has(brief.asset_role) ? marksFor(briefHash, dirs.length, p.values['visual.logo.mark']) : [];
  const slots = blockers.length > 0 ? [] : slotsFor(brief, master, dirs, marks, negatives);
  return {
    schema_version: SCHEMA, compiler_version: INTENT_COMPILER_VERSION,
    intent_id: recordId('vdi', { tenant: args.tenant_id, project: args.project_id, brand: args.brand_id, scope: args.scope,
      scope_ref: args.scope_ref, dep: dependencyHash }),
    tenant_id: args.tenant_id, project_id: args.project_id, brand_id: args.brand_id, scope: args.scope, scope_ref: args.scope_ref,
    genome_ref: p.genome_ref, resolution_hash: p.resolution_hash, asset_role: brief.asset_role, vector_need: vectorNeed(brief.asset_role), brief,
    brief_hash: briefHash, field_decisions: decisions, prohibited, status: blockers.length > 0 ? 'BLOCKED_INPUT' : 'READY', blockers,
    shared: sharedOf(args, dirs),
    prompt_compiler: { final_state: compiled.final_state, package_hash: compiled.package_hash ?? null,
      missing_genome_keys: [...(compiled.missing_genome_keys ?? [])], generation_firewall: compiled.generation_firewall ?? null },
    image_instructions: slots, vector_instructions: vectorInstructions(args, exact), dependency_hash: dependencyHash,
  };
}

export const HANDOFF_RETURN = {
  formats: ['image/png', 'image/svg+xml'], max_bytes: 12_000_000,
  record: ['provider', 'model', 'model_version', 'seed', 'parameters', 'generated_at', 'job_ref', 'receipt_ref', 'cost_minor', 'currency',
    'rights_basis', 'reference_ids'],
  provenance: 'USER_REPORTED: the importer\'s statement; this server verifies only the bytes it stores',
};

export const HANDOFF_RULES: readonly string[] = ['use only an account and terms you are authorized to use; this package grants no entitlement',
  'do not include identity text in generated images', 'do not upload private or [PII] material to a provider'];

/** The manual route: everything an operator needs to generate elsewhere under their own authorization. Calls no provider. */
export function handoffPackage(intent: CreativeIntent): { [key: string]: PyValue } {
  return { intent_id: intent.intent_id, genome_ref: intent.genome_ref, asset_role: intent.asset_role, status: intent.status,
    blockers: [...intent.blockers],
    slots: intent.image_instructions.map((s) => ({ slot: s.slot, direction: s.direction, prompt: s.prompt, negative_prompt: s.negative_prompt,
      parameters: s.parameters, prompt_hash: s.prompt_hash })),
    vector_instructions: intent.vector_instructions as unknown as PyValue, return: HANDOFF_RETURN as unknown as PyValue, rules: [...HANDOFF_RULES] };
}

