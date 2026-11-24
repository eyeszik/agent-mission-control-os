"""Tenant scope rules for row-level security (WO-04); the PostgreSQL behaviour is in test_tenant_rls.py."""

import pytest

from services.langgraph.persistence.database import current_tenant_scope, rls_mode, tenant_scope, transaction


def test_mode_defaults_off_and_unknown_values_fail_closed(monkeypatch):
    monkeypatch.delenv("AMC_DB_RLS_MODE", raising=False)
    assert rls_mode() == "off"
    monkeypatch.setenv("AMC_DB_RLS_MODE", " Scoped ")
    assert rls_mode() == "scoped"
    monkeypatch.setenv("AMC_DB_RLS_MODE", "force")
    with pytest.raises(RuntimeError, match="AMC_DB_RLS_MODE"):
        rls_mode()


def test_scope_requires_a_tenant_and_only_narrows():
    with pytest.raises(ValueError):
        with tenant_scope("  "):
            pass
    assert current_tenant_scope() is None
    with tenant_scope("t_a"):
        with tenant_scope("t_a"):
            assert current_tenant_scope() == "t_a"
        with pytest.raises(PermissionError):
            with tenant_scope("t_b"):
                pass
        assert current_tenant_scope() == "t_a"
    assert current_tenant_scope() is None


def test_scope_is_a_no_op_on_sqlite(monkeypatch):
    monkeypatch.setenv("AMC_DB_RLS_MODE", "scoped")
    with tenant_scope("t_a"):
        with transaction() as db:
            assert db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
