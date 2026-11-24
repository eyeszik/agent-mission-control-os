// Python catalog data for the UI/UX compiler. Python is the reference;
// tests/fixtures/ui-ux-catalog.json (owned by test_ui_ux_parity_fixture.py) fails if this drifts.
import type { Principle } from './types';

export const FEATURE_KEYWORDS: Readonly<Record<string, readonly string[]>> = {
  "forms": [
    "form",
    "sign up",
    "signup",
    "register",
    "checkout",
    "onboard",
    "input",
    "apply",
    "booking"
  ],
  "search": [
    "search",
    "filter",
    "sort",
    "find",
    "browse",
    "catalog"
  ],
  "data": [
    "dashboard",
    "metric",
    "kpi",
    "analytics",
    "report",
    "chart",
    "table",
    "data"
  ],
  "ai": [
    "ai",
    "assistant",
    "chat",
    "copilot",
    "llm",
    "generate",
    "agent",
    "recommend"
  ],
  "multi_step": [
    "wizard",
    "step",
    "stepper",
    "checkout",
    "onboarding",
    "multi-step",
    "flow"
  ],
  "destructive": [
    "delete",
    "remove",
    "cancel",
    "archive",
    "revoke",
    "refund"
  ],
  "approvals": [
    "approve",
    "approval",
    "review",
    "sign-off",
    "hitl"
  ],
  "realtime": [
    "real-time",
    "realtime",
    "live",
    "stream",
    "streaming",
    "sync"
  ],
  "long_content": [
    "article",
    "docs",
    "documentation",
    "long-form",
    "blog",
    "content"
  ],
  "mobile_first": [
    "mobile",
    "phone",
    "on the go",
    "field"
  ],
  "high_density": [
    "power user",
    "operator",
    "dense",
    "trading",
    "ops",
    "console",
    "admin"
  ],
  "onboarding": [
    "onboard",
    "first run",
    "getting started",
    "welcome"
  ]
};

