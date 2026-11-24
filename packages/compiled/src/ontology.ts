/**
 * Twin of `agency/compiled/ontology.py` (T05): the S00-S25 human-process
 * ontology, the MB0-MB8 domain overlays, the exception catalog and the
 * artifact → stage map. Process ontology only: N2 stays the lifecycle authority.
 */
import { pyRepr, type ArtifactType } from '@amc/kernel';
import { CompiledValueError } from './errors';

export const DOMAINS = [
  'BRAND', 'GRAPHIC_DESIGN', 'PRODUCT_DESIGN', 'UX_UI', 'WEB', 'SOFTWARE', 'MOBILE_APP', 'FILM', 'VIDEO', 'MOTION',
  'ANIMATION', 'VFX', 'CONTENT', 'DIGITAL_MARKETING', 'TRADITIONAL_ADVERTISING', 'MEDIA', 'ANALYTICS',
  'BUSINESS_OPERATIONS',
] as const;
export type Domain = (typeof DOMAINS)[number];

/** Python `Enum(value)`: refuses anything that is not a member value. */
export function enumMember<T extends string>(members: readonly T[], value: unknown, enumName: string): T {
  if (typeof value === 'string' && (members as readonly string[]).includes(value)) return value as T;
  const shown = typeof value === 'string' ? pyRepr(value) : String(value);
  throw new CompiledValueError(`${shown} is not a valid ${enumName}`);
}

export interface StageDefinition {
  readonly stage_id: string;
  readonly name: string;
  readonly scope: string;
  readonly roleos_phase: string;
}

const stage = (stage_id: string, name: string, scope: string, roleos_phase: string): StageDefinition => ({
  stage_id, name, scope, roleos_phase,
});

export const LIFECYCLE_STAGES: readonly StageDefinition[] = [
  stage('S00', 'SIGNAL', 'inbound, outbound, referral, partner, RFP, existing-client need', 'P0'),
  stage('S01', 'QUALIFY', 'fit, urgency, budget, authority, value, conflicts, capacity', 'P1'),
  stage('S02', 'COMMERCIAL_DISCOVERY', 'objectives, stakeholders, procurement, NDA, constraints', 'P2'),
  stage('S03', 'RESEARCH', 'company, user, customer, category, competitor, culture, analytics, technology, legal, operations', 'P4'),
  stage('S04', 'SYNTHESIS', 'evidence map, insight, problem/opportunity model', 'P4'),
  stage('S05', 'BRIEF', 'outcome, audience, proposition, requirements, constraints, metrics', 'P5'),
  stage('S06', 'STRATEGY', 'brand/product/content/channel/experience/technical/production strategy', 'P5'),
  stage('S07', 'SCOPE', 'deliverables, exclusions, dependencies, assumptions, acceptance', 'P3'),
  stage('S08', 'ESTIMATE', 'effort, staffing, vendors, contingency, schedule, margin', 'P3'),
  stage('S09', 'CONTRACT', 'proposal, SOW, MSA, IP, payment, change-control', 'P3'),
  stage('S10', 'KICKOFF', 'governance, communication, tools, files, cadence, RAID', 'P4'),
  stage('S11', 'PLAN', 'roadmap, backlog, IA, preproduction, media/production plan', 'P8'),
  stage('S12', 'EXPLORE', 'hypotheses, concepts, territories, prototypes, tests', 'P7'),
  stage('S13', 'SELECT', 'comparison, evidence, selection', 'P7'),
  stage('S14', 'PRODUCE', 'design, write, code, shoot, animate, build, configure, traffic', 'P9'),
  stage('S15', 'INTERNAL_REVIEW', 'discipline, creative, technical, business review', 'P10'),
  stage('S16', 'CLIENT_REVIEW', 'client presentation, feedback, revision, approval', 'P11'),
  stage('S17', 'QA', 'correctness, a11y, performance, security, legal, brand, platform/spec QA', 'P10'),
  stage('S18', 'RELEASE', 'print, build, deploy, master, publish, traffic, activate', 'P12'),
  stage('S19', 'VERIFY_RELEASE', 'smoke/proof/publication/tracking validation', 'P12'),
  stage('S20', 'HANDOFF', 'sources, documentation, guidelines, runbooks, training', 'P12'),
  stage('S21', 'MEASURE', 'brand/product/campaign/operational measurement', 'P13'),
  stage('S22', 'OPTIMIZE', 'experiment, iterate, maintain, support', 'P14'),
  stage('S23', 'FINANCIAL_CLOSE', 'vendor close, reconciliation, invoice, margin/utilization', 'P15'),
  stage('S24', 'ARCHIVE', 'files, rights, decisions, versions, approvals, learnings', 'P15'),
  stage('S25', 'REUSE', 'case study, portfolio, award submission, templates, reusable knowledge', 'P15'),
];
export const STAGES_BY_ID: ReadonlyMap<string, StageDefinition> = new Map(LIFECYCLE_STAGES.map((s) => [s.stage_id, s]));

