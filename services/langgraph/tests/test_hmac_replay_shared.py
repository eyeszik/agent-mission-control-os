"""ASI07: replay protection must hold across workers and processes, not just within one process.

These tests use real OS processes: a multi-worker uvicorn server and concurrent subprocesses that share
one SQLite database. They are not mocks.
"""

import concurrent.futures
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from services.langgraph.persistence import sqlite_db
from services.langgraph.security import replay_store
from services.langgraph.security.hmac_ingress import sign_v2
from services.langgraph.security.replay_store import DatabaseReplayStore, ReplayDetected, ReplayStoreSaturated

REPO_ROOT = Path(__file__).resolve().parents[3]
SECRET = "shared-replay-secret"


@pytest.fixture
def shared_db(tmp_path, monkeypatch):
    path = tmp_path / "replay.db"
    monkeypatch.setattr(sqlite_db, "DB_PATH", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    return str(path)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_schema_v21_creates_the_shared_nonce_table(shared_db):
    assert sqlite_db.current_schema_version() == sqlite_db._MIGRATIONS[-1][0] >= 21
    store = DatabaseReplayStore()
    assert store.live_count(now=time.time()) == 0


def test_database_store_refuses_a_repeat_and_saturates_closed(shared_db):
    now = time.time()
    store = DatabaseReplayStore(window=300, max_entries=2)
    store.check_and_record("nonce-aaaaaaaaaaaaaaaa", timestamp=int(now), now=now)
    with pytest.raises(ReplayDetected):
        store.check_and_record("nonce-aaaaaaaaaaaaaaaa", timestamp=int(now), now=now)
    store.check_and_record("nonce-bbbbbbbbbbbbbbbb", timestamp=int(now), now=now)
    with pytest.raises(ReplayStoreSaturated):
        store.check_and_record("nonce-cccccccccccccccc", timestamp=int(now), now=now)
    # Once the window closes, the rows are purged and capacity returns.
    later = now + 301
    store.check_and_record("nonce-cccccccccccccccc", timestamp=int(later), now=later)
    assert store.live_count(now=later) == 1


def test_expired_nonce_is_purged_and_can_be_recorded_again_only_with_a_fresh_timestamp(shared_db):
    now = time.time()
    store = DatabaseReplayStore(window=300, max_entries=10)
    store.check_and_record("nonce-dddddddddddddddd", timestamp=int(now), now=now)
    later = now + 1000
    store.check_and_record("nonce-dddddddddddddddd", timestamp=int(later), now=later)


def _child_attempt(db_path: str, nonce: str) -> str:
    code = (
        "import sys, time\n"
        "from services.langgraph.persistence import sqlite_db\n"
        "sqlite_db.DB_PATH = sys.argv[1]\n"
        "from services.langgraph.security.replay_store import DatabaseReplayStore, ReplayDetected\n"
        "now = time.time()\n"
        "try:\n"
        "    DatabaseReplayStore().check_and_record(sys.argv[2], timestamp=int(now), now=now)\n"
        "    print('ACCEPTED')\n"
        "except ReplayDetected:\n"
        "    print('REPLAY')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code, db_path, nonce], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "AMC_DATABASE_BACKEND": "sqlite"})
    assert proc.returncode == 0, proc.stderr[-800:]
    return proc.stdout.strip().splitlines()[-1]


def test_concurrent_processes_accept_a_nonce_exactly_once(shared_db):
    nonce = f"proc-race-{uuid.uuid4().hex}"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: _child_attempt(shared_db, nonce), range(8)))
    assert outcomes.count("ACCEPTED") == 1, outcomes
    assert outcomes.count("REPLAY") == 7, outcomes


def test_multi_worker_server_refuses_a_replay_on_any_worker(shared_db, tmp_path):
    port = _free_port()
    env = {**os.environ, "AMC_TEST_HMAC_SECRET": SECRET, "AMC_TEST_REPLAY_BACKEND": "database",
           "AMC_DB_PATH": shared_db, "AMC_DATABASE_BACKEND": "sqlite"}
    log = open(tmp_path / "uvicorn.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.langgraph.tests.hmac_replay_worker_app:app",
         "--host", "127.0.0.1", "--port", str(port), "--workers", "3", "--log-level", "warning"],
        cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("server did not start: " + (tmp_path / "uvicorn.log").read_text()[-800:])

        body = b"{}"
        nonce = f"worker-race-{uuid.uuid4().hex}"
        ts = str(int(time.time()))
        headers = {"X-AMC-Signature": sign_v2(body=body, timestamp=ts, nonce=nonce, secret=SECRET.encode()),
                   "X-AMC-Timestamp": ts, "X-AMC-Nonce": nonce, "Connection": "close"}

        def send(_):
            with httpx.Client(timeout=30) as client:
                r = client.post(f"http://127.0.0.1:{port}/p", content=body, headers=headers)
                return r.status_code, r.headers.get("x-worker-pid")

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(send, range(48)))
        statuses = [s for s, _ in results]
        pids = {p for _, p in results if p}
        assert statuses.count(200) == 1, statuses
        assert statuses.count(401) == 47, statuses
        assert len(pids) >= 2, f"requests were served by only {pids}; the test did not cross workers"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def test_memory_store_is_refused_when_more_than_one_worker_is_configured(monkeypatch):
    from services.langgraph.app import config
    monkeypatch.setenv("AMC_HMAC_REPLAY_STORE", "memory")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="refused with multiple workers"):
        config.hmac_replay_backend()
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    assert config.hmac_replay_backend() == "memory"
    monkeypatch.setenv("AMC_HMAC_REPLAY_STORE", "redis")
    with pytest.raises(RuntimeError):
        config.hmac_replay_backend()


def test_default_backend_is_the_shared_database(monkeypatch):
    from services.langgraph.app import config
    monkeypatch.delenv("AMC_HMAC_REPLAY_STORE", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    assert config.hmac_replay_backend() == "database"
    assert isinstance(replay_store.build_replay_store("database", window=300, max_entries=5), DatabaseReplayStore)
