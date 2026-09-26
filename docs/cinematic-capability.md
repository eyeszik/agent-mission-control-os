# Cinematic generative capability

`services/langgraph/agency/cinematic/` is a lazily-loaded domain capability that
compiles rough ideas, scripts, storyboards, and images into production-grade
prompts for text-to-image, text-to-video, image-to-video, storyboards, and
brand motion — while preserving story, character identity, continuity, camera
logic, lighting, physics, brand behaviour, and user constraints.

It is a sibling of the prompt compiler, not part of it, and it honours the same
boundary: **it compiles validated prompts and never invokes a media provider,
writes a generated frame, or performs any external creative side effect.** Its
terminal state is `PROMPT_PACKAGE_READY` (`GENERATION_FIREWALL`).

## Why it is a native module, not a guidance pack

Guidance packs (`agency/guidance/packs/*.yaml`) are advisory prose that *shapes*
how the prompt compiler runs; they carry no executable behaviour. This
capability needs real schemas validated against fixtures, compilers that consume
a canonical shot representation, an evaluator that produces scores, and a bounded
repair loop — so it is implemented as a cohesive Python module under `agency/`,
the repository's native place for domain logic (alongside `prompt_compiler.py`
and the kernel). The full specification lives here only; it is intentionally
kept out of `CLAUDE.md` / `AGENTS.md` / `README.md`, which carry only a short
routing pointer.

## Runtime flow

```
input → router → cinematic capability → PROJECT/SHOT IR → production reasoning
      → target compiler → model adapter → evaluator → local repair
      → prompt compression → final output
```

- **Router** (`router.py`) — deterministic, declarative trigger metadata decides
  whether a request is cinematic. It does not hijack coding, writing, or plain
  still-image requests. Capability/audit/system-design/workflow requests are
  recognised as non-generative and return a capability manifest instead of an
  invented scene.
- **IR** (`schemas.py`) — `ProjectIR` and `ShotIR` are the single canonical
  representations. Every compiler consumes `ShotIR`; none rebuilds project
  context on its own. The IR is always richer than the final prompt.
- **Production reasoning** — source authority (`authority.py`), continuity
  packets and the end-state→start-state handshake (`continuity.py`), camera
  validation and 3D-scene path checks (`camera.py`), lighting/material coupling
  and physics causality (`render.py`), story/performance (`story.py`),
  storyboards (`storyboard.py`), brand motion (`motion.py`).
- **Compilers** (`compilers.py`) — `compile_t2i`, `compile_t2v`, `compile_i2v`,
  targeted failure-prevention, and entropy control (never drops a protected
  dimension: who, where, what changes, camera, light, continuity, end state).
- **Adapters** (`adapters.py`) — known models are shaped into their dialect;
  unknown models get the portable natural-language prompt. Capabilities are
  never fabricated; unsupported hard constraints are surfaced, not dropped. The
  `/use-after-effects` prefix is legacy metadata only and is never emitted by
  default.
- **Evaluator + repair** (`evaluation.py`) — structured scores, failed
  requirements, and repair targets; local repair is bounded to
  `MAX_REPAIR_CYCLES` (3) and only touches the failed dimension.

## Invocation

CLI (compiles prompts, generates nothing):

```bash
python3 orchestrate_brand_pipeline.py cinematic --text "A woman waits alone for the last train in the rain."
python3 orchestrate_brand_pipeline.py cinematic --input sample_cinematic_request.json
```

Python:

```python
from services.langgraph.agency.cinematic import run_pipeline
from services.langgraph.agency.cinematic.schemas import CinematicRequest, InputMode

result = run_pipeline(CinematicRequest(text="text to video of a man walking through a market",
                                       mode=InputMode.video_package))
print(result.prompts[0].prompt)
```

## Supported inputs and outputs

- **Input forms**: idea, script, treatment, dialogue, image, moodboard,
  storyboard panel, character, location, brand, product, campaign, scene,
  reference.
- **Modes**: capability, audit, system_design, workflow, development, character,
  storyboard, video_package, prompts_only, revision, brand, automation. The
  first four are non-generative.
- **Targets**: T2I, T2V, I2V, storyboard, motion.

## Adding a model adapter

Construct a `ModelProfile` (`schemas.py`) describing the target generator's real
capabilities and limitations, then pass it on the `CinematicRequest`
(`model_profile=...`). `adapters.adapt()` shapes each compiled prompt for that
profile. Never list a capability the generator does not have; unsupported
requirements are reported in `CompiledPrompt.unsupported_requirements`.

## Interpreting results

`PipelineResult` carries `prompts`, `storyboard`, per-shot `evaluations`
(scores + failed requirements + repair targets), `repair_log`, and `unresolved`
(unknown-critical facts and source conflicts surfaced as focused questions —
never silently resolved). `requires_human_review()` is true when there are
unresolved conflicts or unknown-critical facts.

## Tests

```bash
python -m pytest services/langgraph/tests/test_cinematic.py -q
```

The suite includes the named regression fixtures A–J (simple T2V, character
continuity, storyboard generation, storyboard-to-video, image-to-video, entropy
control, conflicting sources, brand motion, capability-only, unknown model) plus
focused unit tests for routing discipline, camera validation, and bounded
repair.
