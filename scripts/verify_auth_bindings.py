#!/usr/bin/env python3
"""Deterministic auth/hosting binding verifier (task node: auth-bind-check).

This validator answers one question only: *are the Supabase authentication and
Vercel hosting binding contracts structurally complete and fail-closed?*

It deliberately does NOT contact Supabase or Vercel and does NOT accept live
credentials. A verifier that needed real secrets could not run in CI, and
importing secrets into the repository is precisely the failure this gate
exists to prevent. Live binding remains an operator action performed in the
Supabase and Vercel dashboards; this gate proves the code is ready to receive
those values and refuses to let credentials be committed alongside it.

Failure semantics are BLOCK: any violation exits non-zero with the specific
contract that was broken.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Environment keys that must be *declared* in .env.example so an operator can
# see the full binding surface, and must be declared *empty* so no credential
# is ever carried in the repository.
SUPABASE_SECRET_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
)

# Credential shapes that must never appear in a tracked configuration file.
CREDENTIAL_PATTERNS = (
    (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\."), "JWT-shaped literal"),
    (re.compile(r"\bsb[ps]_[A-Za-z0-9_-]{20,}"), "Supabase key literal"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "OpenAI-style key literal"),
    (re.compile(r"\bpostgres(?:ql)?://[^\s\"']*:[^\s\"'@]+@"), "database URL with inline password"),
)


class BindingError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"auth-bind-check BLOCK: {message}")


def _read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise BindingError(f"required binding file is missing: {relative}")
    return path.read_text(encoding="utf-8")


def _env_declarations(text: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        declarations[key.strip()] = value.strip()
    return declarations


def check_env_contract() -> None:
    """.env.example must declare the full Supabase surface and hold no values."""
    declarations = _env_declarations(_read(".env.example"))

    for key in SUPABASE_SECRET_KEYS:
        if key not in declarations:
            raise BindingError(f".env.example does not declare {key}")
        if declarations[key]:
            raise BindingError(
                f".env.example assigns a value to {key}; credential values belong in the "
                "Vercel/Supabase dashboards, never in the repository"
            )

    # The auth mode selector must be present and must default to the safe mode.
    if declarations.get("AMC_AUTH_MODE") != "local":
        raise BindingError(".env.example must default AMC_AUTH_MODE to local")
    if declarations.get("AMC_ENV") != "local":
        raise BindingError(".env.example must default AMC_ENV to local")


def check_production_config_gate() -> None:
    """Production runtime must refuse to boot outside the supabase/postgres pair."""
    config = _read("services/langgraph/app/config.py")
    required_clauses = (
        ("AMC_AUTH_MODE must be supabase", "production must reject non-supabase auth modes"),
        ("AMC_DATABASE_BACKEND must be postgres", "production must reject non-postgres persistence"),
        ("SUPABASE_URL", "production must require SUPABASE_URL"),
        ("SUPABASE_PUBLISHABLE_KEY", "production must require SUPABASE_PUBLISHABLE_KEY"),
    )
    for token, explanation in required_clauses:
        if token not in config:
            raise BindingError(f"app/config.py missing production gate: {explanation}")


def check_tenant_binding_is_server_derived() -> None:
    """EC-001: tenant scope must come from the verified token, not client headers."""
    auth = _read("services/langgraph/security/auth.py")
    if "list_active_memberships" not in auth:
        raise BindingError(
            "auth.py must resolve tenant scope through server-side memberships, "
            "not through client-supplied identity"
        )
    if "_verify_supabase_user" not in auth:
        raise BindingError("auth.py must verify the bearer token against Supabase before trusting it")
    # A requested tenant may be *named* by a header, but it must be checked
    # against the membership set rather than accepted.
    if "outside authenticated membership scope" not in auth:
        raise BindingError(
            "auth.py must reject a requested tenant that falls outside the authenticated "
            "membership set (EC-001 tenant substitution)"
        )


def check_vercel_manifests() -> None:
    """Both deployment manifests must exist and be structurally coherent."""
    web = json.loads(_read("apps/web/vercel.json"))
    if web.get("framework") != "nextjs":
        raise BindingError("apps/web/vercel.json must declare the nextjs framework")

    api = json.loads(_read("services/langgraph/vercel.json"))
    functions = api.get("functions") or {}
    if "app/main.py" not in functions:
        raise BindingError("services/langgraph/vercel.json must declare the app/main.py function")

    entry = functions["app/main.py"]
    max_duration = entry.get("maxDuration")
    if not isinstance(max_duration, int) or max_duration <= 0:
        raise BindingError("services/langgraph/vercel.json must set a positive maxDuration")

    # EC-006: the synchronous pipeline is bounded by this number. If the manifest
    # ever drops below the observed synchronous envelope, the gate must fail
    # rather than let a gateway timeout surface as a corrupt half-run.
    if max_duration < 60:
        raise BindingError(
            f"services/langgraph/vercel.json maxDuration={max_duration}s is below the 60s "
            "synchronous pipeline envelope (EC-006 gateway timeout)"
        )

    excluded = entry.get("excludeFiles") or ""
    if "tests/**" not in excluded:
        raise BindingError("services/langgraph/vercel.json must exclude tests from the deployed bundle")

    if not api.get("rewrites"):
        raise BindingError("services/langgraph/vercel.json must route requests to the ASGI entrypoint")


def check_no_committed_credentials() -> None:
    """Stop rule: no credential-shaped literal in any tracked config surface."""
    surfaces = [
        ".env.example",
        "apps/web/vercel.json",
        "services/langgraph/vercel.json",
        "infra/cloudflare/wrangler.example.toml",
    ]
    for relative in surfaces:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, description in CREDENTIAL_PATTERNS:
            if pattern.search(text):
                raise BindingError(f"{relative} appears to contain a {description}")


def main() -> None:
    check_env_contract()
    check_production_config_gate()
    check_tenant_binding_is_server_derived()
    check_vercel_manifests()
    check_no_committed_credentials()
    print("auth-bind-check: Supabase and Vercel binding contracts verified (no live credentials required)")


if __name__ == "__main__":
    try:
        main()
    except BindingError as exc:
        print(str(exc), file=sys.stderr)
        raise
