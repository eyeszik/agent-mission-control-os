/**
 * Twin of `agency/compiled/autonomy.py` (T13): the L0-L6 AutonomyClassifier.
 * Routes on task properties; a performance score never moves consequential
 * work above L5, and L6 needs an explicit governance approval ref.
 */
import { PyFloat } from '@amc/kernel';

export const AUTONOMY_LEVELS = [
  'L0_OBSERVE', 'L1_ASSIST', 'L2_ENHANCE', 'L3_SUPERCHARGE', 'L4_DRIVE', 'L5_APPROVED_EXTERNAL', 'L6_BOUNDED_AUTONOMY',
] as const;
export type AutonomyLevel = (typeof AUTONOMY_LEVELS)[number];

export const AUTONOMY_ROUTES = [
  'AUTOMATE', 'AI_EXECUTE_MACHINE_VALIDATE', 'AI_GENERATE_HUMAN_SELECT', 'HUMAN_APPROVAL_REQUIRED', 'SPECIALIST_REVIEW',
  'BLOCK_RESEARCH',
] as const;
export type AutonomyRoute = (typeof AUTONOMY_ROUTES)[number];

export const LEVELS = ['low', 'medium', 'high'] as const;
export type Level = (typeof LEVELS)[number];

/** Source terminology; "Lead" maps to L5 or L6 by consequence and governance, never universally. */
export const SOURCE_TERMINOLOGY: Readonly<Record<string, AutonomyLevel>> = {
  Assist: 'L1_ASSIST', Enhance: 'L2_ENHANCE', Supercharge: 'L3_SUPERCHARGE', Drive: 'L4_DRIVE',
};

export interface TaskSuitability {
  readonly determinism: Level;
  readonly ambiguity: Level;
  readonly consequence: Level;
  readonly reversible: boolean;
  readonly data_sensitivity: Level;
  readonly creative_judgment: Level;
  readonly factual_verifiability: Level;
  readonly tool_reliability: Level;
  readonly evaluation_history: number;
  readonly legal_public_financial_or_client_binding: boolean;
  readonly rights_privacy_security_uncertain: boolean;
  readonly evidence_sufficient: boolean;
  /** Recorded, never an authority input on its own. */
  readonly performance_score: PyFloat | null;
  readonly governance_approval_ref: string | null;
  readonly proven_narrow_scope: boolean;
}

export interface AutonomyDecision {
  readonly route: AutonomyRoute;
  readonly level: AutonomyLevel;
  readonly reasons: readonly string[];
}

const decide = (route: AutonomyRoute, level: AutonomyLevel, ...reasons: string[]): AutonomyDecision => ({ route, level, reasons });

function consequential(task: TaskSuitability): AutonomyDecision {
  const reasons = ['consequential, public, binding or irreversible'];
  // AUTONOMY_ESCROW: L6 needs evaluated history + governance approval + a proven narrow subprocess.
  if (task.governance_approval_ref && task.proven_narrow_scope && task.evaluation_history >= 1) {
    reasons.push('governance-approved bounded subprocess');
    return decide('HUMAN_APPROVAL_REQUIRED', 'L6_BOUNDED_AUTONOMY', ...reasons);
  }
  return decide('HUMAN_APPROVAL_REQUIRED', 'L5_APPROVED_EXTERNAL', ...reasons);
}

/** `classify(task)`. */
export function classify(task: TaskSuitability): AutonomyDecision {
  if (!task.evidence_sufficient) return decide('BLOCK_RESEARCH', 'L0_OBSERVE', 'insufficient evidence');
  if (task.rights_privacy_security_uncertain) {
    return decide('SPECIALIST_REVIEW', 'L1_ASSIST', 'rights/privacy/security uncertainty');
  }
  if (task.legal_public_financial_or_client_binding || !task.reversible || task.consequence === 'high') {
    return consequential(task);
  }
  if (task.determinism === 'high' && task.factual_verifiability === 'high' && task.consequence === 'low'
    && task.tool_reliability !== 'low') {
    return decide('AUTOMATE', 'L4_DRIVE', 'deterministic, verifiable, reversible, low consequence');
  }
  if (task.factual_verifiability === 'high' && task.ambiguity !== 'high') {
    return decide('AI_EXECUTE_MACHINE_VALIDATE', 'L3_SUPERCHARGE', 'structured and machine-verifiable');
  }
  if (task.creative_judgment !== 'low') {
    return decide('AI_GENERATE_HUMAN_SELECT', 'L2_ENHANCE', 'creative/judgment work; human selects');
  }
  return decide('AI_GENERATE_HUMAN_SELECT', 'L2_ENHANCE', 'default: draft for expert refinement');
}

const CREATIVE = new Set(['creative_concept', 'copy_variant', 'asset_prompt_set', 'naming_candidate', 'brand_platform',
  'identity_guidelines', 'design_brief', 'positioning_statement']);
const STRUCTURED = new Set(['design_token_set', 'design_system_spec', 'implementation_plan', 'app_build_spec',
  'automation_spec', 'measurement_plan', 'qa_report', 'website_lockup_spec']);
const RESEARCH = new Set(['research_brief', 'market_analysis', 'knowledge_capsule']);

export interface NodeSuitabilityInput {
  readonly artifactType: string | null;
  readonly sideEffectClass: string;
  readonly evidenceSufficient?: boolean;
  readonly rightsUncertain?: boolean;
}

/** `suitability_for_node`: deterministic, conservative task properties for a compiled node. */
export function suitabilityForNode(input: NodeSuitabilityInput): TaskSuitability {
  const a = input.artifactType ?? '';
  const isConsequential = input.sideEffectClass === 'REVERSIBLE_WRITE' || input.sideEffectClass === 'IRREVERSIBLE_WRITE';
  const creative = CREATIVE.has(a);
  const structured = STRUCTURED.has(a);
  const mediumConsequence = a === 'release_record' || a === 'media_plan';
  return {
    determinism: structured ? 'high' : creative ? 'low' : 'medium',
    ambiguity: creative ? 'high' : 'medium',
    consequence: isConsequential ? 'high' : mediumConsequence ? 'medium' : 'low',
    reversible: input.sideEffectClass !== 'IRREVERSIBLE_WRITE',
    data_sensitivity: a === 'measurement_plan' || a === 'media_plan' ? 'medium' : 'low',
    creative_judgment: creative ? 'high' : 'low',
    factual_verifiability: structured ? 'high' : RESEARCH.has(a) ? 'medium' : 'low',
    tool_reliability: 'medium',
    evaluation_history: 0,
    legal_public_financial_or_client_binding: isConsequential,
    rights_privacy_security_uncertain: input.rightsUncertain ?? false,
    evidence_sufficient: input.evidenceSufficient ?? true,
    performance_score: null,
    governance_approval_ref: null,
    proven_narrow_scope: false,
  };
}
