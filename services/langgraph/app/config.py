from __future__ import annotations

import os


def runtime_environment() -> str:
    return (os.environ.get("AMC_ENV") or "local").strip().lower()


_VALID_EXECUTION_MODES = {"inline", "background"}
_VALID_DATABASE_BACKENDS = {"sqlite", "postgres"}
_VALID_ARTIFACT_BACKENDS = {"local", "r2"}


def execution_mode() -> str:
    """inline: pipeline executes inside the HTTP request (local/CI default).
    background: runs enqueue durable jobs executed by runtime/worker.py."""

    value = (os.environ.get("AMC_EXECUTION_MODE") or "inline").strip().lower()
    if value not in _VALID_EXECUTION_MODES:
        raise RuntimeError(f"Unsupported AMC_EXECUTION_MODE={value!r}")
    return value


def artifact_backend() -> str:
    value = (os.environ.get("AMC_ARTIFACT_BACKEND") or "local").strip().lower()
    if value not in _VALID_ARTIFACT_BACKENDS:
        raise RuntimeError(f"Unsupported AMC_ARTIFACT_BACKEND={value!r}")
    return value


def production_config_errors() -> list[str]:
    if runtime_environment() != "production":
        return []
    errors: list[str] = []
    required_values = [
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "AMC_CORS_ALLOWED_ORIGINS",
    ]
    for name in required_values:
        if not (os.environ.get(name) or "").strip():
            errors.append(f"missing {name}")
    if (os.environ.get("AMC_AUTH_MODE") or "").strip().lower() != "supabase":
        errors.append("AMC_AUTH_MODE must be supabase")
    if (os.environ.get("AMC_DATABASE_BACKEND") or "").strip().lower() != "postgres":
        errors.append("AMC_DATABASE_BACKEND must be postgres")
    origins = (os.environ.get("AMC_CORS_ALLOWED_ORIGINS") or "").lower()
    if "*" in origins or "localhost" in origins or "127.0.0.1" in origins:
        errors.append("production CORS origins must be explicit non-loopback origins")
    if (os.environ.get("AMC_PUBLICATION_MODE") or "disabled").strip().lower() not in {"disabled", "dry_run"}:
        errors.append("AMC_PUBLICATION_MODE cannot be live until a concrete provider adapter is installed")
    if (os.environ.get("AMC_PAID_MEDIA_MODE") or "disabled").strip().lower() != "disabled":
        errors.append("AMC_PAID_MEDIA_MODE must remain disabled until a concrete provider adapter is installed")
    if execution_mode() != "background":
        errors.append("AMC_EXECUTION_MODE must be background in production so run execution survives request/worker lifetimes")
    if (os.environ.get("AMC_ARTIFACT_BACKEND") or "local").strip().lower() == "r2":
        for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
            if not (os.environ.get(name) or "").strip():
                errors.append(f"AMC_ARTIFACT_BACKEND=r2 requires {name}")
    return errors


def assert_runtime_configuration() -> None:
    errors = production_config_errors()
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))
