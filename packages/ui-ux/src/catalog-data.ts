// Python catalog data for the UI/UX compiler. Python is the reference;
// tests/fixtures/ui-ux-catalog.json (owned by test_ui_ux_parity_fixture.py) fails if this drifts.
import type { ComponentTemplate, StateRow, SurfaceTemplate, TerritoryTemplate } from './types';

export const COMPONENT_TEMPLATES: Readonly<Record<string, ComponentTemplate>> = {
  "SiteHeader": {
    "role": "banner + nav landmark",
    "purpose": "Brand identity and primary navigation.",
    "tags": [
      "nav"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED",
      "CURRENT"
    ],
    "a11y": [
      "Skip link to main content precedes the header."
    ]
  },
  "HeroSection": {
    "role": "region with the page h1",
    "purpose": "State the offer and the single primary action.",
    "tags": [
      "content"
    ],
    "states": [
      "DEFAULT"
    ],
    "a11y": [
      "Exactly one h1 per page."
    ]
  },
  "PrimaryCTA": {
    "role": "button or link (by effect: navigation=a, action=button)",
    "purpose": "The one primary action for the view.",
    "tags": [
      "action",
      "cta"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED"
    ],
    "a11y": []
  },
  "FeatureList": {
    "role": "list",
    "purpose": "Specific capabilities stated as user outcomes.",
    "tags": [
      "content"
    ],
    "states": [
      "DEFAULT"
    ],
    "a11y": []
  },
  "EvidenceBlock": {
    "role": "figure / blockquote with cite",
    "purpose": "Sourced proof only (quotes, logos, figures carry a source).",
    "tags": [
      "content",
      "evidence"
    ],
    "states": [
      "DEFAULT",
      "EMPTY"
    ],
    "a11y": [
      "Quotes carry a visible attribution."
    ]
  },
  "SiteFooter": {
    "role": "contentinfo landmark",
    "purpose": "Secondary links and legal.",
    "tags": [
      "nav"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED"
    ],
    "a11y": []
  },
  "AppShell": {
    "role": "layout with banner/nav/main landmarks",
    "purpose": "Stable frame for the primary task.",
    "tags": [
      "layout"
    ],
    "states": [
      "DEFAULT"
    ],
    "a11y": [
      "One main landmark; landmarks are labeled."
    ]
  },
  "NavRail": {
    "role": "nav landmark with aria-current",
    "purpose": "Move between top-level areas.",
    "tags": [
      "action",
      "nav"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED",
      "CURRENT"
    ],
    "a11y": []
  },
  "TaskList": {
    "role": "list or grid with row actions",
    "purpose": "Scan and pick the item to work on.",
    "tags": [
      "action",
      "data",
      "result"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED",
      "SELECTED",
      "LOADING"
    ],
    "a11y": []
  },
  "TaskDetail": {
    "role": "region labeled by item title",
    "purpose": "Inspect and act on one item.",
    "tags": [
      "data",
      "disclosure"
    ],
    "states": [
      "DEFAULT",
      "LOADING"
    ],
    "a11y": []
  },
  "EditForm": {
    "role": "form with fieldset/legend groups",
    "purpose": "Create or change an item.",
    "tags": [
      "action",
      "field",
      "form"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED",
      "READ_ONLY"
    ],
    "a11y": []
  },
  "StatusToast": {
    "role": "status live region (polite)",
    "purpose": "Confirm async outcomes without stealing focus.",
    "tags": [
      "status"
    ],
    "states": [
      "DEFAULT",
      "SUCCESS",
      "ERROR"
    ],
    "a11y": []
  },
  "FilterBar": {
    "role": "search landmark + form controls",
    "purpose": "Narrow the data shown.",
    "tags": [
      "action",
      "field",
      "filter"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED",
      "CHECKED"
    ],
    "a11y": []
  },
  "MetricTile": {
    "role": "figure with figcaption",
    "purpose": "One metric with its truth label (measured/estimated/not measured).",
    "tags": [
      "data",
      "metric"
    ],
    "states": [
      "DEFAULT",
      "LOADING"
    ],
    "a11y": []
  },
  "ChartPanel": {
    "role": "figure with an equivalent data table",
    "purpose": "Show a trend; the table is the accessible equivalent.",
    "tags": [
      "data"
    ],
    "states": [
      "DEFAULT",
      "LOADING"
    ],
    "a11y": []
  },
  "DataTable": {
    "role": "table with caption and scoped headers",
    "purpose": "Exact values for comparison.",
    "tags": [
      "data",
      "result"
    ],
    "states": [
      "DEFAULT",
      "LOADING",
      "SELECTED"
    ],
    "a11y": []
  },
  "ActivityFeed": {
    "role": "feed / log",
    "purpose": "Recent events with timestamps.",
    "tags": [
      "data",
      "status"
    ],
    "states": [
      "DEFAULT",
      "LOADING"
    ],
    "a11y": []
  },
  "MessageList": {
    "role": "log live region",
    "purpose": "Conversation history; new messages announced once complete.",
    "tags": [
      "ai",
      "data"
    ],
    "states": [
      "DEFAULT",
      "LOADING"
    ],
    "a11y": []
  },
  "Composer": {
    "role": "form with labeled textarea",
    "purpose": "Write the prompt/request.",
    "tags": [
      "action",
      "field"
    ],
    "states": [
      "DEFAULT",
      "HOVER",
      "FOCUS_VISIBLE",
      "DISABLED"
    ],
    "a11y": []
  },
  "AITrustEnvelope": {
    "role": "group labeled 'AI provenance'",
    "purpose": "One truthful provenance scope per AI response.",
    "tags": [
      "ai",
      "status"
    ],
    "states": [
      "DEFAULT"
    ],
    "a11y": []
  },
  "SourcePanel": {
    "role": "complementary landmark",
    "purpose": "Sources and context behind an AI answer, when available.",
    "tags": [
      "ai",
      "disclosure"
    ],
    "states": [
      "DEFAULT",
      "EMPTY"
    ],
    "a11y": []
  },
  "ProgressStepper": {
    "role": "ordered list with aria-current=step",
    "purpose": "Where the user is in a multi-step flow.",
    "tags": [
      "nav",
      "progress",
      "status"
    ],
    "states": [
      "DEFAULT",
      "CURRENT"
    ],
    "a11y": []
  },
  "ReviewSummary": {
    "role": "region with description list",
    "purpose": "Check everything before committing.",
    "tags": [
      "data"
    ],
    "states": [
      "DEFAULT"
    ],
    "a11y": []
  },
  "ConfirmationPanel": {
    "role": "status region",
    "purpose": "Outcome of the flow with next step.",
    "tags": [
      "status"
    ],
    "states": [
      "DEFAULT",
      "SUCCESS",
      "ERROR"
    ],
    "a11y": []
  }
};

