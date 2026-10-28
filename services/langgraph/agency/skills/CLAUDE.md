# agency/skills

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Skill dispatcher — capability gating, not a plugin system yet

`agency/skills/dispatcher.py`: a `Skill` is registered once with the N3 `Capability` it requires; `dispatch_skill(role_id, skill_id, payload)` raises before the handler ever runs if the role's contract doesn't hold that capability. Authorization failures raise (`RoleContractError`/`SkillDispatchError`); handler-execution failures come back as a `SkillOutcome(status="FAILED")` rather than propagating, mirroring `GenerationOutcome`'s degraded-mode convention. Currently exactly one skill is registered (`zo_ask`, read-only, via `integrations/zo.py`). There is no AI image/audio *generation* in this codebase — `agency/assets.py`'s `render_logo_svg`/`render_background_pattern_svg`/`render_hero_svg` are fixed, deterministic SVG templates parameterized by brand color tokens. The one renderer is `services/freevideoforge/` (local, zero paid API, needs Pillow + FFmpeg), which the Project OS bridges by file contract rather than import (see below).
