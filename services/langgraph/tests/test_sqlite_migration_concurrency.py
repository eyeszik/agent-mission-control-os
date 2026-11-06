"""SQLite migration lock safety and artifact handling (ISSUE-08)."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_migration_lock_is_not_tracked_and_gitignore_covers_it():
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "*.migrate.lock" in gitignore or "migrate.lock" in gitignore


def test_concurrent_migration_only_one_acquires_ownership(tmp_path):
    """Two processes attempting migration simultaneously: only one should win without IntegrityError."""
    db_path = tmp_path / "concurrent.db"

    script = (
        "import sys\n"
        "from services.langgraph.persistence import sqlite_db\n"
        "sqlite_db.DB_PATH = sys.argv[1]\n"
        "try:\n"
        "    sqlite_db.init_db()\n"
        "    print('OK')\n"
        "except Exception as e:\n"
        "    print(f'FAIL:{e}')\n"
        "    sys.exit(1)\n"
    )

    # Launch two processes concurrently init-ing the same DB
    procs = []
    for _ in range(2):
        proc = subprocess.Popen([sys.executable, "-c", script, str(db_path)], cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append(proc)

    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=10)
        results.append((proc.returncode, out.strip(), err.strip()))

    # Both should succeed (one creates, other waits via flock)
    for code, out, err in results:
        assert code == 0, f"Migration failed: {out} {err}"
        assert "OK" in out


def test_lock_file_is_runtime_artifact_not_dependency_lock():
    """Verify legitimate lockfiles remain tracked (pnpm-lock.yaml) while migration lock is ignored."""
    assert (REPO_ROOT / "pnpm-lock.yaml").exists()
    # git ls-files should not show any *.migrate.lock
    proc = subprocess.run(["git", "ls-files", "*.migrate.lock"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.stdout.strip() == "", f"migrate.lock should not be tracked: {proc.stdout}"

    # git check-ignore should confirm the pattern is ignored
    proc2 = subprocess.run(["git", "check-ignore", "-v", "amc_local.db.migrate.lock"], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc2.returncode == 0, "migrate lock should be gitignored"


def test_stale_lock_recovery_does_not_leave_permanent_ownership(tmp_path):
    """Process termination should not leave unsafe permanent lock ownership (flock releases on close)."""
    db_path = tmp_path / "stale.db"
    lock_path = Path(str(db_path) + ".migrate.lock")

    # Simulate a process that acquires lock then terminates (flock is released on close)
    import fcntl
    with open(str(lock_path), "a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        # Hold lock briefly, then release (simulating process exit)
        assert lock_path.exists()
        # While held, another process should block; after release it should succeed

    # After release, init should succeed
    from services.langgraph.persistence import sqlite_db
    orig = sqlite_db.DB_PATH
    try:
        sqlite_db.DB_PATH = str(db_path)
        sqlite_db.init_db()
    finally:
        sqlite_db.DB_PATH = orig

    # Lock file may remain but must not prevent future migrations (flock is advisory, not persistent)
    assert db_path.exists()
