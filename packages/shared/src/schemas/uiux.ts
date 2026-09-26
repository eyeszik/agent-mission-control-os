import { z } from 'zod';

// Zod twin of services/langgraph/agency/ui_ux/models.py (UIUXDesignIR).
// Every object is .strict() to mirror Pydantic `extra="forbid"`. Parity is
// proven by packages/shared/tests/fixtures/uiux-design-ir.json, which the
// backend test suite regenerates from the real compiler and this package's
// tests parse with these schemas.

export const UIUX_SCHEMA_VERSION = 'amc-uiux-ir/v1' as const;
export const UIUX_SPEC_READY = 'UIUX_SPEC_READY' as const;

export const SurfaceModeSchema = z.enum(['LANDING_PAGE', 'APPLICATION', 'DASHBOARD', 'AI_INTERFACE', 'FORM_FLOW']);
export const UIPlatformSchema = z.enum(['WEB_RESPONSIVE', 'MOBILE_WEB', 'DESKTOP_WEB']);
export const UIPrioritySchema = z.enum(['P0', 'P1', 'P2', 'P3']);
export const UIStateSchema = z.enum([
  'DEFAULT', 'HOVER', 'FOCUS_VISIBLE', 'PRESSED', 'SELECTED', 'CHECKED', 'CURRENT', 'EXPANDED',
  'DISABLED', 'READ_ONLY', 'LOADING', 'STREAMING', 'SKELETON', 'EMPTY', 'VALID', 'INVALID',
  'WARNING', 'ERROR', 'SUCCESS', 'PENDING', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
  'DEGRADED', 'STALE', 'DRAG', 'DROP_TARGET', 'OFFLINE', 'UNAVAILABLE',
]);
export const ResponsiveTransformSchema = z.enum([
  'WRAP', 'STACK', 'REORDER', 'COLLAPSE', 'SCROLL', 'MENU', 'DRAWER', 'FULL_WIDTH', 'PRIORITY_REDUCTION',
]);
export const A11yVerificationSchema = z.enum([
  'VERIFIED_STATIC', 'VERIFIED_BROWSER', 'REQUIRES_ASSISTIVE_TECH', 'REQUIRES_HUMAN_EVALUATION',
]);
export const MetricTruthSchema = z.enum(['MEASURED', 'DERIVED', 'ESTIMATED', 'NOT_MEASURED', 'UNAVAILABLE']);
export const UISourceKindSchema = z.enum(['REQUEST', 'BRAND_CORE', 'DESIGN_BRIEF', 'STRATEGY', 'COMPILER_DEFAULT']);
export const PrincipleFamilySchema = z.enum([
  'USABILITY', 'HEURISTICS', 'GESTALT', 'COGNITIVE', 'BEHAVIORAL', 'VISUAL', 'INTERACTION', 'PLATFORM', 'SYSTEM',
]);
export const ImplementationStatusSchema = z.enum(['VERIFIED_EXISTING', 'EXTEND', 'PROPOSED']);
export const EvaluationEngineSchema = z.enum([
  'ANTI_GENERIC', 'SALIENCE_BUDGET', 'INTERACTION_DEBT', 'STATE_ENTROPY', 'COUNTERFACTUAL_UX',
  'LAYOUT_GRAMMAR', 'TRACEABILITY', 'CONTRAST',
]);
export const SeveritySchema = z.enum(['BLOCKING', 'WARNING', 'INFO']);
export const CheckStatusSchema = z.enum(['PASS', 'FAIL', 'NOT_RUN']);
export const WCAGRequirementSchema = z.enum(['AAA_NORMAL', 'AAA_LARGE', 'AA_NORMAL', 'AA_LARGE', 'NON_TEXT']);
// No generated/deployed terminal exists: the compiler stops at a spec.
export const UIUXTerminalSchema = z.enum(['UIUX_SPEC_READY', 'REQUIRES_APPROVAL', 'BLOCKED']);

const InputModeSchema = z.enum(['POINTER', 'TOUCH', 'KEYBOARD', 'SCREEN_READER']);
const nonEmpty = z.string().min(1);

export const UISourceRefSchema = z.object({ kind: UISourceKindSchema, ref: nonEmpty, detail: z.string() }).strict();
export const UIAssumptionSchema = z.object({ id: z.string(), statement: z.string(), reason: z.string(), impact: z.string() }).strict();
export const UIUnknownSchema = z.object({ id: z.string(), question: z.string(), blocks: z.boolean() }).strict();

export const ProductModelSchema = z.object({
  purpose: z.string(),
  platform: UIPlatformSchema,
  primary_user: z.string(),
  primary_task: z.string(),
  business_goal: z.string(),
}).strict();

export const IAItemSchema = z.object({
  id: z.string(),
  label: z.string(),
  purpose: z.string(),
  priority: UIPrioritySchema,
  children: z.array(z.string()),
}).strict();

export const InformationArchitectureSchema = z.object({
  primary_nav: z.array(IAItemSchema).min(1),
  hierarchy_depth: z.number().int().min(1).max(4),
  labeling_rule: z.string(),
}).strict();

