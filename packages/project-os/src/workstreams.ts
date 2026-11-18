/**
 * Twin of `agency/project_os/workstreams.py`: workstream templates (product,
 * creative, video, content, search, social, growth, CRM, web/app) expressed
 * over the N1 vocabulary.
 *
 * Each stage that produces a durable artifact names its N1 artifact type and
 * a subtype. Stages are not new artifact types: ownership, release reviewers
 * and N3 production authority come from `@amc/kernel`. `planWorkstream`
 * checks every stage against N3 (some role must be allowed to produce that
 * type) and against what the project already holds, so a plan shows real
 * readiness, not an aspirational checklist.
 */
import { ROLE_REGISTRY, owningDepartment } from '@amc/kernel';
import { compareCodePoints, pyRepr } from '@amc/kernel';
import { UnknownWorkstream } from './errors';
import { strOf } from './pytext';
import { own } from './vocabulary';

export interface Stage {
  readonly key: string;
  /** `null` = an activity without a durable artifact. */
  readonly artifact_type: string | null;
  readonly subtype: string | null;
  readonly depends_on: readonly string[];
}

type StageSpec = readonly [key: string, artifactType: string | null, subtype: string | null];

function chain(...specs: StageSpec[]): Stage[] {
  return specs.map(([key, artifactType, subtype], index) => ({
    key,
    artifact_type: artifactType,
    subtype,
    depends_on: index > 0 ? [(specs[index - 1] as StageSpec)[0]] : [],
  }));
}

export const WORKSTREAMS: Readonly<Record<string, readonly Stage[]>> = {
  product: chain(
    ['opportunity_discovery', 'research_brief', 'opportunity'],
    ['jtbd', 'research_brief', 'jtbd'],
    ['competitive_analysis', 'market_analysis', 'competitive'],
    ['prd', 'product_spec', 'prd'],
    ['prioritization_roadmap', 'product_spec', 'roadmap'],
    ['user_stories', 'product_spec', 'user_stories'],
    ['information_architecture', 'design_brief', 'ia'],
    ['flows_wireframes', 'design_brief', 'flows'],
    ['prototype_usability', 'qa_report', 'usability'],
    ['technical_architecture', 'app_build_spec', 'architecture'],
    ['api_data_contracts', 'app_build_spec', 'api_contract'],
    ['engineering_backlog', 'implementation_plan', 'backlog'],
    ['qa_security_performance', 'qa_report', 'release_qa'],
    ['telemetry_plan', 'measurement_plan', 'telemetry'],
    ['release', 'release_record', 'release'],
    ['post_launch_review', 'measurement_plan', 'post_launch'],
  ),
  creative: chain(
    ['creative_brief', 'creative_concept', 'brief'],
    ['reference_board', 'creative_concept', 'reference_board'],
    ['style_invariants', 'asset_prompt_set', 'style_invariants'],
    ['creative_bom', 'creative_concept', 'bom'],
    ['concepts', 'creative_concept', 'concepts'],
    ['prompt_package', 'asset_prompt_set', 'prompt_package'],
    ['masters', 'media_asset', 'master'],
    ['brand_lint_qa', 'qa_report', 'brand_lint'],
    ['channel_derivatives', 'media_asset', 'derivative'],
  ),
  video: chain(
    ['premise', 'creative_concept', 'premise'],
    ['character_world_bible', 'creative_concept', 'bible'],
    ['treatment', 'creative_concept', 'treatment'],
    ['script', 'copy_variant', 'video_script'],
    ['storyboard_shot_list', 'asset_prompt_set', 'storyboard'],
    ['shot_prompts', 'asset_prompt_set', 'shot_ir_prompts'],
    ['render_master', 'media_asset', 'video_master'],
    ['qc', 'qa_report', 'video_qc'],
    ['platform_variants', 'media_asset', 'video_variant'],
    ['thumbnails', 'media_asset', 'thumbnail'],
  ),
  content: chain(
    ['content_strategy', 'media_plan', 'content_strategy'],
    ['topic_inventory', 'market_analysis', 'topic_inventory'],
    ['editorial_briefs', 'creative_concept', 'editorial_brief'],
    ['fact_cores', 'knowledge_capsule', 'content_atom'],
    ['derivatives', 'copy_variant', 'derivative'],
    ['editorial_calendar', 'media_plan', 'editorial_calendar'],
    ['measurement', 'measurement_plan', 'content_measurement'],
  ),
  search: chain(
    ['seo_audit', 'research_brief', 'seo_audit'],
    ['search_intent_map', 'market_analysis', 'search_intent_map'],
    ['entity_map', 'market_analysis', 'entity_map'],
    ['topic_graph', 'market_analysis', 'topic_graph'],
    ['content_gap_map', 'market_analysis', 'content_gap_map'],
    ['seo_content_brief', 'research_brief', 'seo_content_brief'],
    ['ai_discoverability_brief', 'research_brief', 'ai_discoverability_brief'],
    ['technical_seo_plan', 'implementation_plan', 'technical_seo_plan'],
    ['search_measurement_plan', 'measurement_plan', 'search_measurement_plan'],
  ),
  social: chain(
    ['platform_strategy', 'media_plan', 'platform_strategy'],
    ['channel_voice', 'brand_guidelines_doc', 'channel_voice'],
    ['creative_templates', 'asset_prompt_set', 'social_templates'],
    ['social_calendar', 'media_plan', 'social_calendar'],
    ['posts', 'copy_variant', 'social_post'],
    ['community_playbook', 'copy_variant', 'community_replies'],
    ['listening_report', 'market_analysis', 'social_listening'],
    ['performance_review', 'measurement_plan', 'social_performance'],
  ),
  growth: chain(
    ['gtm', 'offer_definition', 'gtm'],
    ['funnel_architecture', 'campaign_package', 'funnel'],
    ['segmentation', 'market_analysis', 'segments'],
    ['experiment_backlog', 'measurement_plan', 'experiments'],
    ['landing_pages', 'copy_variant', 'landing_page'],
    ['cro_review', 'measurement_plan', 'cro'],
  ),
  crm: chain(
    ['journey_map', 'campaign_package', 'journey_map'],
    ['lifecycle_messages', 'copy_variant', 'lifecycle_message'],
    ['trigger_schedule', 'automation_spec', 'lifecycle_triggers'],
    ['lifecycle_measurement', 'measurement_plan', 'lifecycle'],
  ),
  web_app: chain(
    ['discovery', 'research_brief', 'web_discovery'],
    ['ia_content_model', 'design_brief', 'content_model'],
    ['ui_design_system', 'design_system_spec', 'web_ui'],
    ['design_tokens', 'design_token_set', 'web_tokens'],
    ['cms_schema', 'app_build_spec', 'cms_schema'],
    ['component_inventory', 'design_system_spec', 'component_inventory'],
    ['page_contracts', 'app_build_spec', 'page_contracts'],
    ['api_contracts', 'app_build_spec', 'api_contract'],
    ['test_plan', 'implementation_plan', 'test_plan'],
    ['a11y_performance_qa', 'qa_report', 'web_qa'],
    ['deployment_manifest', 'release_record', 'deployment_manifest'],
    ['post_deploy_smoke', 'qa_report', 'post_deploy_smoke'],
  ),
};

