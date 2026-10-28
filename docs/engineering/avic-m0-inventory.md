# AVIC M0 — inventory

Checkout inspected before any change: branch `claude/ai-agency-pipeline-oae65z` reset to `origin/master` at
`94e220e9d20876cd36d5bba35010157fb8089462` ("CI: bound and retry the Chromium runtime install (#185)"). This is the
historical reference commit named in the directive; it was verified with `git rev-parse HEAD`, not assumed. The worktree
was clean. `AGENTS.md`, `CLAUDE.md` and `README.md` were read; `AGENTS.md` is the pre-implementation planning bundle
CLAUDE.md describes, not runtime.

## Source archive (`Realism_Engine_Updated_Sources_M0_M1_M2_REGENERATED.zip`)

Extracted to a scratch directory and read as data; no file from it was executed or imported.

| File | What it is | Disposition |
|---|---|---|
| `contracts.py` | dataclass `Requirement`, `SceneContract`, `Defect`; JSON digest | Ideas kept (requirement ids, defect evidence rule "VERIFIED needs evidence"); re-expressed as strict Pydantic records on AMC-CANON-1 (`agency/avic/contracts.py`) |
| `svg_pipeline.py` | procedural sphere SVG, regex `safe_svg`, CairoSVG raster, linear-light composite | Not reused: regex denylist replaced by an allowlist on top of the repo's `svg_safety`; CairoSVG is not installed here; raster compositing is out of AVIC scope |
| `design_compiler.py` | palette quantisation of references, fixed procedural layout | Idea kept (measured palette only, `semantic_analysis = NOT_IMPLEMENTED`, rights tracked); stdlib re-implementation in `references.py` |
| `color_pipeline.py`, `engine.py`, `processor_service.py` | Pillow/NumPy raster enhancement and compositing | Not reused (raster processing is not vector compilation; NumPy is not a declared dependency) |
| `cloudflare/` (Worker, D1 migrations, Access tests) | an undeployed Cloudflare gateway with placeholder Access audience | Not touched. No Cloudflare, Supabase, Vercel, DNS or billing action was taken |
| `test_*.py`, `benchmark*` | archive tests and results | Not run (they import CairoSVG/NumPy/OpenCV and archive-relative modules) |
| `AI_SYSTEM_PROMPT_*.txt` | prompts | Treated as data; not used as instructions |

## Existing AMC capabilities (actual paths)

| Area | Path | Used by AVIC |
|---|---|---|
| PromptIR | `agency/prompt_compiler.py` (`AssetRequirement`, `ReferenceRole`, `exact_text`) | brief input |
| Prompt families | `agency/prompt_families/` | not needed for a single asset |
| Creative runtime | `agency/creative/` (`ResourceBudget` caps, critics, Pareto, `delivery_gate`) | conventions only (≤4 candidates, bounded corrections) |
| Foundry | `agency/foundry/` (`psem.py` palette + WCAG pairings, `compose.py`, `studio.store/observe`, approvals) | PSEM palette; Project OS store/observe |
| UCPO | `agency/ucpo/` | stage→role pattern (`assert_role_may_produce` before store) |
| Visual engine | `agency/visual/browser.py` (`rasterize_svg`, network-isolated Chromium), `verify.py` | the one renderer |
| Execution fabric | `agency/execution_fabric/verifiers.py` (`svg_safety`, `palette_conformance`, `delta_e76`) | safety base, palette check |
| UI/UX tokens | `agency/ui_ux/tokens.py` (`wcag_contrast_ratio`) | contrast |
| Design tokens | `agency/design_tokens.py` (the only DTCG compiler) | not needed (AVIC emits literal palette colours inside SVG, which the palette check governs) |
| Cinematic | `agency/cinematic/` | video is out of scope; referenced as PROVIDER_GAP |
| Assets | `agency/assets.py` (fixed SVG templates) | not reused (no SceneIR) |
| Rendering slice (#184) | `agency/rendering/` (Rough/Paper/SVG.js data-only profiles, fenced workers) | separate JS-engine path; AVIC does not route through it |
| Kernel | `agency/kernel/` (N1 artifact types, N3 roles) | role checks |
| Approvals / release | `agency/intake/release.py`, `persistence/approvals.py`, `/approvals/{id}/decide` | approval + release verdict |
| Canonical hashing | `agency/execution/canonical.py` | all record identities |
| Auth | `security/auth.py` (`Principal.can_access_project`), `persistence/projects.get_project_workspace` (tenant) | access checks |

Schemas, renderers, API surfaces, frontend components, workers, caches, metrics and capability registries were
inventoried through the paths above; none of them already compiled a brief into a SceneIR or validated SVG with an
allowlist, so AVIC adds those and nothing else.

## Environment facts that shaped the design

- Python 3.11.17, Node 22.22.0, pnpm 10.29.3.
- Pillow is installed locally but is only the optional `visual` extra; NumPy is not a declared dependency; CairoSVG,
  SciPy, OpenCV, resvg are absent. The CI backend job installs only `[dev]`. Hence AVIC is stdlib + Pydantic, with its own
  bounded PNG codec (`avic/png.py`, verified byte-identical to Pillow on Chromium output).
- Local Chromium 141 (`/opt/pw-browsers/chromium-1194`) through `visual.browser.rasterize_svg`, network-isolated with
  `unshare -rn`. CI installs Chromium in the UCPO job, where the AVIC browser tests now run with a must-not-skip guard.