export const PRINCIPLE_CATALOG: readonly Principle[] = [
  {
    "id": "usability.system_status",
    "name": "Visibility of system status",
    "family": "HEURISTICS",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Users act blindly when the system hides what it is doing.",
    "application": "Every async action exposes LOADING and a terminal SUCCESS/ERROR with a live-region announcement.",
    "tradeoff": "More states to design and test.",
    "a11y_effect": "Status changes are announced via polite live regions.",
    "responsive_effect": "Status stays visible when layouts collapse (never inside a collapsed drawer only).",
    "implementation_effect": "Components expose explicit async state props, not implicit spinners.",
    "effects": [
      {
        "kind": "state_rule",
        "target": "",
        "value": "Async actions render LOADING then SUCCESS or ERROR; never a silent completion.",
        "state": null
      },
      {
        "kind": "component_state",
        "target": "*action",
        "value": "",
        "state": "LOADING"
      },
      {
        "kind": "component_state",
        "target": "*action",
        "value": "",
        "state": "SUCCESS"
      }
    ]
  },
  {
    "id": "usability.error_prevention",
    "name": "Error prevention and recovery",
    "family": "USABILITY",
    "triggers": [
      "destructive",
      "forms"
    ],
    "user_problem": "Irreversible mistakes and unrecoverable errors.",
    "application": "Destructive actions require confirmation naming the object; errors state cause and a recovery action.",
    "tradeoff": "Adds a confirmation step to destructive paths.",
    "a11y_effect": "Error text is programmatically associated with the field (aria-describedby).",
    "responsive_effect": "Confirmation surfaces become full-width sheets on narrow viewports.",
    "implementation_effect": "Form controls carry error message slots and recovery handlers.",
    "effects": [
      {
        "kind": "content_rule",
        "target": "",
        "value": "Error messages state what happened, why, and the next recovery action.",
        "state": null
      },
      {
        "kind": "pattern",
        "target": "",
        "value": "Destructive actions: explicit confirmation naming the affected object; undo where the backend supports it.",
        "state": null
      },
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 3.3.1 Error Identification",
        "value": "Errors are identified in text and linked to the field.",
        "state": null
      }
    ]
  },
  {
    "id": "usability.user_control",
    "name": "User control and freedom",
    "family": "USABILITY",
    "triggers": [
      "forms",
      "multi_step",
      "stateful"
    ],
    "user_problem": "Users get trapped in flows they cannot leave or undo.",
    "application": "Every step offers back/cancel without data loss; drafts persist.",
    "tradeoff": "Draft persistence needs storage and conflict handling.",
    "a11y_effect": "Focus returns to a logical element after cancel.",
    "responsive_effect": "Back/cancel stay reachable in the collapsed layout.",
    "implementation_effect": "Flow state is serializable so drafts survive navigation.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Multi-step flows keep back/cancel available and preserve entered data.",
        "state": null
      },
      {
        "kind": "state_rule",
        "target": "",
        "value": "Draft state persists across navigation; STALE drafts are labeled with their age.",
        "state": null
      }
    ]
  },
  {
    "id": "heuristics.recognition",
    "name": "Recognition over recall",
    "family": "HEURISTICS",
    "triggers": [
      "data",
      "search",
      "stateful"
    ],
    "user_problem": "Users must remember identifiers, filters, or prior choices.",
    "application": "Show current filters, selections, and recent items in place.",
    "tradeoff": "Persistent chips consume horizontal space.",
    "a11y_effect": "Active filters are exposed as a labeled list, not color alone.",
    "responsive_effect": "Filter chips WRAP, then collapse into a count + drawer on narrow viewports.",
    "implementation_effect": "Filter state lives in the URL for shareability and back-button support.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Active filters/selections are always visible with a single clear-all control.",
        "state": null
      },
      {
        "kind": "responsive",
        "target": "filter",
        "value": "WRAP",
        "state": null
      }
    ]
  },
  {
    "id": "gestalt.proximity",
    "name": "Proximity and common region",
    "family": "GESTALT",
    "triggers": [
      "data",
      "forms",
      "high_density"
    ],
    "user_problem": "Related controls read as unrelated noise.",
    "application": "Group related fields/metrics in labeled regions; spacing inside groups is tighter than between groups.",
    "tradeoff": "Requires disciplined spacing tokens.",
    "a11y_effect": "Groups use fieldset/legend or region landmarks with names.",
    "responsive_effect": "Groups STACK as units; they never split across columns.",
    "implementation_effect": "Spacing uses semantic tokens (inline < stack < panel).",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Spacing hierarchy: semantic.space.inline < semantic.space.stack < semantic.space.panel.",
        "state": null
      },
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 1.3.1 Info and Relationships",
        "value": "Visual groups are programmatic groups (fieldset/legend, labeled regions).",
        "state": null
      }
    ]
  },
  {
    "id": "cognitive.progressive_disclosure",
    "name": "Progressive disclosure",
    "family": "COGNITIVE",
    "triggers": [
      "data",
      "forms",
      "high_density"
    ],
    "user_problem": "Everything-at-once screens overload working memory.",
    "application": "Primary fields and metrics first; advanced options behind an explicit disclosure.",
    "tradeoff": "Hidden options are less discoverable.",
    "a11y_effect": "Disclosures use aria-expanded and keep focus in place.",
    "responsive_effect": "Secondary panels COLLAPSE before primary content shrinks.",
    "implementation_effect": "Disclosure components expose EXPANDED state.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*disclosure",
        "value": "",
        "state": "EXPANDED"
      },
      {
        "kind": "responsive",
        "target": "detail",
        "value": "COLLAPSE",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.hick",
    "name": "Hick's law — limit simultaneous choices",
    "family": "BEHAVIORAL",
    "triggers": [
      "onboarding",
      "persuasion",
      "surface:LANDING_PAGE"
    ],
    "user_problem": "Too many equal-weight choices stall the decision.",
    "application": "One primary call to action per view; secondary actions are visually subordinate.",
    "tradeoff": "Secondary paths get less attention.",
    "a11y_effect": "The primary action is first in reading and focus order.",
    "responsive_effect": "Secondary actions move into a menu before the primary shrinks.",
    "implementation_effect": "CTA components accept a single `primary` variant per region.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Exactly one primary action per view; secondary actions use the subordinate variant.",
        "state": null
      },
      {
        "kind": "genome",
        "target": "interaction",
        "value": "single dominant action per view",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.fitts",
    "name": "Fitts's law — target size and distance",
    "family": "BEHAVIORAL",
    "triggers": [
      "interactive",
      "mobile_first"
    ],
    "user_problem": "Small or distant targets cause missed taps and slow pointing.",
    "application": "Interactive targets are at least 24x24 CSS px (WCAG 2.2 SC 2.5.8), 44x44 for primary touch actions.",
    "tradeoff": "Larger targets reduce density.",
    "a11y_effect": "Meets WCAG 2.2 SC 2.5.8 Target Size (Minimum).",
    "responsive_effect": "Primary actions go FULL_WIDTH on narrow touch viewports.",
    "implementation_effect": "Buttons enforce a min-block-size token.",
    "effects": [
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 2.5.8 Target Size (Minimum)",
        "value": "Interactive targets are at least 24x24 CSS px; primary touch targets 44x44.",
        "state": null
      },
      {
        "kind": "responsive",
        "target": "cta",
        "value": "FULL_WIDTH",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.jakob",
    "name": "Jakob's law — follow platform conventions",
    "family": "BEHAVIORAL",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Novel interaction patterns force users to relearn basics.",
    "application": "Use native controls and standard placements; nonstandard interactions must justify themselves.",
    "tradeoff": "Less room for novelty in core controls.",
    "a11y_effect": "Native elements carry correct roles and keyboard behavior by default.",
    "responsive_effect": "Standard navigation transforms (MENU/DRAWER) instead of bespoke gestures.",
    "implementation_effect": "Prefer semantic HTML elements over div-based widgets.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Core controls are native elements (button, a, input, select, dialog) before any custom widget.",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.tesler",
    "name": "Tesler's law — own the irreducible complexity",
    "family": "BEHAVIORAL",
    "triggers": [
      "approvals",
      "data",
      "high_density"
    ],
    "user_problem": "Pushing complexity onto users produces errors and abandonment.",
    "application": "The system pre-fills, validates, and explains; users confirm rather than compute.",
    "tradeoff": "Moves logic into the backend contract.",
    "a11y_effect": "Explanations are text, not tooltips-only.",
    "responsive_effect": "Explanations remain inline on narrow viewports.",
    "implementation_effect": "Backend contracts return derived values with provenance.",
    "effects": [
      {
        "kind": "content_rule",
        "target": "",
        "value": "Derived values show how they were derived (source + formula) where users act on them.",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.von_restorff",
    "name": "Von Restorff — reserve distinctiveness",
    "family": "BEHAVIORAL",
    "triggers": [
      "approvals",
      "data",
      "persuasion"
    ],
    "user_problem": "When everything is emphasized nothing is.",
    "application": "Only the P0 element and critical status get the accent treatment.",
    "tradeoff": "Brand accent appears less often.",
    "a11y_effect": "Distinctiveness never relies on color alone.",
    "responsive_effect": "Accent emphasis survives stacking (it moves with the P0 region).",
    "implementation_effect": "Accent tokens are only mapped to primary/critical variants.",
    "effects": [
      {
        "kind": "genome",
        "target": "color",
        "value": "accent reserved for the P0 action and critical status only",
        "state": null
      }
    ]
  },
  {
    "id": "behavioral.truthful_progress",
    "name": "Truthful progress",
    "family": "BEHAVIORAL",
    "triggers": [
      "ai",
      "multi_step",
      "realtime"
    ],
    "user_problem": "Fake progress bars and invented ETAs destroy trust.",
    "application": "Show determinate progress only when the backend reports it; otherwise indeterminate + elapsed time.",
    "tradeoff": "Less reassuring than a fabricated percentage.",
    "a11y_effect": "Progress uses role=progressbar with aria-valuenow only when determinate.",
    "responsive_effect": "Progress stays in the primary region when layouts stack.",
    "implementation_effect": "Progress components accept `determinate: false` without a value.",
    "effects": [
      {
        "kind": "state_rule",
        "target": "",
        "value": "Determinate progress only from backend-reported values; never a synthetic percentage or ETA.",
        "state": null
      },
      {
        "kind": "component_state",
        "target": "*progress",
        "value": "",
        "state": "PENDING"
      }
    ]
  },
  {
    "id": "visual.hierarchy",
    "name": "Visual hierarchy through salience budget",
    "family": "VISUAL",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Users cannot find the primary task among decoration.",
    "application": "Salience is budgeted: P0 strongest, P3 never outweighs P0.",
    "tradeoff": "Decorative elements lose visual weight.",
    "a11y_effect": "Heading levels mirror the visual hierarchy.",
    "responsive_effect": "PRIORITY_REDUCTION drops P3 before compressing P0.",
    "implementation_effect": "Regions carry priority + emphasis metadata.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Salience budget: P0 > P1 > P2 > P3; P3 regions are removed first under constraint.",
        "state": null
      },
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 2.4.6 Headings and Labels",
        "value": "Heading structure mirrors the visual hierarchy.",
        "state": null
      }
    ]
  },
  {
    "id": "interaction.feedback",
    "name": "Immediate, proportionate feedback",
    "family": "INTERACTION",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Actions without feedback get repeated or abandoned.",
    "application": "Every press shows PRESSED within one frame and a result within the async contract.",
    "tradeoff": "Needs motion/state design per control.",
    "a11y_effect": "Feedback is perceivable without motion or color.",
    "responsive_effect": "Feedback anchors to the control, not a region that may collapse.",
    "implementation_effect": "Controls expose PRESSED and disabled-while-pending states.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*action",
        "value": "",
        "state": "PRESSED"
      },
      {
        "kind": "motion_rule",
        "target": "",
        "value": "Feedback motion <= semantic.motion.duration.feedback; disabled under prefers-reduced-motion.",
        "state": null
      }
    ]
  },
  {
    "id": "interaction.forms",
    "name": "Forms: labels, inline validation, preserved input",
    "family": "INTERACTION",
    "triggers": [
      "forms"
    ],
    "user_problem": "Unlabeled fields and late validation cause rework.",
    "application": "Persistent visible labels; validate on blur/submit, never on first keystroke; keep input on error.",
    "tradeoff": "Longer forms visually.",
    "a11y_effect": "Labels are programmatic; required state is text, not asterisk color.",
    "responsive_effect": "Fields STACK single-column on narrow viewports.",
    "implementation_effect": "Field components expose VALID/INVALID/WARNING/READ_ONLY.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*field",
        "value": "",
        "state": "INVALID"
      },
      {
        "kind": "component_state",
        "target": "*field",
        "value": "",
        "state": "VALID"
      },
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 3.3.2 Labels or Instructions",
        "value": "Every input has a persistent visible label.",
        "state": null
      },
      {
        "kind": "responsive",
        "target": "form",
        "value": "STACK",
        "state": null
      }
    ]
  },
  {
    "id": "interaction.search",
    "name": "Search, filter, sort",
    "family": "INTERACTION",
    "triggers": [
      "search"
    ],
    "user_problem": "Users cannot narrow large collections.",
    "application": "Search is debounced, results count is announced, empty results suggest recovery.",
    "tradeoff": "More states (no-results, partial).",
    "a11y_effect": "Result counts announced via live region.",
    "responsive_effect": "Filters move into a DRAWER on narrow viewports.",
    "implementation_effect": "Query state is URL-backed.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*result",
        "value": "",
        "state": "EMPTY"
      },
      {
        "kind": "responsive",
        "target": "filter",
        "value": "DRAWER",
        "state": null
      }
    ]
  },
  {
    "id": "interaction.empty_loading_error",
    "name": "Designed empty, loading, and error states",
    "family": "INTERACTION",
    "triggers": [
      "ai",
      "data",
      "stateful"
    ],
    "user_problem": "Blank screens look broken; spinners hide structure.",
    "application": "Skeletons mirror final layout; empty states explain and offer the first action; errors offer retry.",
    "tradeoff": "Three extra designs per data surface.",
    "a11y_effect": "Skeletons are aria-hidden with a live 'Loading' status.",
    "responsive_effect": "Empty states keep the primary action visible at every width.",
    "implementation_effect": "Data components expose SKELETON/EMPTY/ERROR/STALE.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*data",
        "value": "",
        "state": "SKELETON"
      },
      {
        "kind": "component_state",
        "target": "*data",
        "value": "",
        "state": "EMPTY"
      },
      {
        "kind": "component_state",
        "target": "*data",
        "value": "",
        "state": "ERROR"
      },
      {
        "kind": "component_state",
        "target": "*data",
        "value": "",
        "state": "STALE"
      }
    ]
  },
  {
    "id": "interaction.modals",
    "name": "Modal discipline",
    "family": "INTERACTION",
    "triggers": [
      "approvals",
      "destructive"
    ],
    "user_problem": "Modals interrupt and trap focus incorrectly.",
    "application": "Modals only for decisions that block progress; focus is trapped and restored.",
    "tradeoff": "Some confirmations become inline.",
    "a11y_effect": "dialog element with focus trap and Escape to close.",
    "responsive_effect": "Modals become full-screen sheets on narrow viewports.",
    "implementation_effect": "Use the native <dialog> element.",
    "effects": [
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 2.4.3 Focus Order",
        "value": "Dialogs trap focus while open and restore it to the invoking control on close.",
        "state": null
      }
    ]
  },
  {
    "id": "platform.responsive_semantic_zoom",
    "name": "Semantic zoom",
    "family": "PLATFORM",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Shrinking a desktop layout produces an unusable mobile one.",
    "application": "Responsive changes transform representation (table -> list, sidebar -> drawer), not just scale.",
    "tradeoff": "More layout variants.",
    "a11y_effect": "Reflow at 320 CSS px without two-dimensional scrolling (SC 1.4.10).",
    "responsive_effect": "Each region declares its transform.",
    "implementation_effect": "Container queries where regions are reused.",
    "effects": [
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 1.4.10 Reflow",
        "value": "Content reflows at 320 CSS px without two-dimensional scrolling (data tables excepted with scroll containers).",
        "state": null
      },
      {
        "kind": "responsive",
        "target": "table",
        "value": "SCROLL",
        "state": null
      }
    ]
  },
  {
    "id": "platform.keyboard",
    "name": "Full keyboard operability",
    "family": "PLATFORM",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Keyboard and switch users are locked out.",
    "application": "Every interaction has a keyboard path; focus is always visible and never obscured.",
    "tradeoff": "Custom widgets need roving tabindex work.",
    "a11y_effect": "WCAG 2.2 SC 2.1.1 Keyboard, 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured.",
    "responsive_effect": "Sticky headers must not cover the focused element.",
    "implementation_effect": "Focus ring uses semantic.color.focus-ring.",
    "effects": [
      {
        "kind": "interaction_input",
        "target": "",
        "value": "KEYBOARD",
        "state": null
      },
      {
        "kind": "a11y",
        "target": "WCAG 2.2 SC 2.4.11 Focus Not Obscured (Minimum)",
        "value": "Sticky/fixed regions never fully hide the focused element.",
        "state": null
      },
      {
        "kind": "component_state",
        "target": "*action",
        "value": "",
        "state": "FOCUS_VISIBLE"
      }
    ]
  },
  {
    "id": "platform.rtl",
    "name": "Bidirectional layout",
    "family": "PLATFORM",
    "triggers": [
      "rtl"
    ],
    "user_problem": "Mirrored locales break physical-direction layouts.",
    "application": "Use logical properties (inline-start/end) everywhere; icons with direction mirror.",
    "tradeoff": "Directional icons need variants.",
    "a11y_effect": "Reading order matches visual order in both directions.",
    "responsive_effect": "Transforms are expressed in logical axes.",
    "implementation_effect": "No left/right CSS in components.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Layout uses logical properties only (margin-inline-start, inset-inline-end).",
        "state": null
      },
      {
        "kind": "genome",
        "target": "geometry",
        "value": "direction-agnostic logical geometry",
        "state": null
      }
    ]
  },
  {
    "id": "system.ai_trust",
    "name": "Truthful AI provenance",
    "family": "SYSTEM",
    "triggers": [
      "ai"
    ],
    "user_problem": "Users over-trust or mis-attribute machine output.",
    "application": "AI output is wrapped in one trust envelope stating involvement, known provider/model, sources, and review status; no decorative confidence.",
    "tradeoff": "Less 'magical' presentation.",
    "a11y_effect": "Provenance is text, reachable by keyboard, announced when streaming completes.",
    "responsive_effect": "The provenance label never collapses away on narrow viewports.",
    "implementation_effect": "A single AITrustEnvelope scope per AI response.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*ai",
        "value": "",
        "state": "STREAMING"
      },
      {
        "kind": "component_state",
        "target": "*ai",
        "value": "",
        "state": "DEGRADED"
      },
      {
        "kind": "component_state",
        "target": "*ai",
        "value": "",
        "state": "UNAVAILABLE"
      },
      {
        "kind": "content_rule",
        "target": "",
        "value": "AI content is labeled AI-generated or AI-assisted; confidence is shown only from a calibrated backend value, otherwise 'Confidence not measured'.",
        "state": null
      }
    ]
  },
  {
    "id": "system.approvals",
    "name": "Human approval is a first-class state",
    "family": "SYSTEM",
    "triggers": [
      "approvals"
    ],
    "user_problem": "Users cannot tell draft, pending, and approved work apart.",
    "application": "PENDING_APPROVAL, APPROVED, REJECTED are distinct in text and icon, not color alone.",
    "tradeoff": "More status vocabulary.",
    "a11y_effect": "Status is exposed as text.",
    "responsive_effect": "Status badges stay attached to their item when lists stack.",
    "implementation_effect": "Status comes from the backend lifecycle, never inferred in the client.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*status",
        "value": "",
        "state": "PENDING_APPROVAL"
      },
      {
        "kind": "component_state",
        "target": "*status",
        "value": "",
        "state": "APPROVED"
      },
      {
        "kind": "component_state",
        "target": "*status",
        "value": "",
        "state": "REJECTED"
      }
    ]
  },
  {
    "id": "system.realtime_resilience",
    "name": "Degraded-network resilience",
    "family": "SYSTEM",
    "triggers": [
      "ai",
      "data",
      "realtime"
    ],
    "user_problem": "Live surfaces silently show stale data when the connection drops.",
    "application": "OFFLINE and STALE are explicit; reconnection is automatic with a visible manual retry.",
    "tradeoff": "Extra connection-state UI.",
    "a11y_effect": "Connection changes announced politely.",
    "responsive_effect": "Connection status remains visible in collapsed layouts.",
    "implementation_effect": "Stream/socket clients expose connection state and clean up on unmount.",
    "effects": [
      {
        "kind": "component_state",
        "target": "*data",
        "value": "",
        "state": "OFFLINE"
      },
      {
        "kind": "perf",
        "target": "",
        "value": "Streams, sockets, observers, and timers are cleaned up on unmount.",
        "state": null
      }
    ]
  },
  {
    "id": "system.reduced_motion",
    "name": "Motion is optional",
    "family": "SYSTEM",
    "triggers": [
      "interactive"
    ],
    "user_problem": "Motion causes vestibular harm and distracts.",
    "application": "All non-essential motion is disabled under prefers-reduced-motion; meaning never depends on motion.",
    "tradeoff": "Some delight is lost for those users.",
    "a11y_effect": "WCAG 2.2 SC 2.3.3 Animation from Interactions (AAA) respected via reduced-motion.",
    "responsive_effect": "No motion-dependent reveal of content at any width.",
    "implementation_effect": "Motion reads semantic.motion tokens and a reduced-motion guard.",
    "effects": [
      {
        "kind": "motion_rule",
        "target": "",
        "value": "prefers-reduced-motion: reduce disables non-essential animation; state changes remain perceivable statically.",
        "state": null
      }
    ]
  },
  {
    "id": "cognitive.structured_density",
    "name": "Structured density for expert users",
    "family": "COGNITIVE",
    "triggers": [
      "high_density"
    ],
    "user_problem": "Experts are slowed by consumer-grade whitespace.",
    "application": "Denser rows with strict alignment and tabular numerals; density never drops below target sizes.",
    "tradeoff": "Harder for novices.",
    "a11y_effect": "Density respects the 24px minimum target size.",
    "responsive_effect": "Density relaxes on touch viewports.",
    "implementation_effect": "Density is a token scale, not ad hoc spacing.",
    "effects": [
      {
        "kind": "genome",
        "target": "density",
        "value": "HIGH",
        "state": null
      },
      {
        "kind": "pattern",
        "target": "",
        "value": "Numeric data uses tabular numerals and right alignment.",
        "state": null
      }
    ]
  },
  {
    "id": "visual.anti_generic_signature",
    "name": "Product-specific signature",
    "family": "VISUAL",
    "triggers": [
      "persuasion",
      "surface:LANDING_PAGE"
    ],
    "user_problem": "Template-looking pages are indistinguishable and untrustworthy.",
    "application": "One product-specific signature element derived from the brand thesis replaces generic decoration.",
    "tradeoff": "Requires real brand input.",
    "a11y_effect": "Signature is decorative-only (aria-hidden) or has a text equivalent.",
    "responsive_effect": "Signature scales down or drops (P3) before content.",
    "implementation_effect": "Signature is a single component, not scattered effects.",
    "effects": [
      {
        "kind": "pattern",
        "target": "",
        "value": "Replace generic decoration (gradients, glows, floating blobs) with one brand-derived signature element.",
        "state": null
      }
    ]
  }
];
