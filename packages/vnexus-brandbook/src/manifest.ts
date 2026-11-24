/**
 * The brand book page manifest (`brandbook/manifest.py`): a versioned, brandless 24-page template. A page's
 * `required_paths`/`optional_paths` are its dependency set; DECIDE pages also depend on their applicability key.
 */
import { compareCodePoints } from './python';
import { canonicalHash } from './hash';

export const TEMPLATE_ID = 'amc-brandbook/default';
export const TEMPLATE_VERSION = '1.0.0';
export const APPLICABILITY_PREFIX = 'production.brandbook.applicability.';

export const MODES = ['SYSTEM_SPEC_ONLY', 'PROMPTS_ONLY', 'PREVIEW', 'PRODUCTION'] as const;
export type Mode = (typeof MODES)[number];
export type AssetRef = 'mark' | 'wordmark' | 'lockup';
export type Layout = 'cover' | 'list' | 'grid' | 'specimen' | 'matrix' | 'table';
export type GapBehavior = 'BLOCK' | 'LABEL' | 'DECIDE';

/** `PageSpec.model_dump(mode="json")`: every field present, in declaration order. */
export interface PageSpec {
  readonly id: string;
  readonly order: number;
  readonly title: string;
  readonly objective: string;
  readonly required_paths: readonly string[];
  readonly optional_paths: readonly string[];
  readonly exact_copy: readonly string[];
  readonly asset_refs: readonly AssetRef[];
  readonly evidence_refs: boolean;
  readonly layout: Layout;
  readonly prohibitions: readonly string[];
  readonly checks: readonly string[];
  readonly output_modes: readonly Mode[];
  readonly gap_behavior: GapBehavior;
  readonly reads_all_pages: boolean;
}

export interface PageManifest {
  readonly template_id: string;
  readonly template_version: string;
  readonly pages: readonly PageSpec[];
}

export class ManifestError extends Error {
  override name = 'ValueError';
}

/** `StopIteration` from `PageManifest.page()` for an id that is not in the manifest (Python's message is empty). */
export class PageNotFound extends Error {
  override name = 'StopIteration';
  constructor() {
    super('');
  }
}

type PageInput = Pick<PageSpec, 'id' | 'order' | 'title' | 'objective'> & Partial<PageSpec>;

/** A `PageSpec` with Python's defaults filled in. */
export function pageSpec(input: PageInput): PageSpec {
  return {
    id: input.id, order: input.order, title: input.title, objective: input.objective,
    required_paths: input.required_paths ?? [], optional_paths: input.optional_paths ?? [], exact_copy: input.exact_copy ?? [],
    asset_refs: input.asset_refs ?? [], evidence_refs: input.evidence_refs ?? false, layout: input.layout ?? 'list',
    prohibitions: input.prohibitions ?? [], checks: input.checks ?? ['no_overflow', 'exact_copy', 'no_unresolved_tokens'],
    output_modes: input.output_modes ?? ['PROMPTS_ONLY', 'PREVIEW', 'PRODUCTION'], gap_behavior: input.gap_behavior ?? 'LABEL',
    reads_all_pages: input.reads_all_pages ?? false,
  };
}

export function applicabilityKey(spec: PageSpec): string {
  return APPLICABILITY_PREFIX + spec.id;
}

/** `sorted(set(...))`: Python sorts str by code point. */
export function sortedUnique(values: Iterable<string>): string[] {
  return [...new Set(values)].sort(compareCodePoints);
}

export function dependencyPaths(spec: PageSpec): string[] {
  const extra = spec.gap_behavior === 'DECIDE' ? [applicabilityKey(spec)] : [];
  return sortedUnique([...spec.required_paths, ...spec.optional_paths, ...extra]);
}

/** The `PageManifest` model validator: unique ids and orders, listed in order. */
export function pageManifest(templateId: string, templateVersion: string, pages: readonly PageSpec[]): PageManifest {
  const ids = pages.map((p) => p.id);
  const orders = pages.map((p) => p.order);
  if (new Set(ids).size !== ids.length || new Set(orders).size !== orders.length) {
    throw new ManifestError('page ids and orders must be unique');
  }
  if (orders.some((o, i) => i > 0 && o < (orders[i - 1] ?? o))) throw new ManifestError('pages must be listed in order');
  return { template_id: templateId, template_version: templateVersion, pages };
}

export function manifestHash(manifest: PageManifest): string {
  return canonicalHash(manifest);
}

export function manifestPage(manifest: PageManifest, pageId: string): PageSpec {
  const found = manifest.pages.find((p) => p.id === pageId);
  if (found === undefined) throw new PageNotFound();
  return found;
}

