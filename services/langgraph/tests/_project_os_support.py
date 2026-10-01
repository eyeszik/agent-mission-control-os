"""Shared helpers for the project OS test suites."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app

client = TestClient(app)
TENANT = "tenant-events-test"


def headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


def as_user(monkeypatch, user: str, *, role: str = "admin", tenant: str = TENANT, projects: str = "*", self_approval: bool = False) -> None:
    monkeypatch.setenv("AMC_LOCAL_USER_ID", user)
    monkeypatch.setenv("AMC_LOCAL_ROLE", role)
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", tenant)
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", projects)
    if self_approval:
        monkeypatch.setenv("AMC_ALLOW_SELF_APPROVAL", "1")
    else:
        monkeypatch.delenv("AMC_ALLOW_SELF_APPROVAL", raising=False)


def new_project(name: str = "Acme Launch", **extra) -> dict:
    project_id = extra.pop("project_id", f"prj-test-{uuid4().hex[:12]}")
    response = client.post(
        "/projects",
        json={"display_name": name, "project_id": project_id, "slug": f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}", **extra},
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()["project"]


@pytest.fixture
def export_root(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(root))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    return root