function stageRange(first: number, last: number): string[] {
  const out: string[] = [];
  for (let n = first; n <= last; n += 1) out.push(`S${String(n).padStart(2, '0')}`);
  return out;
}

export interface Overlay {
  readonly overlay_id: string;
  readonly name: string;
  readonly stages: readonly string[];
  readonly domains: ReadonlySet<Domain>;
}

const ALL: readonly Domain[] = DOMAINS;
const BRAND: readonly Domain[] = ['BRAND', 'GRAPHIC_DESIGN'];
const DIGITAL: readonly Domain[] = ['PRODUCT_DESIGN', 'UX_UI', 'WEB', 'SOFTWARE', 'MOBILE_APP'];
const SOFTWARE: readonly Domain[] = ['WEB', 'SOFTWARE', 'MOBILE_APP'];
const MEDIA: readonly Domain[] = [
  'FILM', 'VIDEO', 'MOTION', 'ANIMATION', 'VFX', 'CONTENT', 'DIGITAL_MARKETING', 'TRADITIONAL_ADVERTISING', 'MEDIA',
];

const overlay = (overlay_id: string, name: string, stages: string[], ...domains: (readonly Domain[])[]): Overlay => ({
  overlay_id, name, stages, domains: new Set(domains.flat()),
});

export const MASTER_BUILDER_OVERLAYS: readonly Overlay[] = [
  overlay('MB0', 'DISCOVERY/PROBLEM_MAPPING', stageRange(2, 5), ALL),
  overlay('MB1', 'STRATEGY/POSITIONING/NAMING', stageRange(5, 9), BRAND, MEDIA, DIGITAL),
  overlay('MB2', 'VISUAL_EXPLORATION', stageRange(12, 13), BRAND, MEDIA, ['UX_UI', 'PRODUCT_DESIGN']),
  overlay('MB3', 'IDENTITY_SYSTEM', stageRange(14, 17), BRAND),
  overlay('MB4', 'ALPHA/PROTOTYPING', stageRange(11, 17), DIGITAL),
  overlay('MB5', 'BETA/SECURITY/PRE_RELEASE', stageRange(14, 19), SOFTWARE),
  overlay('MB6', 'VIDEO/CONTENT/360_CAMPAIGN', stageRange(11, 19), MEDIA),
  overlay('MB7', 'APP_DISTRIBUTION', stageRange(18, 19), ['MOBILE_APP']),
  overlay('MB8', 'LIVE_OPERATIONS', stageRange(20, 25), SOFTWARE, ['ANALYTICS']),
];

/** `select_overlays(domains, live_service=...)`: only the overlays the domains justify. */
export function selectOverlays(domains: Iterable<string>, liveService = false): string[] {
  const wanted = new Set<Domain>();
  for (const d of domains) wanted.add(enumMember(DOMAINS, d, 'Domain'));
  const selected: string[] = [];
  for (const item of MASTER_BUILDER_OVERLAYS) {
    if (![...item.domains].some((d) => wanted.has(d))) continue;
    if (item.overlay_id === 'MB8' && !liveService) continue;
    selected.push(item.overlay_id);
  }
  return selected;
}