export const STATE_TABLE: Readonly<Record<string, StateRow>> = {
  "DEFAULT": [
    "initial render",
    "base tokens",
    "base content",
    "native role",
    "reachable in tab order if interactive",
    "none",
    "none",
    "n/a",
    "none",
    null
  ],
  "HOVER": [
    "pointer over target",
    "surface-raised background",
    "none",
    "none",
    "n/a (pointer only; never the sole affordance)",
    "none",
    "feedback duration",
    "n/a",
    "none",
    null
  ],
  "FOCUS_VISIBLE": [
    "keyboard focus",
    "2px focus-ring outline, offset, never removed",
    "none",
    "focused element",
    "Tab / Shift+Tab",
    "accessible name announced",
    "none",
    "n/a",
    "none",
    "outline shape"
  ],
  "PRESSED": [
    "activation start",
    "inset/darker surface",
    "none",
    "aria-pressed only for toggles",
    "Enter / Space",
    "none",
    "feedback duration",
    "n/a",
    "none",
    null
  ],
  "SELECTED": [
    "item chosen",
    "accent border + check icon",
    "selected label",
    "aria-selected=true",
    "Space toggles; arrows move",
    "'selected'",
    "none",
    "deselect",
    "session",
    "check icon"
  ],
  "CHECKED": [
    "option enabled",
    "filled control + check mark",
    "none",
    "checked=true",
    "Space",
    "'checked'",
    "none",
    "uncheck",
    "form state",
    "check mark"
  ],
  "CURRENT": [
    "location in set",
    "accent indicator bar + bold label",
    "none",
    "aria-current",
    "n/a",
    "'current'",
    "none",
    "n/a",
    "route",
    "indicator bar + weight"
  ],
  "EXPANDED": [
    "disclosure opened",
    "chevron rotated, panel shown",
    "revealed content",
    "aria-expanded=true",
    "Enter / Space toggles",
    "'expanded'",
    "reduced-motion safe reveal",
    "collapse",
    "session",
    "chevron direction"
  ],
  "DISABLED": [
    "action unavailable",
    "reduced-contrast control (still >=3:1 border)",
    "reason text nearby",
    "disabled or aria-disabled with reason",
    "skipped or focusable with reason",
    "reason on focus",
    "none",
    "state what enables it",
    "none",
    "reason text"
  ],
  "READ_ONLY": [
    "no edit permission",
    "no input chrome, plain text",
    "'Read only' label",
    "readonly",
    "focusable, not editable",
    "'read only'",
    "none",
    "request access path",
    "none",
    "'Read only' label"
  ],
  "LOADING": [
    "async request in flight",
    "indeterminate indicator; layout reserved",
    "'Loading…' text",
    "aria-busy=true",
    "focus retained",
    "polite 'Loading'",
    "reduced-motion safe spinner",
    "timeout -> ERROR",
    "none",
    "'Loading…' text"
  ],
  "STREAMING": [
    "response arriving incrementally",
    "caret/progress indicator on the growing block",
    "partial content, marked incomplete",
    "aria-busy until complete",
    "stop control focusable",
    "announce once on completion",
    "no per-token motion",
    "stop / retry",
    "none",
    "'Generating…' text"
  ],
  "SKELETON": [
    "first load of structured data",
    "neutral placeholder shapes mirroring layout",
    "none (aria-hidden)",
    "aria-hidden placeholders + live status",
    "no focusable placeholders",
    "polite 'Loading'",
    "static under reduced motion",
    "timeout -> ERROR",
    "none",
    "status text"
  ],
  "EMPTY": [
    "no data for the current scope",
    "explanatory illustration-free panel",
    "why it is empty + first action",
    "status region",
    "first action focusable",
    "result count '0' announced",
    "none",
    "primary action / clear filters",
    "none",
    "explanatory text"
  ],
  "VALID": [
    "field passes validation",
    "subtle success border + icon",
    "optional confirmation text",
    "aria-invalid=false",
    "n/a",
    "none",
    "none",
    "n/a",
    "form state",
    "success icon"
  ],
  "INVALID": [
    "field fails validation on blur/submit",
    "danger border + error icon",
    "error message: cause + fix",
    "aria-invalid=true + aria-describedby",
    "focus moves to first invalid field on submit",
    "error text announced",
    "none",
    "correct the value",
    "form state",
    "error icon + message text"
  ],
  "WARNING": [
    "risky but allowed value",
    "warning border + icon",
    "warning text",
    "aria-describedby warning",
    "n/a",
    "polite warning",
    "none",
    "confirm or change",
    "form state",
    "warning icon + text"
  ],
  "ERROR": [
    "operation failed",
    "danger surface + error icon",
    "what failed, why, what to do",
    "role=alert for blocking errors",
    "retry control focusable",
    "assertive for blocking, polite otherwise",
    "none",
    "retry / alternative path",
    "until dismissed or resolved",
    "error icon + text"
  ],
  "SUCCESS": [
    "operation succeeded",
    "success icon + message",
    "what changed",
    "status region",
    "focus not stolen",
    "polite confirmation",
    "reduced-motion safe",
    "undo where supported",
    "transient (toast) or inline",
    "success icon + text"
  ],
  "PENDING": [
    "awaiting backend confirmation",
    "clock icon + muted label",
    "'Pending' label",
    "status text",
    "n/a",
    "polite 'Pending'",
    "none",
    "cancel if supported",
    "until resolved",
    "clock icon + label"
  ],
  "PENDING_APPROVAL": [
    "awaiting human approval",
    "hourglass icon + 'Awaiting approval' badge",
    "who approves, since when",
    "status text",
    "n/a",
    "polite",
    "none",
    "view approval request",
    "until decision",
    "icon + text badge"
  ],
  "APPROVED": [
    "approval granted",
    "check-seal icon + 'Approved' badge",
    "approver + time",
    "status text",
    "n/a",
    "polite",
    "none",
    "n/a",
    "durable",
    "icon + text badge"
  ],
  "REJECTED": [
    "approval denied",
    "cross icon + 'Rejected' badge",
    "reason + next step",
    "status text",
    "n/a",
    "polite",
    "none",
    "revise and resubmit",
    "durable",
    "icon + text badge"
  ],
  "DEGRADED": [
    "fallback path used",
    "warning icon + 'Degraded' label",
    "what is reduced and why",
    "status text",
    "n/a",
    "polite",
    "none",
    "retry with full capability",
    "until recovered",
    "icon + text label"
  ],
  "STALE": [
    "data older than freshness budget",
    "clock icon + age label",
    "'Updated N min ago'",
    "status text",
    "refresh focusable",
    "polite on transition",
    "none",
    "refresh",
    "until refreshed",
    "age label"
  ],
  "DRAG": [
    "item being dragged",
    "lifted surface + drag handle",
    "none",
    "aria-grabbed legacy avoided; live instructions",
    "keyboard move alternative required",
    "instructions announced",
    "reduced-motion safe",
    "Escape cancels",
    "none",
    "handle icon + instruction text"
  ],
  "DROP_TARGET": [
    "valid drop zone under drag",
    "dashed accent outline",
    "'Drop here' text",
    "live instruction",
    "keyboard move alternative",
    "polite",
    "none",
    "Escape cancels",
    "none",
    "dashed outline + text"
  ],
  "OFFLINE": [
    "network lost",
    "offline icon + banner",
    "what still works, what is queued",
    "status region",
    "retry focusable",
    "polite",
    "none",
    "auto-reconnect + manual retry",
    "until online",
    "icon + banner text"
  ],
  "UNAVAILABLE": [
    "capability/provider not available",
    "unavailable icon + reason",
    "reason + alternative",
    "status text",
    "alternative focusable",
    "polite",
    "none",
    "alternative path",
    "until available",
    "icon + reason text"
  ]
};

