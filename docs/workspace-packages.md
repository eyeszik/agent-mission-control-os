# Workspace packages and the backend core

The repository has two stacks: TypeScript (`apps/web`, `packages/*`) and Python (`services/langgraph`).

Both stacks share the same **semantics**, meaning the same vocabularies, error codes and envelope, and config and logging conventions. They do **not** share code. No Python module imports TypeScript and no TypeScript module imports Python. A backend test (`tests/test_core.py`) reads `packages/constants/src/index.ts` and fails if the two vocabularies drift apart.

## TypeScript tier-1 packages (`packages/*`)

| Package | Purpose | Internal deps |
| --- | --- | --- |
| `@amc/constants` | Vocabularies: environments, auth modes, database backends, log levels, approver roles, agency run states, `isOneOf` | — |
| `@amc/errors` | `AMCError` base class, typed subclasses, the JSON envelope, and response mapping | — |
| `@amc/logger` | `Logger` interface, `ConsoleLogger` with secret redaction, `createLogger` | constants |
| `@amc/config` | Zod-validated `loadConfig` and typed `loadAppConfig` | constants, errors |
| `@amc/db` | `DbConfig`/`DbClient`/`DbTransaction`, `createDbClient`, `withTransaction`, `requireTx` | constants, errors |
| `@amc/testing` | `createTestContext`, `createMockResponse`, `setupVitestHooks` (ES module; test-only) | config, logger, constants |

The `@amc/errors` subclasses are `ValidationError` (422), `UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404) and `ConflictError` (409). Its helpers are `isAMCError`, `ensureValid`, `toErrorEnvelope` and `errorFromResponse`.

**Conventions:**

- Each package has `package.json`, `tsconfig.json` (typecheck for `src` plus `tests`), `tsconfig.build.json` (emits `src` to `dist`), `src/index.ts` and `tests/`.
- Each package has `build`, `typecheck` and `test` scripts.
- Internal dependencies use `workspace:*`.
- Every config extends the root `tsconfig.base.json`, which is TypeScript 5.x with `module`/`moduleResolution` `Node16` (no deprecated `node`/`node10` resolution).
- Output is CommonJS, except `@amc/testing`. That package imports the ESM-only Vitest, so it is `"type": "module"`.

**Build:**

```bash
pnpm --filter "./packages/*" build        # dependency order is automatic
pnpm --filter "./packages/*" typecheck
pnpm --filter "./packages/*" test
```

`pnpm-workspace.yaml` is authoritative for pnpm. The root `package.json` `workspaces` field mirrors it for tools that read that field.

### How `apps/web` uses them

| Package | Where it is used |
| --- | --- |
| `@amc/config` | `lib/config.ts` (`getAppConfig`, `usesSupabaseAuth`). It reads each `NEXT_PUBLIC_*` variable as a literal `process.env` expression, because Next.js only inlines public values into browser bundles at literal references. The loader takes that explicit record and never reads `process.env` itself. |
| `@amc/logger` | `lib/logger.ts` (`getLogger`, level from `NEXT_PUBLIC_LOG_LEVEL`). Used by the SSE client and the mission-control components that previously called `console.*`. |
| `@amc/errors` | `ServiceError` in `lib/api/client.ts` now extends `AMCError`. Its constructor is unchanged. `apiFetch` reads both FastAPI `{ detail }` bodies and the AMC envelope. |
| `@amc/constants` | Auth-mode comparison. A web test checks the run states against `@amc/shared`'s `AgencyRunStatusSchema`. |
| `@amc/testing` | Web tests (dev dependency only). |

`@amc/db` is not used by the web app: all persistence lives in the Python backend. It defines the contract for a future TypeScript service, and the caller supplies the driver.

## Python core (`services/langgraph/core`)

| Module | Contents |
| --- | --- |
| `constants.py` | `AMC_ENVIRONMENTS`, `AMC_AUTH_MODES`, `AMC_DATABASE_BACKENDS`, `AMC_LOG_LEVELS`, `AMC_APPROVER_ROLES`, `AMC_AGENCY_RUN_STATES`, and named constants (`AUTH_MODE_SUPABASE`, `DB_BACKEND_POSTGRES`, …). It has no dependencies. |
| `errors.py` | See below. |
| `config.py` | `AppConfig` dataclass, `load_runtime_config` (re-exported), `load_app_config`, `get_logger`, `parse_log_level`. |

**`errors.py`:**

- `AMCError` subclasses FastAPI's `HTTPException`. The subclasses are `ValidationError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError` and `ConflictError`.
- `ErrorEnvelope` and `error_envelope` build the response body, `ensure_valid` raises on a failed condition, and `register_error_handlers(app)` installs the handler.
- Raising an `AMCError` works with or without the handler. With it (registered in `app/main.py`) the body is `{"detail", "error": {...}}`. Plain `HTTPException`s keep FastAPI's `{"detail"}` body.

**`config.py`:**

- `app/config.py` remains the **single owner** of runtime configuration and the production gates.
- `AppConfig` is a typed view over it, plus approver roles and log level. `core.config` imports `app.config` lazily, because `app.config` itself imports `core.constants`.
- `get_logger(name)` sets a level only when `AMC_LOG_LEVEL` is set. Otherwise logging behaves exactly as before.

**Adopted by:**

- `app/config.py`: environment, auth mode and database backend values. The production-gate error strings the CI verifiers grep for are unchanged.
- `security/auth.py`: auth modes.
- `security/approval_authority.py`: default approver roles and the local environment.
- `persistence/database.py`: database backends.
- The four modules that used `logging.getLogger(__name__)`.