/** Per-domain process maps (spec §10), kept as data; no domain compiler runs because one exists. */
export const DOMAIN_PROCESS_MAPS: Readonly<Record<string, readonly string[]>> = {
  BRAND: ['discovery', 'research', 'positioning', 'brand_architecture', 'naming_when_required', 'verbal_identity',
    'creative_territories', 'visual_motion_sonic_systems', 'applications', 'guidelines', 'rollout', 'governance'],
  PRODUCT_UX: ['research', 'problem_framing', 'journeys', 'information_architecture', 'flows', 'wireframes', 'prototype',
    'testing', 'ui', 'tokens_components', 'responsive_a11y', 'handoff', 'design_qa'],
  WEB: ['discovery', 'content_seo_audit', 'information_architecture', 'wireframes', 'design', 'cms_data_architecture',
    'frontend_backend', 'integrations', 'analytics', 'a11y_performance_security_qa', 'migration', 'deployment',
    'monitoring', 'maintenance'],
  SOFTWARE_APP: ['opportunity', 'product_discovery', 'prd', 'domain_model', 'architecture', 'backlog', 'ux_ui',
    'api_data_contracts', 'implementation', 'qa', 'beta_where_applicable', 'platform_compliance', 'release',
    'telemetry', 'support'],
  FILM_VIDEO: ['brief', 'treatment', 'estimate', 'script', 'boards', 'previz', 'casting_location_crew',
    'schedule_shotlist', 'production', 'ingest_backup', 'edit_review', 'vfx_motion', 'color', 'sound', 'captions',
    'rights_qc', 'masters', 'variants_distribution_archive'],
  MARKETING: ['goals', 'audience_data_audit', 'channel_strategy', 'measurement_architecture', 'campaign_content_plan',
    'production', 'trafficking', 'launch', 'optimization', 'reporting'],
  SEO: ['crawl', 'intent_keyword_research', 'architecture', 'content', 'technical', 'authority', 'measure'],
  PAID: ['goals', 'audiences_keywords', 'structure', 'creative', 'landing_experience', 'tracking', 'activation',
    'optimization'],
  SOCIAL: ['audience', 'content_pillars', 'calendar', 'production', 'approval', 'publish', 'community'],
  CRM: ['segments', 'journeys', 'copy_design', 'build', 'qa', 'trigger', 'measure'],
  CRO: ['analytics', 'hypothesis', 'experiment', 'qa', 'run', 'analysis', 'decision'],
  TRADITIONAL_ADVERTISING: ['planning', 'insight', 'brief', 'creative', 'production', 'business_legal',
    'media_plan_buy', 'traffic', 'proof', 'launch', 'post_buy'],
};

export const PROCESS_ELEMENTS = [
  'ACTOR', 'ACTION', 'TRIGGER', 'INPUT', 'TOOL', 'ARTIFACT', 'DECISION', 'RULE', 'HANDOFF', 'WAIT', 'EXCEPTION',
  'APPROVAL', 'OUTPUT',
] as const;

export const FAILURE_ROUTES = [
  'BLOCK', 'RECORD_CONFLICT+REVIEW', 'RESEARCH', 'BOUNDED_RETRY', 'RECONCILE', 'COMPENSATE', 'REJECT/REVISE',
  'LAST_APPROVED_STATE_REPAIR', 'WAIT', 'ESCALATE', 'EXACT_APPROVAL', 'CIRCUIT_BREAKER',
] as const;
export type FailureRoute = (typeof FAILURE_ROUTES)[number];

