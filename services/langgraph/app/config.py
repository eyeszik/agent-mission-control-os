from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

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
    return (_env("AMC_ENV") or "local").lower()


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
        if environment == "production":
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
        if environment == "production" and host in _LOOPBACK_HOSTS:
            errors.append(f"origin '{normalized}' is a loopback address, not allowed in production")
            continue
        if normalized in allowed:
            errors.append(f"origin '{normalized}' is a duplicate after normalization")
            continue
        allowed[normalized] = None

    if environment == "production" and not allowed:
        errors.append("AMC_CORS_ALLOWED_ORIGINS must contain at least one valid explicit origin")

    return CorsConfig(allowed_origins=tuple(allowed.keys()), errors=tuple(errors))


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str
    has_database_url: bool


@dataclass(frozen=True)
class AuthConfig:
    mode: str


@dataclass(frozen=True)
class ProviderConfig:
    has_supabase_url: bool
    has_supabase_publishable_key: bool


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
    errors: tuple[str, ...]


def _production_errors(
    environment: str,
    cors: CorsConfig,
    database: DatabaseConfig,
    auth: AuthConfig,
    providers: ProviderConfig,
    publication: PublicationConfig,
    paid_media: PaidMediaConfig,
) -> list[str]:
    if environment != "production":
        return []

    errors: list[str] = []
    if not database.has_database_url:
        errors.append("missing DATABASE_URL")
    if not providers.has_supabase_url:
        errors.append("missing SUPABASE_URL")
    if not providers.has_supabase_publishable_key:
        errors.append("missing SUPABASE_PUBLISHABLE_KEY")
    errors.extend(f"AMC_CORS_ALLOWED_ORIGINS: {error}" for error in cors.errors)
    if auth.mode != "supabase":
        errors.append("AMC_AUTH_MODE must be supabase")
    if database.backend != "postgres":
        errors.append("AMC_DATABASE_BACKEND must be postgres")
    if publication.mode not in {"disabled", "dry_run"}:
        errors.append("AMC_PUBLICATION_MODE cannot be live until a concrete provider adapter is installed")
    if paid_media.mode != "disabled":
        errors.append("AMC_PAID_MEDIA_MODE must remain disabled until a concrete provider adapter is installed")
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
        backend=(_env("AMC_DATABASE_BACKEND") or "sqlite").lower(),
        has_database_url=bool(_env("DATABASE_URL")),
    )
    auth = AuthConfig(mode=(_env("AMC_AUTH_MODE") or "disabled").lower())
    providers = ProviderConfig(
        has_supabase_url=bool(_env("SUPABASE_URL")),
        has_supabase_publishable_key=bool(_env("SUPABASE_PUBLISHABLE_KEY")),
    )
    publication = PublicationConfig(mode=(_env("AMC_PUBLICATION_MODE") or "disabled").lower())
    paid_media = PaidMediaConfig(mode=(_env("AMC_PAID_MEDIA_MODE") or "disabled").lower())

    errors = _production_errors(environment, cors, database, auth, providers, publication, paid_media)

    return RuntimeConfig(
        environment=environment,
        cors=cors,
        database=database,
        auth=auth,
        providers=providers,
        publication=publication,
        paid_media=paid_media,
        errors=tuple(errors),
    )


def production_config_errors() -> list[str]:
    return list(load_runtime_config().errors)


def assert_runtime_configuration() -> None:
    errors = production_config_errors()
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def hmac_ingress_enabled() -> bool:
    return bool(_env("AMC_HMAC_SECRET"))


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
