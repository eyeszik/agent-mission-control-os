/**
 * Types for the UI/UX compiler. The IR types are `@amc/shared`'s strict Zod
 * twin of `ui_ux/models.py`, reused rather than forked: the compiler's output
 * is parsed by `UIUXDesignIRSchema` in the tests.
 */
import type { z } from 'zod';
import type {
  A11yVerificationSchema,
  EvaluationEngineSchema,
  ImplementationStatusSchema,
  PrincipleFamilySchema,
  ResponsiveTransformSchema,
  SeveritySchema,
  SurfaceMode,
  UIPlatformSchema,
  UIPrioritySchema,
  UISourceKindSchema,
  UIState,
  UIUXDesignIR,
  WCAGRequirementSchema,
} from '@amc/shared';

export type { SurfaceMode, UIState, UIUXDesignIR };
export type Platform = z.infer<typeof UIPlatformSchema>;
export type Priority = z.infer<typeof UIPrioritySchema>;
export type ResponsiveTransform = z.infer<typeof ResponsiveTransformSchema>;
export type A11yVerification = z.infer<typeof A11yVerificationSchema>;
export type SourceKind = z.infer<typeof UISourceKindSchema>;
export type PrincipleFamily = z.infer<typeof PrincipleFamilySchema>;
export type ImplementationStatus = z.infer<typeof ImplementationStatusSchema>;
export type EvaluationEngine = z.infer<typeof EvaluationEngineSchema>;
export type Severity = z.infer<typeof SeveritySchema>;
export type WCAGRequirement = z.infer<typeof WCAGRequirementSchema>;

export type LayoutRegion = UIUXDesignIR['screens'][number]['regions'][number];
export type InteractionSpec = UIUXDesignIR['interactions'][number];
export type DesignGenome = UIUXDesignIR['design_genome'];
export type A11yRequirement = UIUXDesignIR['accessibility']['requirements'][number];
export type Assumption = UIUXDesignIR['assumptions'][number];
export type Unknown = UIUXDesignIR['unknowns'][number];
export type SourceRef = UIUXDesignIR['sources'][number];
export type ContrastCheck = UIUXDesignIR['tokens']['contrast'][number];
export type TokenSystemSpec = UIUXDesignIR['tokens'];
export type EvaluationFinding = UIUXDesignIR['evaluation'][number];
export type Territory = UIUXDesignIR['territories'][number];
export type PrincipleApplication = UIUXDesignIR['principles_applied'][number];
export type StateSpec = UIUXDesignIR['states'][number];

/** Python `_ComponentTemplate`. */
export interface ComponentTemplate {
  readonly role: string;
  readonly purpose: string;
  readonly tags: readonly string[];
  readonly states: readonly UIState[];
  readonly a11y: readonly string[];
}

/** One row of the state table: trigger, visual, content, semantics, keyboard, announcement, motion, recovery, persistence, non-color channel. */
export type StateRow = readonly [string, string, string, string, string, string, string, string, string, string | null];

export interface TerritoryTemplate {
  readonly id: string;
  readonly name: string;
  readonly thesis: string;
  readonly affinities: readonly string[];
  readonly modes: readonly SurfaceMode[];
}

export interface ScreenTemplate {
  readonly id: string;
  readonly name: string;
  readonly purpose: string;
  readonly priority: Priority;
  readonly regions: readonly LayoutRegion[];
  readonly components: readonly string[];
}

export interface FlowTemplate {
  readonly id: string;
  readonly name: string;
  readonly goal: string;
  readonly steps: ReadonlyArray<{ screen_ref: string; user_action: string; system_response: string; failure_path: string }>;
  readonly success_signal: string;
}

export interface SurfaceTemplate {
  readonly nav: ReadonlyArray<readonly [string, string, string, Priority]>;
  readonly screens: readonly ScreenTemplate[];
  readonly flows: readonly FlowTemplate[];
}

/** Python `Effect`: one concrete edit; `kind` names the IR surface the compiler mutates. */
export interface Effect {
  readonly kind: string;
  readonly target: string;
  readonly value: string;
  readonly state: UIState | null;
}

export interface Principle {
  readonly id: string;
  readonly name: string;
  readonly family: PrincipleFamily;
  readonly triggers: readonly string[];
  readonly user_problem: string;
  readonly application: string;
  readonly tradeoff: string;
  readonly a11y_effect: string;
  readonly responsive_effect: string;
  readonly implementation_effect: string;
  readonly effects: readonly Effect[];
}

export type DesignSystemKey = 'patterns' | 'state_rules' | 'content_rules' | 'motion_rules';

export interface DraftScreen {
  readonly id: string;
  readonly name: string;
  readonly purpose: string;
  readonly priority: Priority;
  regions: LayoutRegion[];
  components: string[];
}

export interface DraftComponent {
  readonly template: ComponentTemplate;
  states: UIState[];
  readonly status: ImplementationStatus;
}

/** Python `Draft`: the mutable working copy the principles and the repair loop edit. */
export interface Draft {
  readonly mode: SurfaceMode;
  readonly features: ReadonlySet<string>;
  readonly screens: DraftScreen[];
  readonly components: Map<string, DraftComponent>;
  interactions: InteractionSpec[];
  genome: DesignGenome;
  readonly design_system: Record<DesignSystemKey, string[]>;
  a11y: A11yRequirement[];
  performance_requirements: string[];
  assumptions: Assumption[];
  approval_required: string[];
}
