from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from services.langgraph.core.constants import (
    AUTH_MODE_DISABLED,
    AUTH_MODE_SUPABASE,
    DB_BACKEND_POSTGRES,
    DB_BACKEND_SQLITE,
    ENV_LOCAL,
    ENV_PRODUCTION,
)

# Typed runtime configuration. Every module that needs to know how the
# process is configured should go through load_runtime_config() rather than
# reading os.environ directly, so validation logic lives in exactly one
# place. Sub-objects never hold secret values (API keys, DB URLs with
# embedded credentials) -- only presence booleans or already-public
# identifiers -- so a RuntimeConfig can be logged, repr()'d, or returned
# from /ready without leaking anything.

_DEFAULT_LOCAL_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def runtime_environment() -> str:
    return (_env("AMC_ENV") or ENV_LOCAL).lower()


def _normalize_origin(raw: str) -> tuple[str | None, str | None]:
    """Validate and normalize one CORS origin entry.

    Returns (normalized_origin, error) where exactly one is None.
    """
    if raw == "*":
        return None, "wildcard origin '*' is not allowed"

    parsed = urlsplit(raw)
    if parsed.scheme not in ("http", "https"):
        return None, f"origin '{raw}' must use the http or https scheme"
    if not parsed.hostname:
        return None, f"origin '{raw}' is missing a host"
    if parsed.username or parsed.password:
        return None, f"origin '{raw}' must not contain credentials"
    if parsed.path not in ("", "/"):
        return None, f"origin '{raw}' must not contain a path"
    if parsed.query:
        return None, f"origin '{raw}' must not contain a query string"
    if parsed.fragment:
        return None, f"origin '{raw}' must not contain a fragment"

    port_part = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port_part}", None


@dataclass(frozen=True)
class CorsConfig:
    allowed_origins: tuple[str, ...]
    errors: tuple[str, ...]


def _build_cors_config(environment: str) -> CorsConfig:
    raw = _env("AMC_CORS_ALLOWED_ORIGINS")
    if not raw:
        if environment == ENV_PRODUCTION:
            return CorsConfig(
                allowed_origins=(),
                errors=("AMC_CORS_ALLOWED_ORIGINS must be set to an explicit origin list",),
            )
        raw = ",".join(_DEFAULT_LOCAL_ORIGINS)

    errors: list[str] = []
    allowed: dict[str, None] = {}
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        normalized, error = _normalize_origin(candidate)
        if error is not None:
            errors.append(error)
            continue
        assert normalized is not None
        host = urlsplit(normalized).hostname or ""
        if environment == ENV_PRODUCTION and host in _LOOPBACK_HOSTS:
            errors.append(f"origin '{normalized}' is a loopback address, not allowed in production")
            continue
        if normalized in allowed:
            errors.append(f"origin '{normalized}' is a duplicate after normalization")
            continue
        allowed[normalized] = None

    if environment == ENV_PRODUCTION and not allowed:
        errors.append("AMC_CORS_ALLOWED_ORIGINS must contain at least one valid explicit origin")

    return CorsConfig(allowed_origins=tuple(allowed.keys()), errors=tuple(errors))


def _build_execution_config() -> ExecutionConfig:
    """Validate AMC_EXECUTION_MODE / AMC_ARTIFACT_BACKEND.

    ``inline`` executes the pipeline inside the HTTP request (local and CI
    default). ``background`` enqueues durable jobs executed by
    services/langgraph/runtime/worker.py, which is what production must use so
    run execution survives request and worker lifetimes.
    """
    mode = (_env("AMC_EXECUTION_MODE") or "inline").lower()
    if mode not in _VALID_EXECUTION_MODES:
        raise RuntimeError(f"Unsupported AMC_EXECUTION_MODE={mode!r}")
    backend = (_env("AMC_ARTIFACT_BACKEND") or "local").lower()
    if backend not in _VALID_ARTIFACT_BACKENDS:
        raise RuntimeError(f"Unsupported AMC_ARTIFACT_BACKEND={backend!r}")
    missing = tuple(name for name in _R2_REQUIRED_ENV if not _env(name))
    return ExecutionConfig(mode=mode, artifact_backend=backend, missing_r2_env=missing)


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    has_database_url: bool



