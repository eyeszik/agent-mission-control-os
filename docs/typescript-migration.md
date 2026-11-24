# TypeScript migration plan

Status: **Waves 1 and 2 (core utilities and services) ported.** Twelve packages, from `@amc/canonical` to `@amc/vnexus-directions`, each reproduce a Python-generated parity fixture. No Python caller has been switched to them yet; Python is still the reference. Wave 3 has started with its pure security slice: `sanitize_deep` (`security/preprocess.py`) is twinned in `@amc/pii`. Persistence, API and the rest of `security` are blocked on the HTTP-runtime and database decisions below; nothing is invented ahead of them.

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

### Wave 2: services (pure compilers over Wave 1) — ported

Each area keeps its Python module as the reference. Only the pure computation moved; whatever touches the database, the filesystem, a browser, an image library or a subprocess stays in Python, and the twin takes that part's *result* as typed input.

| Python area | TS package | Parity cases | Stays in Python |
|---|---|---|---|
| `agency/design` | `@amc/design-mode` | ~500 | catalog file loading, `/design/*` routes |
| `agency/ui_ux` | `@amc/ui-ux` | ~15,900 (14,225 contrast pairs, 384 full compiles with identical `spec_hash`) | CLI, file I/O |
| `agency/vnexus` (core files) | `@amc/vnexus` | 6,723 | persistence, routes, approvals, imaging and video rendering, and everything that needs the foundry grammars or the prompt compiler |
| `agency/project_os` | `@amc/project-os` | 3,892 | file and disk operations, ffmpeg probe, the pipeline call |
| `agency/guidance` | `@amc/guidance` | ~380 (incl. the real registry hash) | pack file reading, CLI |
| `agency/prompt_families` | `@amc/prompt-families` | ~430 | role registry lookup |
| `agency/compiled` | `@amc/compiled` | 7,303 | archive/zip reads, the scenario harness, persistence-row adapters |
| `agency/vnexus/brandbook` | `@amc/vnexus-brandbook` | ~5,000 | authorization, storage, release, Chromium measurement and PDF render |
| `agency/vnexus/directions` | `@amc/vnexus-directions` | ~2,000 | PNG/Chromium/SVG image analysis, Lab distance, persistence, approvals, freeze flow |

Two things in this wave are stubbed in a fixture rather than exercised with real code: `@amc/vnexus-directions` replays a recorded `compile_genome_prompt` result and a recorded `scan_forms` verdict per text. They need the foundry and prompt-compiler ports first.

Fail-closed rules carried over as literals, not configuration: `spend_authority_granted` and `execution_available` are `false`, a video QC result is never `PASS`, `allow_paid` is `false`, the live publication provider registry is private and empty, and a UI/UX request with no compiler adapter raises instead of returning a result.

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

## What Wave 2 added

Everything under "What Wave 1 taught" held. New findings:

- **Hash floats and cross-instance identity.** Anything that reaches a hash must build floats through `pyFloat` / `CanonicalFloat`, and test them with `isPyFloat`. Under vitest the workspace package loaded from `src` and from a dependency's `dist` are two module graphs, so `instanceof CanonicalFloat` can fail across them. `@amc/design-tokens` re-exports one shared marker, and packages that inline workspace deps (`@amc/vnexus-directions` has a `vitest.config.ts` for this) must adopt a foreign instance.
- **`pow`, `log` and `cbrt` differ from glibc in the last bit.** About 12% of sRGB linearisations, 9% of cube roots and 7% of logs differ by one ulp. Fixes in use: a Python-generated table (the 256 sRGB values), a double-double cube root, and a correctly rounded `log` computed in 128-bit fixed point. When a quantity cannot be tabled (Lab `t ** (1/3)`), it stays in Python and the twin takes the result as input.
- **Object key order.** JS puts integer-like keys first. Use `Map`, or an explicit order array, wherever order is observable (for example lens keys `'10'`–`'14'` sorting before `'01'`).
- **`datetime.fromisoformat` on CPython 3.11 is not the documented grammar.** The C parser accepts junk between seconds and an offset, and the error message embeds a `timedelta` repr. Twins either follow the C implementation (`@amc/project-os`) or take a strict subset and fail closed (`@amc/compiled`).
- **Pydantic validators only run when field constraints hold**, and errors come in input-key order, then missing fields. Zod `superRefine` runs anyway, so rules need an explicit guard. Error text embeds a version and a docs URL, so compare each issue's location and type, plus the exact message only for custom `value_error`s.
- **`model_dump(mode="json")` turns NaN and Infinity inside `Any` values into `null`.** This changed a registry hash until the twin did the same.
- **`str.strip`, `rstrip` and friends: use a linear scan, not a regex.** CodeQL flags `/-+$/` and `/\/+$/` as polynomial-time regular expressions. They were not exploitable here, but `stripChar` in `packages/project-os/src/pytext.ts` is the same operation without the alert.
- **Hash-seed independence.** A fixture builder that iterates a Python `set` varies with `PYTHONHASHSEED`. Iterate `sorted(...)`, and run each fixture-owner test under more than one seed.
- **Fixture size.** Keep each fixture near 3 MB. A large domain is split across files (`@amc/ui-ux` uses four), with a full dump stored only for a sample and a digest for the rest.
- **Python bugs are mirrored on purpose** and recorded as fixture cases (for example a `KeyError` while hashing a page, an `IndexError` on an empty list). A twin never quietly fixes its reference; the fix goes into Python first, then the fixture is regenerated.

## Rules for every wave

- **Proof, not authority.** A matching hash shows two implementations agree; it doesn't approve or release anything. The fail-closed rules (publish, spend and send disabled; providers DISABLED) carry over unchanged into TypeScript.
- **Never weaken tests or gates to get to green.** Never refresh unrelated `manifest.json` hashes. A new TS file that guards an authorization boundary gets added to the tracked set when its Python twin is retired.
- **No silent divergence.** Every type or encoding the languages represent differently gets an explicit wrapper or an explicit refusal, plus a fixture case.
- **Switching callers is a separate PR from the port**, so it can be reverted on its own.
