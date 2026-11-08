"""Distributed security: shared halt and JTI replay across workers (ISSUE-05)."""

import time
import uuid
from pathlib import Path

import pytest

from services.langgraph.security.distributed import (
    ToolExecutionPolicy,
    check_and_record_jti,
    check_any_halt,
    check_halt,
    clear_halt_shared,
    set_halt,
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    from services.langgraph.persistence import sqlite_db
    path = tmp_path / f"sec_{uuid.uuid4().hex[:8]}.db"
    monkeypatch.setattr(sqlite_db, "DB_PATH", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    return path


def test_two_workers_observe_same_halt(isolated_db):
    set_halt(scope="tenant", scope_key="tenant_1", reason="security review", issuer="admin")
    # Worker 1 and worker 2 both see it
    assert check_halt(scope="tenant", scope_key="tenant_1") is not None
    assert check_any_halt(tenant_id="tenant_1") is not None
    # Tenant B is not affected
    assert check_any_halt(tenant_id="tenant_2") is None
    clear_halt_shared(scope="tenant", scope_key="tenant_1")
    assert check_halt(scope="tenant", scope_key="tenant_1") is None


def test_halt_survives_process_restart(tmp_path):
    """Halt is durable in the configured DB, not just in-memory."""
    import os
    import subprocess
    import sys
    from pathlib import Path as P

    repo_root = P(__file__).resolve().parents[3]
    db_path = tmp_path / "halt_restart.db"
    scope_key = f"restart-{uuid.uuid4().hex}"
    child_env = os.environ.copy()
    if child_env.get("AMC_DATABASE_BACKEND", "sqlite").strip().lower() != "postgres":
        # This test owns a temporary SQLite file unless the suite explicitly
        # selected PostgreSQL, in which case use its configured shared database.
        child_env["AMC_DATABASE_BACKEND"] = "sqlite"
        child_env.pop("DATABASE_URL", None)

    # Write halt via subprocess 1.
    code_set = (
        "import sys; from services.langgraph.persistence import sqlite_db; "
        "sqlite_db.DB_PATH = sys.argv[1]; "
        "from services.langgraph.security.distributed import set_halt; "
        "set_halt(scope='global', scope_key=sys.argv[2], reason='halt-test', issuer='admin'); "
        "print('SET')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code_set, str(db_path), scope_key],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=10,
        env=child_env,
    )
    assert proc.returncode == 0, proc.stderr

    # Check via subprocess 2 (simulates restart), then remove this unique row.
    code_check = (
        "import sys; from services.langgraph.persistence import sqlite_db; "
        "sqlite_db.DB_PATH = sys.argv[1]; "
        "from services.langgraph.security.distributed import check_halt, clear_halt_shared; "
        "hit = check_halt(scope='global', scope_key=sys.argv[2]); "
        "print('HIT' if hit else 'MISS'); "
        "clear_halt_shared(scope='global', scope_key=sys.argv[2])"
    )
    proc2 = subprocess.run(
        [sys.executable, "-c", code_check, str(db_path), scope_key],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=10,
        env=child_env,
    )
    assert proc2.returncode == 0, proc2.stderr
    assert "HIT" in proc2.stdout


def test_concurrent_duplicate_jti_is_rejected(isolated_db):
    jti = uuid.uuid4().hex
    now = int(time.time())
    exp = now + 300
    # First acceptance succeeds
    check_and_record_jti(jti=jti, issuer="amc-council-gateway", tenant_id="tenant_1", expires_at=exp, now=now)
    # Duplicate must be rejected
    with pytest.raises(ValueError, match="JTI_REPLAYED"):
        check_and_record_jti(jti=jti, issuer="amc-council-gateway", tenant_id="tenant_1", expires_at=exp, now=now)


def test_jti_atomicity_across_processes(tmp_path):
    """Two processes concurrently trying same JTI: exactly one wins."""
    import concurrent.futures, subprocess, sys, os
    repo_root = Path(__file__).resolve().parents[3]
    db_path = tmp_path / "jti_race.db"
    jti = f"race-{uuid.uuid4().hex}"

    def child_attempt():
        code = (
            "import sys, time\n"
            "from services.langgraph.persistence import sqlite_db\n"
            "sqlite_db.DB_PATH = sys.argv[1]\n"
            "from services.langgraph.security.distributed import check_and_record_jti\n"
            "now = int(time.time()); exp = now + 300\n"
            "try:\n"
            "    check_and_record_jti(jti=sys.argv[2], issuer='amc-council-gateway', tenant_id='t1', expires_at=exp, now=now)\n"
            "    print('ACCEPTED')\n"
            "except ValueError:\n"
            "    print('REPLAY')\n"
        )
        proc = subprocess.run([sys.executable, "-c", code, str(db_path), jti], cwd=str(repo_root), capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip().splitlines()[-1]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: child_attempt(), range(4)))

    assert outcomes.count("ACCEPTED") == 1
    assert outcomes.count("REPLAY") == 3


def test_policy_enforces_halt_and_tenant_isolation(isolated_db):
    policy = ToolExecutionPolicy()
    set_halt(scope="tenant", scope_key="tenant_1", reason="halted", issuer="admin")
    with pytest.raises(PermissionError, match="HALTED"):
        policy.check_halt(tenant_id="tenant_1")
    # Other tenant unaffected
    policy.check_halt(tenant_id="tenant_2")
    # Tenant isolation
    with pytest.raises(PermissionError, match="TENANT_ISOLATION"):
        policy.validate_tenant_scope("tenant_1", "tenant_2")
    clear_halt_shared(scope="tenant", scope_key="tenant_1")


def test_expired_halt_is_handled_according_to_policy(isolated_db):
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    set_halt(scope="job", scope_key="job-123", reason="test", issuer="admin", expires_at=past)
    # Expired halt should be cleared on check
    assert check_halt(scope="job", scope_key="job-123") is None