@dataclass(frozen=True)
class AuthConfig:
    mode: str


@dataclass(frozen=True)
class ExecutionConfig:
    """Durable-execution and artifact-storage selection.

    Carries only the R2 credential *presence* flag, never the values, so the
    config stays safe to log or return from /ready.
    """

    mode: str
    artifact_backend: str
    missing_r2_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderConfig:
    has_supabase_url: bool
    has_supabase_publishable_key: bool


_VALID_EXECUTION_MODES = ("inline", "background")
_VALID_ARTIFACT_BACKENDS = ("local", "r2")
_R2_REQUIRED_ENV = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


@dataclass(frozen=True)
class PublicationConfig:
    mode: str


@dataclass(frozen=True)
class PaidMediaConfig:
    mode: str


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    cors: CorsConfig
    database: DatabaseConfig
    auth: AuthConfig
    providers: ProviderConfig
    publication: PublicationConfig
    paid_media: PaidMediaConfig
    execution: ExecutionConfig
    errors: tuple[str, ...]


def _production_errors(
    environment: str,
    cors: CorsConfig,
    database: DatabaseConfig,
    auth: AuthConfig,
    providers: ProviderConfig,
    publication: PublicationConfig,
    paid_media: PaidMediaConfig,
    execution: ExecutionConfig,
) -> list[str]:
    if environment != ENV_PRODUCTION:
        return []

    errors: list[str] = []
    if not database.has_database_url:
        errors.append("missing DATABASE_URL")
    if not providers.has_supabase_url:
        errors.append("missing SUPABASE_URL")
    if not providers.has_supabase_publishable_key:
        errors.append("missing SUPABASE_PUBLISHABLE_KEY")
    errors.extend(f"AMC_CORS_ALLOWED_ORIGINS: {error}" for error in cors.errors)
    if auth.mode != AUTH_MODE_SUPABASE:
        errors.append("AMC_AUTH_MODE must be supabase")
    if database.backend != DB_BACKEND_POSTGRES:
        errors.append("AMC_DATABASE_BACKEND must be postgres")
    if publication.mode not in {"disabled", "dry_run"}:
        errors.append("AMC_PUBLICATION_MODE cannot be live until a concrete provider adapter is installed")
    if paid_media.mode != "disabled":
        errors.append("AMC_PAID_MEDIA_MODE must remain disabled until a concrete provider adapter is installed")
    if (_env("AMC_CONTRACT_MODE") or "off").strip().lower() not in {"off", "shadow", "enforce"}:
        errors.append("AMC_CONTRACT_MODE must be off, shadow or enforce")
    if (_env("AMC_ALLOW_SELF_APPROVAL") or "").lower() in {"1", "true", "yes", "on"}:
        errors.append("AMC_ALLOW_SELF_APPROVAL must not be enabled in production")
    if (_env("AMC_OBJECT_STORAGE_BACKEND") or "local").lower() not in {"local"}:
        errors.append("AMC_OBJECT_STORAGE_BACKEND has no reviewed remote adapter; R2 stays fail-closed")
    # NOTE: the durable queue (persistence/jobs.py + runtime/worker.py) is in place, but the
    # agency create/resume routes still execute inline: they own trust-kernel policy records,
    # dispatch permits, pin/contract-seeded initial state and enforce_limits, none of which the
    # worker reproduces yet. Requiring "background" here would therefore force production onto the
    # degraded path, so the mode is validated but not mandated until the routes hand work to the
    # worker (follow-up PR). See services/langgraph/runtime/worker.py:_execute_create_job.
    if execution.artifact_backend == "r2" and execution.missing_r2_env:
        errors.append(f"AMC_ARTIFACT_BACKEND=r2 requires {', '.join(execution.missing_r2_env)}")
    return errors