export const TERRITORY_TEMPLATES: readonly TerritoryTemplate[] = [
  {
    "id": "quiet-precision",
    "name": "Quiet Precision",
    "thesis": "Restrained neutrals, exact alignment, one accent reserved for the primary action.",
    "affinities": [
      "calm",
      "clear",
      "minimal",
      "precise",
      "premium",
      "technical",
      "trustworthy"
    ],
    "modes": [
      "AI_INTERFACE",
      "APPLICATION",
      "DASHBOARD"
    ]
  },
  {
    "id": "editorial-warmth",
    "name": "Editorial Warmth",
    "thesis": "Content-led pages with generous type scale and sourced imagery doing the persuading.",
    "affinities": [
      "approachable",
      "bold",
      "friendly",
      "human",
      "inviting",
      "playful",
      "warm"
    ],
    "modes": [
      "LANDING_PAGE"
    ]
  },
  {
    "id": "operational-clarity",
    "name": "Operational Clarity",
    "thesis": "Dense, scannable, status-first layouts for people who work in the tool all day.",
    "affinities": [
      "direct",
      "efficient",
      "fast",
      "operational",
      "practical",
      "reliable"
    ],
    "modes": [
      "APPLICATION",
      "DASHBOARD",
      "FORM_FLOW"
    ]
  }
];