/** Keys every page's styling reads (palette and type set the whole book). */
export const STYLE_PATHS: readonly string[] = [
  'visual.color.ink', 'visual.color.paper', 'visual.color.accent', 'visual.color.accent_2', 'visual.color.muted',
  'visual.typography.display', 'visual.typography.body', 'production.output.page_format',
];

const LOGO = ['visual.logo.mark', 'visual.logo.master_artifact', 'visual.logo.wordmark'];
const P = pageSpec;

export const DEFAULT_PAGES: readonly PageSpec[] = [
  P({ id: 'p01', order: 1, title: 'Cover', objective: 'Exact brand identity, document title, template version and approval status.',
    optional_paths: LOGO, exact_copy: ['Brand guidelines'], asset_refs: ['mark', 'wordmark'], layout: 'cover',
    prohibitions: ['no invented slogan', 'no invented date', 'no endorsement'], gap_behavior: 'LABEL' }),
  P({ id: 'p02', order: 2, title: 'Contents and status', objective: 'Actual navigation from this manifest, scope, evidence and approval legend.',
    exact_copy: ['Contents'], layout: 'table', reads_all_pages: true }),
  P({ id: 'p03', order: 3, title: 'Premise', objective: 'Offering, audience, positioning, differentiation and values behind the design.',
    required_paths: ['strategy.positioning.statement', 'strategy.audience.primary'],
    optional_paths: ['strategy.positioning.promise', 'strategy.audience.needs', 'strategy.differentiation.statement',
      'strategy.values.list', 'strategy.competitive_territory.summary'], gap_behavior: 'BLOCK' }),
  P({ id: 'p04', order: 4, title: 'Voice', objective: 'Operational voice traits, channel tone, vocabulary and claims, with write/avoid samples.',
    required_paths: ['verbal.voice.tone'],
    optional_paths: ['verbal.voice.register', 'verbal.tone.channels', 'verbal.vocabulary.prefer', 'verbal.vocabulary.avoid',
      'verbal.content_rules.claims', 'verbal.messaging.write', 'verbal.messaging.avoid'],
    prohibitions: ['no claim that is not in verbal.content_rules.claims'], gap_behavior: 'BLOCK' }),
  P({ id: 'p05', order: 5, title: 'References and evidence', objective: 'Per-source observations, inferences, unknowns, reuse and privacy limits.',
    evidence_refs: true, prohibitions: ['never reconstruct [PII]', 'source compositions stay evidence'], layout: 'table' }),
  P({ id: 'p06', order: 6, title: 'Identity overview', objective: 'Canonical identity, palette and type on one calibration page.',
    optional_paths: LOGO, asset_refs: ['mark', 'wordmark'], layout: 'grid' }),
  P({ id: 'p07', order: 7, title: 'Primary logo', objective: 'The approved master, its exact text, contexts and placement.',
    required_paths: ['visual.logo.mark'], optional_paths: ['visual.logo.master_artifact', 'visual.logo.wordmark', 'visual.logo.placement'],
    asset_refs: ['mark'], layout: 'specimen', gap_behavior: 'BLOCK' }),
  P({ id: 'p08', order: 8, title: 'Construction', objective: 'Real axes, boundaries and negative space of the master.',
    required_paths: ['visual.logo.mark'], optional_paths: ['visual.logo.master_artifact', 'visual.logo.construction'],
    asset_refs: ['mark'], layout: 'specimen', gap_behavior: 'BLOCK' }),
  P({ id: 'p09', order: 9, title: 'Wordmark', objective: 'Spelling, case, baseline and spacing of the wordmark.',
    optional_paths: ['visual.logo.wordmark', 'visual.logo.wordmark_case', 'visual.logo.custom_lettering'],
    asset_refs: ['wordmark'], layout: 'specimen' }),
  P({ id: 'p10', order: 10, title: 'Lockups', objective: 'Applicable primary, horizontal, stacked, wordmark-only and symbol-only lockups.',
    required_paths: ['visual.logo.mark'], optional_paths: ['visual.logo.master_artifact', 'visual.logo.wordmark', 'visual.logo.lockups'],
    asset_refs: ['mark', 'wordmark', 'lockup'], layout: 'grid', gap_behavior: 'BLOCK' }),
  P({ id: 'p11', order: 11, title: 'Clear space', objective: 'Approved clear space with correct and crowded examples.',
    required_paths: ['visual.logo.mark', 'visual.logo.clear_space'], optional_paths: ['visual.logo.master_artifact'],
    asset_refs: ['mark'], layout: 'specimen', gap_behavior: 'LABEL' }),
  P({ id: 'p12', order: 12, title: 'Scale', objective: 'Approved minimum size and the mark at 16, 32, 64 and 128 px.',
    required_paths: ['visual.logo.mark', 'visual.logo.min_size'], optional_paths: ['visual.logo.master_artifact', 'visual.logo.small_size_variant'],
    asset_refs: ['mark'], layout: 'specimen', gap_behavior: 'LABEL' }),
  P({ id: 'p13', order: 13, title: 'One colour and reverse', objective: 'Canonical silhouette in one colour and reversed, with pairings.',
    required_paths: ['visual.logo.mark'], optional_paths: ['visual.logo.master_artifact'], asset_refs: ['mark'], layout: 'grid',
    gap_behavior: 'BLOCK' }),
  P({ id: 'p14', order: 14, title: 'Misuse', objective: 'Labelled misuse specimens, isolated from the masters.',
    required_paths: ['visual.logo.mark'], optional_paths: ['visual.logo.master_artifact'], asset_refs: ['mark'], layout: 'grid',
    prohibitions: ['misuse specimens are never masters'], gap_behavior: 'BLOCK' }),
  P({ id: 'p15', order: 15, title: 'Colour', objective: 'Colour roles, approved values, allowed pairings and measured contrast.',
    required_paths: ['visual.color.ink', 'visual.color.paper'], optional_paths: ['visual.color.names', 'visual.color.usage'],
    layout: 'matrix', gap_behavior: 'BLOCK' }),
  P({ id: 'p16', order: 16, title: 'Typography', objective: 'Type roles, specimens, hierarchy, licence and fallback status.',
    required_paths: ['visual.typography.display'],
    optional_paths: ['visual.typography.license', 'visual.typography.fallback', 'visual.typography.languages', 'visual.typography.scale'],
    layout: 'specimen', gap_behavior: 'BLOCK' }),
  P({ id: 'p17', order: 17, title: 'Layout', objective: 'Grids, margins, rhythm and responsive rules.',
    optional_paths: ['visual.grid.columns', 'visual.grid.margin', 'visual.grid.rhythm', 'visual.grid.responsive'], gap_behavior: 'DECIDE' }),
  P({ id: 'p18', order: 18, title: 'Graphics', objective: 'Original primitives, icons, patterns and density.',
    optional_paths: ['visual.shape_grammar.summary', 'visual.shape_grammar.density', 'visual.shape_grammar.icons'],
    prohibitions: ['no copied compositions', 'no competing marks'], gap_behavior: 'DECIDE' }),
  P({ id: 'p19', order: 19, title: 'Imagery', objective: 'Subjects, framing, light, treatment, rights and privacy.',
    optional_paths: ['visual.imagery.style', 'visual.imagery.subjects', 'visual.imagery.rights', 'visual.imagery.treatment'],
    prohibitions: ['appearance is not a manufacturing specification'], gap_behavior: 'DECIDE' }),
  P({ id: 'p20', order: 20, title: 'Editorial and print', objective: 'Relevant cover, spread, imprint and collateral rules.',
    optional_paths: ['production.output.print', 'production.media.print_formats'],
    prohibitions: ['no fictional client, contact or testimonial'], gap_behavior: 'DECIDE' }),
  P({ id: 'p21', order: 21, title: 'Digital', objective: 'Header, avatar, social and interface crops and responsiveness.',
    optional_paths: ['production.platform.channels', 'production.platform.avatar', 'experience.responsive.rules'],
    prohibitions: ['a static preview is not a working interface'], gap_behavior: 'DECIDE' }),
  P({ id: 'p22', order: 22, title: 'Motion', objective: 'Storyboard, transitions, continuity and the reduced-motion rule.',
    optional_paths: ['visual.motion.pace', 'visual.motion.emphasis', 'visual.motion.reduced_motion'],
    prohibitions: ['no claim of a rendered video'], gap_behavior: 'DECIDE' }),
  P({ id: 'p23', order: 23, title: 'Handoff', objective: 'Actual files, formats, licences, tokens and version references.',
    optional_paths: ['production.licensing.fonts', 'production.delivery.formats'], layout: 'table', reads_all_pages: true }),
  P({ id: 'p24', order: 24, title: 'Release', objective: 'Actual checks, unresolved decisions, approval and version records.',
    layout: 'table', reads_all_pages: true }),
];

export const DEFAULT_MANIFEST: PageManifest = pageManifest(TEMPLATE_ID, TEMPLATE_VERSION, DEFAULT_PAGES);
