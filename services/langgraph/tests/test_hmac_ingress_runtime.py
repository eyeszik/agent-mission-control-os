import hashlib
import hmac
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from services.langgraph.security import hmac_ingress as hi
from services.langgraph.persistence import sqlite_db
from services.langgraph.security.hmac_ingress import HMACIngressConfig, HMACIngressMiddleware, sign_v2
from services.langgraph.security.replay_store import DatabaseReplayStore

SECRET = b"runtime-secret"
NOW = 1_800_000_000
_BODY = b'{"operation_id":"op-1","mission_id":"mission-1","project_id":"proj_1","payload":{"x":1}}'


def _env(monkeypatch, db_name):
    monkeypatch.setenv("AMC_HMAC_SECRET", SECRET.decode("utf-8"))
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj_1")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", db_name)


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch):
    """These middleware fixtures use a separate SQLite file for each test.

    Set the backend explicitly: under the PostgreSQL suite, changing DB_PATH
    alone otherwise leaves these tests sharing the PostgreSQL replay table.
    """
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(sqlite_db, "DB_PATH", str(tmp_path / "ingress.db"))


@pytest.fixture
def clock(monkeypatch):
    """Freeze the middleware clock. The middleware resolves _now() at call time."""
    state = {"now": float(NOW)}
    monkeypatch.setattr(hi, "_now", lambda: state["now"])
    return state


def _client(monkeypatch, _label=""):
    # Unique database per client, so repeated runs never collide on persisted operation ids.
    _env(monkeypatch, f"/tmp/amc_hmac_{uuid.uuid4().hex}.db")
    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    return TestClient(main_module.app)


def _v2_headers(body=_BODY, *, timestamp=None, nonce="n" * 24, secret=SECRET):
    ts = str(NOW if timestamp is None else timestamp)
    return {
        "Content-Type": "application/json",
        "X-AMC-Signature": sign_v2(body=body, timestamp=ts, nonce=nonce, secret=secret),
        "X-AMC-Timestamp": ts,
        "X-AMC-Nonce": nonce,
    }


def test_hmac_protected_runtime_ingress_rejects_missing_signature(monkeypatch, clock):
    client = _client(monkeypatch)
    response = client.post("/runtime/ingest", json={
        "operation_id": "op-1",
        "mission_id": "mission-1",
        "project_id": "proj_1",
        "payload": {"x": 1},
    })
    assert response.status_code == 401


def test_hmac_protected_runtime_ingress_accepts_valid_v2_signature(monkeypatch, clock):
    client = _client(monkeypatch)
    response = client.post("/runtime/ingest", content=_BODY, headers=_v2_headers())
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["durable"] is False


def test_v1_body_only_signature_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    v1 = hmac.new(SECRET, _BODY, hashlib.sha256).hexdigest()
    response = client.post("/runtime/ingest", content=_BODY,
                           headers={"Content-Type": "application/json", "X-AMC-Signature": v1})
    assert response.status_code == 401


def test_replayed_v2_request_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    # Unique operation id: the ingest store is process-wide, so a fixed id would collide with other tests.
    body = _BODY.replace(b"op-1", f"op-replay-{uuid.uuid4().hex}".encode("ascii"))
    headers = _v2_headers(body, nonce="replay-nonce-0000000001")
    assert client.post("/runtime/ingest", content=body, headers=headers).status_code == 202
    assert client.post("/runtime/ingest", content=body, headers=headers).status_code == 401


def test_stale_timestamp_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    headers = _v2_headers(timestamp=NOW - 301)
    assert client.post("/runtime/ingest", content=_BODY, headers=headers).status_code == 401


def test_future_timestamp_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    headers = _v2_headers(timestamp=NOW + 301)
    assert client.post("/runtime/ingest", content=_BODY, headers=headers).status_code == 401


def test_tampered_body_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    headers = _v2_headers()
    tampered = _BODY.replace(b'"x":1', b'"x":2')
    assert client.post("/runtime/ingest", content=tampered, headers=headers).status_code == 401