/** N3 roles allowed to produce this artifact type, sorted. */
export function producingRoles(artifactType: string): string[] {
  return [...ROLE_REGISTRY]
    .filter(([, role]) => [...role.produces].some((type) => type === artifactType))
    .map(([roleId]) => roleId)
    .sort(compareCodePoints);
}

export type Readiness = 'DONE' | 'IN_PROGRESS' | 'STALE' | 'READY' | 'NO_AUTHORIZED_ROLE' | 'WAITING';

export interface PlannedStage {
  readonly stage: string;
  readonly artifact_type: string | null;
  readonly subtype: string | null;
  readonly owner_department: string | null;
  readonly producing_roles: string[];
  readonly depends_on: string[];
  readonly existing_status: string | null;
  readonly readiness: Readiness;
}

const DONE_STATUSES = ['approved', 'release_eligible', 'released'];
const STALE_STATUSES = ['invalidated', 'review_required'];

function readiness(stage: Stage, status: string | null, roles: readonly string[], done: ReadonlySet<string>): Readiness {
  if (status !== null && DONE_STATUSES.includes(status)) return 'DONE';
  if (status !== null) return STALE_STATUSES.includes(status) ? 'STALE' : 'IN_PROGRESS';
  if (!stage.depends_on.every((dep) => done.has(dep))) return 'WAITING';
  return roles.length > 0 || !stage.artifact_type ? 'READY' : 'NO_AUTHORIZED_ROLE';
}

function existingIndex(existing: Iterable<Readonly<Record<string, unknown>>>): Map<string, string> {
  const have = new Map<string, string>();
  for (const row of existing) {
    have.set(JSON.stringify([strOf(row.artifact_type), strOf(row.subtype || '')]), strOf(row.status));
  }
  return have;
}

/** `existing` rows are artifact metadata with `artifact_type`, `subtype` and `status`. */
export function planWorkstream(kind: string, existing: Iterable<Readonly<Record<string, unknown>>> = []) {
  const stages = own(WORKSTREAMS, kind);
  if (stages === undefined) {
    const known = Object.keys(WORKSTREAMS).sort(compareCodePoints).join(', ');
    throw new UnknownWorkstream(`unknown workstream ${pyRepr(kind)}; known: ${known}`);
  }
  const have = existingIndex(existing);
  const done = new Set<string>();
  const plan: PlannedStage[] = stages.map((stage) => {
    const roles = stage.artifact_type ? producingRoles(stage.artifact_type) : [];
    const status = stage.artifact_type ? (have.get(JSON.stringify([stage.artifact_type, stage.subtype ?? ''])) ?? null) : null;
    const state = readiness(stage, status, roles, done);
    if (state === 'DONE') done.add(stage.key);
    return {
      stage: stage.key,
      artifact_type: stage.artifact_type,
      subtype: stage.subtype,
      owner_department: stage.artifact_type ? owningDepartment(stage.artifact_type) : null,
      producing_roles: roles,
      depends_on: [...stage.depends_on],
      existing_status: status,
      readiness: state,
    };
  });
  return { workstream: kind, stages: plan, complete: done.size === stages.length };
}