export const FlowStepSchema = z.object({
  id: z.string(),
  screen_ref: z.string(),
  user_action: z.string(),
  system_response: z.string(),
  failure_path: z.string(),
}).strict();

export const FlowSchema = z.object({
  id: z.string(),
  name: z.string(),
  goal: z.string(),
  steps: z.array(FlowStepSchema).min(1),
  success_signal: z.string(),
}).strict();

export const TerritorySchema = z.object({
  id: z.string(),
  name: z.string(),
  thesis: z.string(),
  score: z.number().min(0).max(1),
  fit_rationale: z.string(),
  selected: z.boolean(),
  rejection_reason: z.string().nullable(),
}).strict();

export const PrincipleApplicationSchema = z.object({
  id: z.string(),
  name: z.string(),
  family: PrincipleFamilySchema,
  user_problem: z.string(),
  relevance: z.string(),
  application: z.string(),
  tradeoff: z.string(),
  a11y_effect: z.string(),
  responsive_effect: z.string(),
  implementation_effect: z.string(),
  changes: z.array(z.string()).min(1),
}).strict();

export const DesignGenomeSchema = z.object({
  hierarchy: z.string(),
  density: z.enum(['LOW', 'MEDIUM', 'HIGH']),
  geometry: z.string(),
  typography: z.string(),
  color: z.string(),
  material: z.string(),
  motion: z.string(),
  interaction: z.string(),
  signature: z.string(),
  genome_hash: z.string(),
}).strict();

export const ContrastCheckSchema = z.object({
  foreground: z.string(),
  background: z.string(),
  foreground_value: z.string(),
  background_value: z.string(),
  wcag_requirement: WCAGRequirementSchema,
  wcag_ratio: z.number(),
  passes: z.boolean(),
  verification: A11yVerificationSchema,
  // Advisory only; never a WCAG conformance value.
  apca_lc_advisory: z.number(),
  apca_note: z.string(),
}).strict();

export const TokenSystemSpecSchema = z.object({
  format: z.literal('DTCG 2025.10'),
  tiers: z.array(z.string()),
  css_prefix: z.string(),
  document: z.record(z.unknown()),
  source_hash: z.string(),
  token_count: z.number().int().min(1),
  css: z.string(),
  contrast: z.array(ContrastCheckSchema),
  palette_resolution: z.string(),
}).strict();

export const LayoutRegionSchema = z.object({
  id: z.string(),
  purpose: z.string(),
  parent_layout: z.enum(['STACK', 'GRID', 'CLUSTER', 'SIDEBAR', 'SPLIT']),
  axis: z.enum(['BLOCK', 'INLINE']),
  spacing_token: z.string(),
  priority: UIPrioritySchema,
  emphasis: z.number().int().min(1).max(3),
  overflow: z.enum(['WRAP', 'SCROLL', 'TRUNCATE_WITH_DISCLOSURE', 'GROW']),
  min_inline: z.string(),
  max_inline: z.string(),
  responsive_transform: ResponsiveTransformSchema,
}).strict();

export const ScreenTraceSchema = z.object({
  user_task: nonEmpty,
  content: nonEmpty,
  contract: nonEmpty,
  component: nonEmpty,
  token: nonEmpty,
  state: nonEmpty,
  interaction: nonEmpty,
  responsive_rule: nonEmpty,
  a11y_rule: nonEmpty,
  performance_rule: nonEmpty,
  implementation_path: nonEmpty,
  test: nonEmpty,
  evidence: nonEmpty,
}).strict();

export const UIScreenSchema = z.object({
  id: z.string(),
  name: z.string(),
  purpose: z.string(),
  user_task: z.string(),
  priority: UIPrioritySchema,
  regions: z.array(LayoutRegionSchema).min(1),
  components: z.array(z.string()).min(1),
  trace: ScreenTraceSchema,
}).strict();

export const ComponentSpecSchema = z.object({
  id: z.string(),
  name: z.string(),
  semantic_role: z.string(),
  purpose: z.string(),
  tokens: z.array(z.string()),
  states: z.array(UIStateSchema).min(1),
  interactions: z.array(z.string()),
  a11y: z.array(z.string()),
  implementation: ImplementationStatusSchema,
}).strict();

export const StateSpecSchema = z.object({
  component_ref: z.string(),
  state: UIStateSchema,
  trigger: z.string(),
  visual_delta: z.string(),
  content_delta: z.string(),
  semantics: z.string(),
  keyboard: z.string(),
  announcement: z.string(),
  motion: z.string(),
  recovery: z.string(),
  persistence: z.string(),
  non_color_channel: z.string().nullable(),
}).strict();

export const InteractionSpecSchema = z.object({
  id: z.string(),
  component_ref: z.string(),
  trigger: z.string(),
  input_modes: z.array(InputModeSchema).min(1),
  feedback: z.string(),
  standard: z.boolean(),
  justification: z.string().nullable(),
  fallback: z.string().nullable(),
}).strict();

export const ResponsiveRuleSchema = z.object({
  region_ref: z.string(),
  condition: z.string(),
  transform: ResponsiveTransformSchema,
  rationale: z.string(),
}).strict();

