from __future__ import annotations

import os


def runtime_environment() -> str:
    return (os.environ.get("AMC_ENV") or "local").strip().lower()


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
    return errors


def assert_runtime_configuration() -> None:
    errors = production_config_errors()
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def hmac_ingress_enabled() -> bool:
    return bool((os.environ.get("AMC_HMAC_SECRET") or "").strip())


def hmac_ingress_header_name() -> str:
    return (os.environ.get("AMC_HMAC_HEADER") or "X-AMC-Signature").strip()