def load_runtime_config() -> RuntimeConfig:
    """Parse the current process environment into a typed, validated config.

    Cheap enough to call on every request: it does no I/O, just os.environ
    reads and string validation. This is the single place that owns runtime
    configuration semantics; nothing here is cached across calls so tests
    that mutate os.environ (via monkeypatch) see immediate, correct results.
    """
    environment = runtime_environment()
    cors = _build_cors_config(environment)
    database = DatabaseConfig(
        backend=(_env("AMC_DATABASE_BACKEND") or DB_BACKEND_SQLITE).lower(),
        has_database_url=bool(_env("DATABASE_URL")),
    )
    auth = AuthConfig(mode=(_env("AMC_AUTH_MODE") or AUTH_MODE_DISABLED).lower())
    providers = ProviderConfig(
        has_supabase_url=bool(_env("SUPABASE_URL")),
        has_supabase_publishable_key=bool(_env("SUPABASE_PUBLISHABLE_KEY")),
    )
    publication = PublicationConfig(mode=(_env("AMC_PUBLICATION_MODE") or "disabled").lower())
    paid_media = PaidMediaConfig(mode=(_env("AMC_PAID_MEDIA_MODE") or "disabled").lower())
    execution = _build_execution_config()

    errors = _production_errors(
        environment, cors, database, auth, providers, publication, paid_media, execution
    )

    return RuntimeConfig(
        environment=environment,
        cors=cors,
        database=database,
        auth=auth,
        providers=providers,
        publication=publication,
        paid_media=paid_media,
        execution=execution,
        errors=tuple(errors),
    )


def production_config_errors() -> list[str]:
    return list(load_runtime_config().errors)


def assert_runtime_configuration() -> None:
    errors = production_config_errors()
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def execution_mode() -> str:
    """``inline`` (local/CI default) or ``background`` (durable queue, required in production)."""
    return load_runtime_config().execution.mode


def artifact_backend() -> str:
    """Where artifact bytes live: ``local`` filesystem directory or ``r2`` content-addressed store."""
    return load_runtime_config().execution.artifact_backend


def hmac_ingress_enabled() -> bool:
    return bool(_env("AMC_HMAC_SECRET"))


def worker_count() -> int:
    """Worker processes the server is configured to run (WEB_CONCURRENCY or UVICORN_WORKERS; default 1)."""
    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = (_env(name) or "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError as exc:
                raise RuntimeError(f"{name} must be an integer") from exc
    return 1


def hmac_replay_backend() -> str:
    """Nonce store for ASI07 replay protection. ``database`` (default) is shared across workers.

    ``memory`` is process-local and is refused when more than one worker is configured, because a
    replay could then succeed on a different worker. It exists for single-process development only.
    """
    value = (_env("AMC_HMAC_REPLAY_STORE") or "database").strip().lower()
    if value not in ("database", "memory"):
        raise RuntimeError("AMC_HMAC_REPLAY_STORE must be 'database' or 'memory'")
    if value == "memory" and worker_count() > 1:
        raise RuntimeError("AMC_HMAC_REPLAY_STORE=memory is refused with multiple workers; use 'database'")
    return value


def hmac_ingress_header_name() -> str:
    return _env("AMC_HMAC_HEADER") or "X-AMC-Signature"


def readiness_errors() -> list[str]:
    """Errors that should keep /ready from returning 200.

    Broader than production_config_errors(): CORS entries that fail to
    parse are a real misconfiguration worth surfacing in any environment,
    not just production, even though they aren't fatal outside production.
    """
    config = load_runtime_config()
    errors = list(config.errors)
    for cors_error in config.cors.errors:
        message = f"AMC_CORS_ALLOWED_ORIGINS: {cors_error}"
        if message not in errors:
            errors.append(message)
    return errors
