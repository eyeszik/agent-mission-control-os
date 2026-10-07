"""services.langgraph.core: constants, errors and config, and parity with the
TypeScript @amc/constants package (checked by reading its source; the stacks
never import each other at runtime)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.langgraph.core import constants as C
from services.langgraph.core.config import get_logger, load_app_config, parse_log_level
from services.langgraph.core.errors import (
    AMCError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
    ensure_valid,
    error_envelope,
    register_error_handlers,
)
from services.langgraph.persistence.database import database_backend
from services.langgraph.security.approval_authority import DEFAULT_APPROVER_ROLES

TS_CONSTANTS = Path(__file__).resolve().parents[3] / "packages" / "constants" / "src" / "index.ts"


def _ts_tuple(name: str) -> tuple[str, ...]:
    match = re.search(rf"export const {name} = \[([^\]]*)\] as const", TS_CONSTANTS.read_text(encoding="utf-8"))
    assert match, f"{name} not found in {TS_CONSTANTS}"
    return tuple(re.findall(r"'([^']*)'", match.group(1)))


@pytest.mark.parametrize("name", [
    "AMC_ENVIRONMENTS", "AMC_AUTH_MODES", "AMC_DATABASE_BACKENDS", "AMC_LOG_LEVELS",
    "AMC_APPROVER_ROLES", "AMC_AGENCY_RUN_STATES",
])
def test_python_and_typescript_constants_agree(name):
    assert getattr(C, name) == _ts_tuple(name)


def test_existing_modules_use_the_core_vocabulary(monkeypatch):
    assert DEFAULT_APPROVER_ROLES == frozenset(C.AMC_APPROVER_ROLES)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "mysql")
    with pytest.raises(RuntimeError, match="Unsupported AMC_DATABASE_BACKEND"):
        database_backend()


@pytest.mark.parametrize("cls,code,status", [
    (ValidationError, "VALIDATION_FAILED", 422),
    (UnauthorizedError, "UNAUTHORIZED", 401),
    (ForbiddenError, "FORBIDDEN", 403),
    (NotFoundError, "NOT_FOUND", 404),
    (ConflictError, "CONFLICT", 409),
])
def test_error_codes_and_statuses(cls, code, status):
    error = cls()
    assert isinstance(error, AMCError)
    assert (error.code, error.status, error.status_code, error.detail) == (code, status, status, error.message)


def test_envelope_and_ensure_valid():
    error = NotFoundError("Run not found", details={"run_id": "r1"})
    assert error.to_envelope() == {
        "detail": "Run not found",
        "error": {"code": "NOT_FOUND", "message": "Run not found", "status": 404, "details": {"run_id": "r1"}},
    }
    assert error_envelope(RuntimeError("password=hunter2"))["error"] == {"code": "AMC_ERROR", "message": "Internal error", "status": 500}
    with pytest.raises(ValidationError) as raised:
        ensure_valid(False, "name is required", field="name")
    assert raised.value.details == {"field": "name"}
    ensure_valid(True, "fine")


def test_fastapi_renders_the_envelope_and_keeps_plain_http_exceptions():
    from fastapi import HTTPException

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/amc")
    def amc():
        raise ConflictError("Approval is stale", code="APPROVAL_STALE")

    @app.get("/plain")
    def plain():
        raise HTTPException(status_code=404, detail="missing")

    client = TestClient(app)
    response = client.get("/amc")
    assert response.status_code == 409
    assert response.json() == {"detail": "Approval is stale", "error": {"code": "APPROVAL_STALE", "message": "Approval is stale", "status": 409}}
    assert client.get("/plain").json() == {"detail": "missing"}


def test_the_service_app_registers_the_handler():
    from services.langgraph.app.main import app

    assert AMCError in app.exception_handlers


def test_app_config_is_a_view_over_runtime_config(monkeypatch):
    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_APPROVER_ROLES", "Owner, reviewer")
    monkeypatch.setenv("AMC_LOG_LEVEL", "WARNING")
    config = load_app_config()
    assert config.is_production and not config.valid
    assert "AMC_AUTH_MODE must be supabase" in config.errors
    assert (config.auth_mode, config.database_backend, config.log_level) == ("local", "sqlite", "warn")
    assert config.approver_roles == ("owner", "reviewer")


def test_get_logger_only_sets_a_level_when_configured(monkeypatch):
    monkeypatch.delenv("AMC_LOG_LEVEL", raising=False)
    untouched = get_logger("amc.test.untouched")
    assert untouched.level == logging.NOTSET
    monkeypatch.setenv("AMC_LOG_LEVEL", "debug")
    assert get_logger("amc.test.debug").level == logging.DEBUG
    monkeypatch.setenv("AMC_LOG_LEVEL", "verbose")
    assert get_logger("amc.test.unknown").level == logging.NOTSET
    assert parse_log_level("warning") == "warn" and parse_log_level("nope") == "info"