export const A11yRequirementSchema = z.object({
  id: z.string(),
  criterion: z.string(),
  rule: z.string(),
  verification: A11yVerificationSchema,
}).strict();

export const AccessibilitySpecSchema = z.object({
  target: z.literal('WCAG 2.2'),
  requirements: z.array(A11yRequirementSchema),
  predicted: z.array(z.string()),
  verified: z.array(z.string()),
  risks: z.array(z.string()),
  tests_required: z.array(z.string()),
}).strict();

export const UIMetricSchema = z.object({
  name: z.string(),
  target: z.string(),
  truth: MetricTruthSchema,
  source: z.string(),
  formula: z.string(),
  timestamp: z.string().nullable(),
  freshness: z.string(),
  uncertainty: z.string(),
  fallback: z.string(),
}).strict().refine((metric) => metric.truth !== 'MEASURED' || Boolean(metric.timestamp), {
  message: 'a MEASURED metric requires a measurement timestamp',
});

export const PerformanceSpecSchema = z.object({
  requirements: z.array(z.string()),
  risks: z.array(z.string()),
  budgets: z.array(UIMetricSchema),
}).strict();

export const AITrustSpecSchema = z.object({
  required: z.boolean(),
  provenance_rules: z.array(z.string()),
  attribution_rules: z.array(z.string()),
  uncertainty_rules: z.array(z.string()),
  feedback_rules: z.array(z.string()),
  confidence_display: z.enum(['NOT_MEASURED', 'CALIBRATED_BACKEND_ONLY']),
}).strict();

export const ImplementationMappingSchema = z.object({
  verified_existing: z.array(z.string()),
  extend: z.array(z.string()),
  proposed: z.array(z.string()),
  contracts: z.array(z.string()),
  state_dependencies: z.array(z.string()),
  events: z.array(z.string()),
  tests: z.array(z.string()),
}).strict();

export const DesignSystemSpecSchema = z.object({
  foundations: z.array(z.string()),
  patterns: z.array(z.string()),
  templates: z.array(z.string()),
  content_rules: z.array(z.string()),
  state_rules: z.array(z.string()),
  motion_rules: z.array(z.string()),
  accessibility_rules: z.array(z.string()),
  responsive_rules: z.array(z.string()),
}).strict();

export const EvaluationFindingSchema = z.object({
  engine: EvaluationEngineSchema,
  severity: SeveritySchema,
  subject: z.string(),
  message: z.string(),
  repaired: z.boolean(),
  repair_action: z.string().nullable(),
}).strict();

export const UIValidationCheckSchema = z.object({ id: z.string(), status: CheckStatusSchema, evidence: z.string() }).strict();
export const UIConfidenceSchema = z.object({
  value: z.number().min(0).max(1),
  basis: z.array(z.string()),
  unknowns: z.array(z.string()),
}).strict();

export const UIUXDesignIRSchema = z.object({
  schema_version: z.literal(UIUX_SCHEMA_VERSION),
  compiler_version: z.literal('amc-uiux-compiler/v1'),
  project_ref: z.string(),
  mode: SurfaceModeSchema,
  product_model: ProductModelSchema,
  sources: z.array(UISourceRefSchema),
  assumptions: z.array(UIAssumptionSchema),
  unknowns: z.array(UIUnknownSchema),
  constraints: z.array(z.string()),
  capabilities: z.array(z.string()),
  information_architecture: InformationArchitectureSchema,
  flows: z.array(FlowSchema).min(1),
  territories: z.array(TerritorySchema).min(1),
  selected_direction: z.string(),
  principles_applied: z.array(PrincipleApplicationSchema),
  design_genome: DesignGenomeSchema,
  design_system: DesignSystemSpecSchema,
  tokens: TokenSystemSpecSchema,
  screens: z.array(UIScreenSchema).min(1),
  components: z.array(ComponentSpecSchema).min(1),
  states: z.array(StateSpecSchema).min(1),
  interactions: z.array(InteractionSpecSchema).min(1),
  responsive_rules: z.array(ResponsiveRuleSchema).min(1),
  accessibility: AccessibilitySpecSchema,
  performance: PerformanceSpecSchema,
  ai_trust: AITrustSpecSchema,
  implementation_mapping: ImplementationMappingSchema,
  generation_prompts: z.array(z.string()),
  evaluation: z.array(EvaluationFindingSchema),
  repair_iterations: z.number().int().min(0).max(3),
  validation_checks: z.array(UIValidationCheckSchema),
  approval_required: z.array(z.string()),
  confidence: UIConfidenceSchema,
  handoff_only: z.literal(true),
  terminal: UIUXTerminalSchema,
  spec_hash: z.string(),
}).strict();

export type SurfaceMode = z.infer<typeof SurfaceModeSchema>;
export type UIState = z.infer<typeof UIStateSchema>;
export type UIUXTerminal = z.infer<typeof UIUXTerminalSchema>;
export type UIUXDesignIR = z.infer<typeof UIUXDesignIRSchema>;