export const EXCEPTION_CATALOG: ReadonlyMap<string, FailureRoute> = new Map<string, FailureRoute>([
  ['ambiguous_goal', 'RESEARCH'],
  ['conflicting_stakeholders', 'RECORD_CONFLICT+REVIEW'],
  ['hidden_decider', 'ESCALATE'],
  ['procurement_delay', 'WAIT'],
  ['missing_agreement_or_nda', 'BLOCK'],
  ['ip_trademark_conflict', 'ESCALATE'],
  ['stale_or_contradictory_research', 'RECORD_CONFLICT+REVIEW'],
  ['scope_creep', 'RECORD_CONFLICT+REVIEW'],
  ['timeline_compression', 'ESCALATE'],
  ['specialist_or_vendor_unavailable', 'WAIT'],
  ['budget_overrun', 'ESCALATE'],
  ['dependency_delay', 'WAIT'],
  ['client_silence', 'WAIT'],
  ['contradictory_feedback', 'RECORD_CONFLICT+REVIEW'],
  ['approval_revoked', 'EXACT_APPROVAL'],
  ['superseded_artifact', 'LAST_APPROVED_STATE_REPAIR'],
  ['wrong_version_release', 'COMPENSATE'],
  ['accessibility_failure', 'REJECT/REVISE'],
  ['security_vulnerability', 'ESCALATE'],
  ['privacy_consent_failure', 'ESCALATE'],
  ['unlicensed_asset', 'BLOCK'],
  ['talent_music_location_rights_gap', 'BLOCK'],
  ['platform_store_rejection', 'LAST_APPROVED_STATE_REPAIR'],
  ['deployment_failure', 'COMPENSATE'],
  ['analytics_mismatch', 'RECORD_CONFLICT+REVIEW'],
  ['print_broadcast_production_defect', 'REJECT/REVISE'],
  ['corrupted_media_or_project_file', 'LAST_APPROVED_STATE_REPAIR'],
  ['model_hallucination', 'REJECT/REVISE'],
  ['source_prompt_injection', 'BLOCK'],
  ['tool_failure', 'BOUNDED_RETRY'],
  ['duplicate_non_idempotent_action', 'RECONCILE'],
  ['uncertain_external_result', 'RECONCILE'],
  ['irreversible_publication_error', 'ESCALATE'],
  ['missing_source', 'BLOCK'],
  ['repeated_non_progress', 'CIRCUIT_BREAKER'],
]);

/** Unknown exception kinds escalate rather than defaulting to retry. */
export function routeException(kind: string): FailureRoute {
  return EXCEPTION_CATALOG.get(kind) ?? 'ESCALATE';
}

/** Characteristic production stage per N1 artifact. Unmapped types block as ARTIFACT_STAGE_UNMODELED. */
export const ARTIFACT_STAGE: ReadonlyMap<ArtifactType, string> = new Map<ArtifactType, string>([
  ['research_brief', 'S03'],
  ['market_analysis', 'S04'],
  ['knowledge_capsule', 'S25'],
  ['positioning_statement', 'S06'],
  ['business_model_spec', 'S06'],
  ['offer_definition', 'S06'],
  ['brand_platform', 'S06'],
  ['brand_core', 'S06'],
  ['naming_candidate', 'S12'],
  ['identity_guidelines', 'S14'],
  ['brand_guidelines_doc', 'S20'],
  ['creative_concept', 'S12'],
  ['asset_prompt_set', 'S14'],
  ['media_asset', 'S14'],
  ['copy_variant', 'S14'],
  ['design_brief', 'S11'],
  ['design_system_spec', 'S14'],
  ['design_token_set', 'S14'],
  ['website_lockup_spec', 'S14'],
  ['product_spec', 'S11'],
  ['implementation_plan', 'S11'],
  ['app_build_spec', 'S14'],
  ['automation_spec', 'S14'],
  ['campaign_package', 'S14'],
  ['media_plan', 'S11'],
  ['measurement_plan', 'S11'],
  ['qa_report', 'S17'],
  ['release_record', 'S18'],
]);

/** `roleos_phase_for(artifact_type)`; Python raises KeyError for an unmapped type. */
export function roleosPhaseFor(artifactType: ArtifactType): string {
  const stageId = ARTIFACT_STAGE.get(artifactType);
  const found = stageId === undefined ? undefined : STAGES_BY_ID.get(stageId);
  if (found === undefined) throw new CompiledValueError(`no stage modelled for ${artifactType}`);
  return found.roleos_phase;
}

/** Stages where the work is a consequential external act (spec §37). */
export const CONSEQUENTIAL_STAGES: ReadonlySet<string> = new Set(['S09', 'S18', 'S23']);