export const SURFACE_TEMPLATES: Readonly<Record<string, SurfaceTemplate>> = {
  "LANDING_PAGE": {
    "nav": [
      [
        "overview",
        "Overview",
        "What it is",
        "P0"
      ],
      [
        "how-it-works",
        "How it works",
        "Mechanism",
        "P1"
      ],
      [
        "pricing",
        "Pricing",
        "Cost clarity",
        "P1"
      ]
    ],
    "screens": [
      {
        "id": "landing",
        "name": "Landing page",
        "purpose": "Convert a qualified visitor",
        "priority": "P0",
        "regions": [
          {
            "id": "header-nav",
            "purpose": "Identity and navigation",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P1",
            "emphasis": 1,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "MENU"
          },
          {
            "id": "hero",
            "purpose": "Offer + primary action",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.section",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "features",
            "purpose": "Specific outcomes",
            "parent_layout": "GRID",
            "axis": "INLINE",
            "spacing_token": "semantic.space.panel",
            "priority": "P1",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "evidence",
            "purpose": "Sourced proof",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P2",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "final-cta",
            "purpose": "Repeat the primary action",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P1",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          },
          {
            "id": "footer",
            "purpose": "Secondary links",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P3",
            "emphasis": 1,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          }
        ],
        "components": [
          "SiteHeader",
          "HeroSection",
          "PrimaryCTA",
          "FeatureList",
          "EvidenceBlock",
          "SiteFooter"
        ]
      }
    ],
    "flows": [
      {
        "id": "convert",
        "name": "Understand and act",
        "goal": "Visitor takes the primary action",
        "steps": [
          {
            "screen_ref": "landing",
            "user_action": "Reads the headline",
            "system_response": "States the offer in one sentence",
            "failure_path": "Unclear offer -> visitor leaves; test headline comprehension"
          },
          {
            "screen_ref": "landing",
            "user_action": "Activates the primary CTA",
            "system_response": "Navigates to the next step or confirms",
            "failure_path": "Target unavailable -> explain and offer an alternative contact path"
          }
        ],
        "success_signal": "Primary CTA activation"
      }
    ]
  },
  "APPLICATION": {
    "nav": [
      [
        "work",
        "Work",
        "The primary task",
        "P0"
      ],
      [
        "detail",
        "Detail",
        "One item",
        "P1"
      ],
      [
        "settings",
        "Settings",
        "Configuration",
        "P2"
      ]
    ],
    "screens": [
      {
        "id": "workspace",
        "name": "Workspace",
        "purpose": "Complete the primary task",
        "priority": "P0",
        "regions": [
          {
            "id": "nav",
            "purpose": "Top-level navigation",
            "parent_layout": "SIDEBAR",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.inline",
            "priority": "P1",
            "emphasis": 1,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "DRAWER"
          },
          {
            "id": "main",
            "purpose": "Primary task list",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          },
          {
            "id": "detail",
            "purpose": "Selected item",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P2",
            "emphasis": 2,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "COLLAPSE"
          }
        ],
        "components": [
          "AppShell",
          "NavRail",
          "TaskList",
          "TaskDetail",
          "EditForm",
          "StatusToast"
        ]
      }
    ],
    "flows": [
      {
        "id": "do-work",
        "name": "Complete the task",
        "goal": "User finds an item and updates it",
        "steps": [
          {
            "screen_ref": "workspace",
            "user_action": "Selects an item",
            "system_response": "Shows its detail without losing list position",
            "failure_path": "Item deleted elsewhere -> STALE notice with refresh"
          },
          {
            "screen_ref": "workspace",
            "user_action": "Edits and saves",
            "system_response": "Validates, saves, confirms via status toast",
            "failure_path": "Save fails -> ERROR with retry; edits preserved"
          }
        ],
        "success_signal": "Item updated and confirmed"
      }
    ]
  },
  "DASHBOARD": {
    "nav": [
      [
        "overview",
        "Overview",
        "Current state at a glance",
        "P0"
      ],
      [
        "reports",
        "Reports",
        "Detail and export",
        "P1"
      ],
      [
        "settings",
        "Settings",
        "Configuration",
        "P2"
      ]
    ],
    "screens": [
      {
        "id": "overview",
        "name": "Overview dashboard",
        "purpose": "Decide what needs attention",
        "priority": "P0",
        "regions": [
          {
            "id": "filters",
            "purpose": "Scope the data",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P1",
            "emphasis": 1,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "WRAP"
          },
          {
            "id": "metrics",
            "purpose": "Key metrics with truth labels",
            "parent_layout": "GRID",
            "axis": "INLINE",
            "spacing_token": "semantic.space.stack",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "trend",
            "purpose": "Trend with table equivalent",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P1",
            "emphasis": 2,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "table",
            "purpose": "Exact values",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P1",
            "emphasis": 2,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "SCROLL"
          },
          {
            "id": "activity",
            "purpose": "Recent events",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P2",
            "emphasis": 1,
            "overflow": "TRUNCATE_WITH_DISCLOSURE",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "COLLAPSE"
          }
        ],
        "components": [
          "FilterBar",
          "MetricTile",
          "ChartPanel",
          "DataTable",
          "ActivityFeed"
        ]
      }
    ],
    "flows": [
      {
        "id": "triage",
        "name": "Find what needs attention",
        "goal": "Operator identifies and opens the item that needs action",
        "steps": [
          {
            "screen_ref": "overview",
            "user_action": "Scans metrics",
            "system_response": "Shows each metric with its truth label and freshness",
            "failure_path": "Data unavailable -> UNAVAILABLE state with reason, never a zero"
          },
          {
            "screen_ref": "overview",
            "user_action": "Applies a filter",
            "system_response": "Updates metrics/table and announces the result count",
            "failure_path": "No results -> EMPTY state with clear-filters action"
          }
        ],
        "success_signal": "Operator reaches the item needing action"
      }
    ]
  },
  "AI_INTERFACE": {
    "nav": [
      [
        "conversation",
        "Conversation",
        "Work with the assistant",
        "P0"
      ],
      [
        "history",
        "History",
        "Earlier sessions",
        "P3"
      ]
    ],
    "screens": [
      {
        "id": "assistant",
        "name": "Assistant",
        "purpose": "Get a trustworthy answer or draft",
        "priority": "P0",
        "regions": [
          {
            "id": "conversation",
            "purpose": "Messages with provenance",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "GROW",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          },
          {
            "id": "composer",
            "purpose": "Write the request",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.inline",
            "priority": "P0",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          },
          {
            "id": "sources",
            "purpose": "Sources and context",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P2",
            "emphasis": 1,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "DRAWER"
          },
          {
            "id": "history",
            "purpose": "Past sessions",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P3",
            "emphasis": 1,
            "overflow": "SCROLL",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "PRIORITY_REDUCTION"
          }
        ],
        "components": [
          "MessageList",
          "AITrustEnvelope",
          "Composer",
          "SourcePanel"
        ]
      }
    ],
    "flows": [
      {
        "id": "ask",
        "name": "Ask and verify",
        "goal": "User gets an answer and can see where it came from",
        "steps": [
          {
            "screen_ref": "assistant",
            "user_action": "Submits a request",
            "system_response": "Streams the response inside a provenance envelope",
            "failure_path": "Provider unavailable -> UNAVAILABLE state; input preserved; retry offered"
          },
          {
            "screen_ref": "assistant",
            "user_action": "Checks provenance",
            "system_response": "Shows AI involvement, provider/model if known, sources if available",
            "failure_path": "No sources -> states 'Sources unavailable' explicitly"
          }
        ],
        "success_signal": "Answer reviewed with provenance visible"
      }
    ]
  },
  "FORM_FLOW": {
    "nav": [
      [
        "details",
        "Details",
        "Enter information",
        "P0"
      ],
      [
        "review",
        "Review",
        "Check before committing",
        "P0"
      ],
      [
        "done",
        "Confirmation",
        "Outcome",
        "P1"
      ]
    ],
    "screens": [
      {
        "id": "details",
        "name": "Details step",
        "purpose": "Enter required information",
        "priority": "P0",
        "regions": [
          {
            "id": "progress",
            "purpose": "Step position",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P1",
            "emphasis": 1,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "COLLAPSE"
          },
          {
            "id": "form",
            "purpose": "Grouped fields",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "actions",
            "purpose": "Back / continue",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P0",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          }
        ],
        "components": [
          "ProgressStepper",
          "EditForm",
          "PrimaryCTA"
        ]
      },
      {
        "id": "review",
        "name": "Review step",
        "purpose": "Confirm entered information",
        "priority": "P0",
        "regions": [
          {
            "id": "summary",
            "purpose": "Everything entered",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.stack",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          },
          {
            "id": "actions",
            "purpose": "Edit / submit",
            "parent_layout": "CLUSTER",
            "axis": "INLINE",
            "spacing_token": "semantic.space.inline",
            "priority": "P0",
            "emphasis": 2,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "FULL_WIDTH"
          }
        ],
        "components": [
          "ReviewSummary",
          "PrimaryCTA"
        ]
      },
      {
        "id": "done",
        "name": "Confirmation",
        "purpose": "Know the outcome and next step",
        "priority": "P1",
        "regions": [
          {
            "id": "outcome",
            "purpose": "Result + next step",
            "parent_layout": "STACK",
            "axis": "BLOCK",
            "spacing_token": "semantic.space.panel",
            "priority": "P0",
            "emphasis": 3,
            "overflow": "WRAP",
            "min_inline": "16rem",
            "max_inline": "80rem",
            "responsive_transform": "STACK"
          }
        ],
        "components": [
          "ConfirmationPanel"
        ]
      }
    ],
    "flows": [
      {
        "id": "complete",
        "name": "Complete the flow",
        "goal": "User submits correct information once",
        "steps": [
          {
            "screen_ref": "details",
            "user_action": "Fills grouped fields",
            "system_response": "Validates on blur/submit, keeps input on error",
            "failure_path": "Invalid -> field-level error with recovery text; focus moves to first error"
          },
          {
            "screen_ref": "review",
            "user_action": "Reviews and submits",
            "system_response": "Submits once (idempotent) and shows progress",
            "failure_path": "Network failure -> OFFLINE state; submission retried safely"
          },
          {
            "screen_ref": "done",
            "user_action": "Reads the outcome",
            "system_response": "Shows the result and the next step",
            "failure_path": "Server rejection -> ERROR with reason and support path"
          }
        ],
        "success_signal": "Successful single submission"
      }
    ]
  }
};