def test_missing_nonce_or_timestamp_is_refused(monkeypatch, clock):
    client = _client(monkeypatch)
    headers = _v2_headers()
    no_nonce = {k: v for k, v in headers.items() if k != "X-AMC-Nonce"}
    no_ts = {k: v for k, v in headers.items() if k != "X-AMC-Timestamp"}
    assert client.post("/runtime/ingest", content=_BODY, headers=no_nonce).status_code == 401
    assert client.post("/runtime/ingest", content=_BODY, headers=no_ts).status_code == 401


# ---- unit-level checks on the middleware, using a tiny ASGI app with a small nonce store ----

async def _ok_app(scope, receive, send):
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _mini_client(max_nonces=10_000, replay_backend="database"):
    config = HMACIngressConfig(
        header_name="X-AMC-Signature", secret=SECRET, protected_paths=("/p",), max_nonces=max_nonces,
        replay_backend=replay_backend,
    )
    app = HMACIngressMiddleware(_ok_app, config)
    return TestClient(app)


def test_saturated_replay_store_returns_503(monkeypatch, clock):
    client = _mini_client(max_nonces=1)
    first = _v2_headers(nonce="first-nonce-0000000001")
    assert client.post("/p", content=_BODY, headers=first).status_code == 200
    second = _v2_headers(nonce="second-nonce-000000002")
    response = client.post("/p", content=_BODY, headers=second)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"


def test_unsigned_traffic_does_not_populate_nonce_store(monkeypatch, clock):
    client = _mini_client()
    wrong_sig = _v2_headers(nonce="unsigned-nonce-000001", secret=b"wrong-secret")
    assert client.post("/p", content=_BODY, headers=wrong_sig).status_code == 401
    stale = _v2_headers(nonce="unsigned-nonce-000002", timestamp=NOW - 9999)
    assert client.post("/p", content=_BODY, headers=stale).status_code == 401
    assert client.post("/p", content=_BODY, headers={"Content-Type": "application/json"}).status_code == 401
    assert DatabaseReplayStore().live_count(now=float(NOW)) == 0


def _unsigned_ingress_client(monkeypatch, **env):
    monkeypatch.delenv("AMC_HMAC_SECRET", raising=False)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", "/tmp/amc_unsigned_runtime.db")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    return TestClient(main_module.app)


_INGRESS_BODY = {"operation_id": "op-unsigned", "mission_id": "mission-1", "project_id": "proj_1", "payload": {}}


def test_unsigned_runtime_ingress_fails_closed_without_an_auth_provider(monkeypatch):
    client = _unsigned_ingress_client(monkeypatch, AMC_AUTH_MODE="disabled")
    response = client.post("/runtime/ingest", json=_INGRESS_BODY)
    assert response.status_code == 503


def test_unsigned_runtime_ingress_requires_a_bearer_token_in_supabase_mode(monkeypatch):
    client = _unsigned_ingress_client(
        monkeypatch,
        AMC_AUTH_MODE="supabase",
        SUPABASE_URL="https://example.invalid",
        SUPABASE_PUBLISHABLE_KEY="publishable",
    )
    response = client.post("/runtime/ingest", json=_INGRESS_BODY)
    assert response.status_code == 401


def test_unsigned_runtime_ingress_is_scoped_to_the_principal_projects(monkeypatch):
    client = _unsigned_ingress_client(
        monkeypatch,
        AMC_AUTH_MODE="local",
        AMC_LOCAL_USER_ID="local-user",
        AMC_LOCAL_TENANT_ID="tenant_1",
        AMC_LOCAL_PROJECT_IDS="proj_1",
    )
    foreign = client.post("/runtime/ingest", json={**_INGRESS_BODY, "operation_id": "op-foreign", "project_id": "proj_other"})
    assert foreign.status_code == 403
    own = client.post("/runtime/ingest", json={**_INGRESS_BODY, "operation_id": f"op-own-{os.getpid()}"})
    assert own.status_code == 202
