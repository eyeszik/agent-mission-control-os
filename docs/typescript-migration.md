# TypeScript migration plan

Status: **Wave 1 (core utilities) ported.** `@amc/canonical`, `@amc/execution`, `@amc/kernel`, `@amc/design-tokens`, `@amc/assets` and `@amc/pii` each reproduce a Python-generated parity fixture. No Python caller has been switched to them yet; Python is still the reference.

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
| `agency/execution/canonical.py` | 90 | 0 | 93 modules | **Ported** → `@amc/canonical` (525 cases) |
| `agency/execution/models.py` | 239 | 0 | 17 areas | **Ported** → `@amc/execution`, strict Zod schemas (312 cases) |
| `agency/kernel` (N1–N4) | 1,761 | 0 | 12 areas | **Ported** → `@amc/kernel`: guards, roles, registry and merge matrix (6,683 cases) |
| `agency/design_tokens.py` | 472 | 0 | 6 areas | **Ported** → `@amc/design-tokens`; the real `amc.tokens.json` compiles to identical CSS (1,176 cases) |
| `agency/assets.py` | 89 | 0 | 5 areas | **Ported** → `@amc/assets` (364 render cases) |
| `security/pii.py`, `security/sanitize.py` | 131 | 0 | redaction callers | **Ported** → `@amc/pii` (1,933 cases); never more permissive than Python |
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

## What Wave 1 taught (applies to every later wave)

- **Read JSON the way Python does.** `JSON.parse` loses `1.0` vs `1`, and that changes hashes. The real `amc.tokens.json` is a concrete case. `@amc/design-tokens` exports `parseTokenJson`, which keeps the distinction; it needs JSON.parse source-text access, available on Node 21+ (CI pins 22.12). Every package uses `CanonicalFloat` from `@amc/canonical` as the one float marker.
- **Pydantic lax mode is the main source of divergence.** Python accepts `"2"` for an int, `"yes"` for a bool and unix timestamps for datetimes. The TS twins refuse these, and each fixture records them as explicit "Python accepts, TS refuses" cases, so the gap is visible rather than silent.
- **Python's text formatting has to be rebuilt.** `repr(float)` switches to exponent form outside [1e-4, 1e16), while JS does so outside [1e-6, 1e21). `round()` and `f"{x:.4f}"` round half to even on the exact binary value, while `toFixed` rounds ties up. `json.dumps` defaults to `ensure_ascii`. Error messages embed `repr()`. Each package has a small `python*.ts` helper for these.
- **Regex and Unicode.** JS `\w`, `\d` and `\b` are ASCII-only. JS `\s` and Python's whitespace sets differ (U+FEFF, U+001C–U+001F, U+0085). JS `.` also stops at `\r`, U+2028 and U+2029. Python's IGNORECASE matches `İ`, `ı`, `ſ` and K where the JS `i` flag does not. Python's `$` matches before a trailing `\n`. `@amc/pii` and `@amc/assets` use Python-generated Unicode tables (`src/python-unicode.ts`, owned by their parity tests), so the JS engine's Unicode version never decides a match.
- **Sorting and key order.** Sort by code point or UTF-8 bytes, never by JS's default UTF-16 order. JS objects move integer-like keys first, so use `Map` wherever order is observable.
- **Hashing stays synchronous.** Web Crypto only digests asynchronously, but Python's `commit()` and token hashing are synchronous, so `@amc/kernel` and `@amc/design-tokens` bundle a small synchronous SHA-256, checked against the standard test vectors.
- **Ports find real bugs.** Mirroring `security/pii.py` exactly showed that its credential patterns ended in a raw-string `\\b`, a literal backslash followed by `b`, so GitHub tokens were **not detected**. The TS twin mirrored this faithfully, since a twin must not quietly fix its reference. The fix landed in Python first, then the fixture was regenerated and the twin updated.

## Rules for every wave

- **Proof, not authority.** A matching hash shows two implementations agree; it doesn't approve or release anything. The fail-closed rules (publish, spend and send disabled; providers DISABLED) carry over unchanged into TypeScript.
- **Never weaken tests or gates to get to green.** Never refresh unrelated `manifest.json` hashes. A new TS file that guards an authorization boundary gets added to the tracked set when its Python twin is retired.
- **No silent divergence.** Every type or encoding the languages represent differently gets an explicit wrapper or an explicit refusal, plus a fixture case.
- **Switching callers is a separate PR from the port**, so it can be reverted on its own.
