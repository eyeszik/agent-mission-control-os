# TypeScript migration plan

Status: **plan + pilot.** The pilot (`@amc/canonical`) has landed. No backend module has been switched over to it, and nothing in this plan is active until a wave is started on purpose.

## Why not a big-bang port

The Python backend is about 90k lines of application code plus 27k lines of tests. CI runs those tests on SQLite and on PostgreSQL. A parallel rewrite of all of it at once would:

- break the seven verifier gates, which read Python source;
- break the 288 `manifest.json` hash pins;
- break the recorded Zod/Pydantic fixtures;
- leave the backend split across two languages, with nothing proving the halves agree.

The approach here is a **strangler**, done one module at a time, in this order:

1. Each module gets a TypeScript twin.
2. A **Python-generated parity fixture** proves the twin byte-for-byte.
3. Only after that does any caller switch over.

Python stays the reference until a module's callers have all moved.

## The pattern (proven by the pilot)

| Step | Pilot instance |
|---|---|
| 1. Pick a leaf module with no internal deps and many callers | `agency/execution/canonical.py`: 0 internal deps, imported by 93 backend modules |
| 2. A Python test owns a fixture of tagged inputs → expected bytes/hash, regenerated with `AMC_REGENERATE_FIXTURES=1` | `services/langgraph/tests/test_canonical_parity_fixture.py` → `packages/canonical/tests/fixtures/amc-canon-1.json` (525 cases + error and manifest cases) |
| 3. The TS twin lives in a tier-1 workspace package, with explicit types, no `any`, and functions of 20 lines or fewer | `packages/canonical/src/index.ts` |
| 4. A vitest suite reproduces every fixture entry and rejects every input Python rejects | `packages/canonical/tests/parity.test.ts` |
| 5. Confirm the suite fails when the twin is wrong | Two mutations were tried: UTF-16 key order and dropping leading zeros in decimals. Each failed the suite. |
| 6. Document every place the languages can't agree, and fail closed there rather than guessing | See the `@amc/canonical` header comment |

CI picks up a new package automatically, because it builds, typechecks and tests `./packages/*`. The Python half of the fixture runs in the normal backend suite, on SQLite and on Postgres. If someone changes `canonical.py` without regenerating the fixture, the Python test fails first.

Differences the pilot found, and that later waves will meet again:

- **Integers vs floats.** A JS `number` can't record whether it was an int or a float. Integral numbers encode as ints. An integral float must be wrapped in `CanonicalFloat`. Unsafe integers must be passed as `bigint` and are refused otherwise.
- **Map key order.** Mapping keys sort by UTF-8 bytes, not by JS's default UTF-16 order. The two orders differ for astral characters compared with characters at or above U+E000.
- **Lone surrogates.** These are refused. `TextEncoder` would otherwise silently replace them with U+FFFD. Some JSON parsers (Vite's) refuse them outright, so the fixture carries them as a `$utf16` tag.
- **Float text.** Python's `Decimal` formatting is rebuilt from `Number#toExponential()`, which gives the shortest round-trip digits as `repr` does. The 300 random-float cases cover this, including subnormal and boundary values.

## Order of work

There are three waves: core utilities, then services, then components. Inside a wave, modules don't depend on each other, so they can be ported **in parallel and independently**. Each one gets its own PR and its own parity fixture. Dependencies come from the backend's internal import graph, counted as numbers of other areas.

### Wave 1: core utilities (leaves, pure)

| Module | Lines | Internal deps | Used by | Notes |
|---|---|---|---|---|
| `agency/execution/canonical.py` | 90 | 0 | 93 modules | **Done (pilot)** → `@amc/canonical` |
| rest of `agency/execution` | ~240 | 0 | 17 areas | Pydantic records → Zod twins already exist for the API-visible ones; uses `@amc/canonical` |
| `agency/kernel` (N1–N4) | 1,761 | 0 | 12 areas | Zod twins exist and `verify_ontology_parity.py` enforces them; port the lifecycle guards (`release_guard_failures`) with a transition-matrix parity fixture |
| `agency/design_tokens` | 472 | 0 | 6 areas | No external deps; DTCG output can be compared byte-for-byte |
| `agency/assets` | 89 | 0 | 5 areas | |
| `core` | 329 | 0 | 6 areas | Already mirrored by `@amc/{errors,config,constants,logger}`; just keep `test_core.py` in step |

### Wave 2: services (pure compilers over Wave 1)

Each of these needs only Wave 1:

- `agency/compiled` (6,074 lines)
- `agency/project_os` (3,172)
- `agency/guidance`
- `agency/prompt_families`
- `agency/design`
- `agency/ui_ux`
- the pure parts of `agency/vnexus`: the genome, the brand book compiler and the directions review board

They are deterministic compilers, so a fixture of recorded inputs and outputs makes a complete parity proof. Persistence calls stay behind an interface that is still answered by Python over the existing API.

### Wave 3: components (I/O edges)

These come last, and only once Waves 1 and 2 are complete:

- `persistence` (10,272 lines, used by 21 areas);
- `api` (7,296 lines, FastAPI);
- `security`.

Moving them means a new HTTP runtime, and either a Postgres driver plus a SQLite story or a Postgres-only decision. It also means re-pointing `verify_auth_bindings.py` and `verify_production_readiness.py`. Those gates grep literal strings in Python source, so each must gain a TypeScript equivalent *before* its Python source is deleted. Weakening a gate is never the fix.

## What stays in Python, and why

| Area | Reason |
|---|---|
| `agency/council` (CrewAI, AutoGen, LangGraph engines) | CrewAI and AutoGen are Python-only. A TS port would mean dropping two of the three engines. |
| LangGraph execution pipeline and checkpoints (`graph/agency`, `persistence/checkpoints.py`) | Checkpoint blobs are written in LangGraph-Python's serializer format. LangGraph.js can't resume them, so existing runs would be stranded. |
| `agency/visual` R-renderers using `bpy`, and FreeVideoForge | Blender's Python API, plus Pillow/FFmpeg pipelines with no drop-in TS equivalent |
| `agency/execution_fabric` code sandbox | Runs Python code by design |
| Verifier gates (`scripts/verify_*.py`) | They are the CI contract. They move only once each has a TS twin that is proven equivalent. |

So the realistic end state is a **TypeScript core and services behind the existing API, with a Python worker tier** for the areas above. It is not a backend with no Python in it.

## Rules for every wave

- **Proof, not authority.** A matching hash shows two implementations agree; it doesn't approve or release anything. The fail-closed rules (publish, spend and send disabled; providers DISABLED) carry over unchanged into TypeScript.
- **Never weaken tests or gates to get to green.** Never refresh unrelated `manifest.json` hashes. A new TS file that guards an authorization boundary gets added to the tracked set when its Python twin is retired.
- **No silent divergence.** Every type or encoding the languages represent differently gets an explicit wrapper or an explicit refusal, plus a fixture case.
- **Switching callers is a separate PR from the port**, so it can be reverted on its own.
