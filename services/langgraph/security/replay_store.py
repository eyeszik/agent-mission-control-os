"""Nonce stores for HMAC ingress replay protection (OWASP ASI07).

Two backends implement the same contract, ``check_and_record``:

* ``DatabaseReplayStore`` (default): accepted nonces live in ``hmac_replay_nonces`` in the application
  database. Every worker and process that shares the database shares the replay memory. On SQLite the
  check and insert run inside one ``BEGIN IMMEDIATE`` transaction, so they serialize across processes.
  On PostgreSQL they run inside one transaction under a transaction-scoped advisory lock.
* ``MemoryReplayStore``: process-local and bounded. It is correct only for a single worker, so the
  application refuses it when more than one worker is configured.

Both raise ``ReplayDetected`` for a repeat, and ``ReplayStoreSaturated`` when the window already holds
``max_entries`` live nonces. The caller must fail closed on the latter.
"""

from __future__ import annotations

import threading
from typing import Protocol

REPLAY_WINDOW_SECONDS = 300
MAX_NONCES = 10_000
_ADVISORY_KEY = "amc_hmac_replay_v1"


class ReplayDetected(ValueError):
    """A nonce was already accepted inside the replay window."""


class ReplayStoreSaturated(RuntimeError):
    """Too many live nonces to record another safely. The caller must fail closed."""


class ReplayStore(Protocol):
    def check_and_record(self, nonce: str, *, timestamp: int, now: float) -> None: ...


class MemoryReplayStore:
    """Bounded, thread-safe, process-local memory of accepted nonces."""

    def __init__(self, *, window: int = REPLAY_WINDOW_SECONDS, max_entries: int = MAX_NONCES) -> None:
        if window <= 0 or max_entries <= 0:
            raise ValueError("window and max_entries must be positive")
        self._window = window
        self._max = max_entries
        self._expiry: dict[str, float] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._expiry)

    def check_and_record(self, nonce: str, *, timestamp: int, now: float) -> None:
        expires = float(timestamp + self._window)
        with self._lock:
            self._purge(now)
            if nonce in self._expiry:
                raise ReplayDetected("nonce already used")
            if len(self._expiry) >= self._max:
                raise ReplayStoreSaturated("replay store is full of live nonces")
            self._expiry[nonce] = expires

    def _purge(self, now: float) -> None:
        for nonce in [n for n, exp in self._expiry.items() if exp < now]:
            del self._expiry[nonce]


# Backwards-compatible name used by earlier code and tests.
ReplayGuard = MemoryReplayStore


class DatabaseReplayStore:
    """Replay memory shared through the application database. See the module docstring."""

    def __init__(self, *, window: int = REPLAY_WINDOW_SECONDS, max_entries: int = MAX_NONCES) -> None:
        if window <= 0 or max_entries <= 0:
            raise ValueError("window and max_entries must be positive")
        self._window = window
        self._max = max_entries

    def check_and_record(self, nonce: str, *, timestamp: int, now: float) -> None:
        # Imported here so the security package does not import persistence at module load.
        from services.langgraph.persistence.database import is_postgres, table, transaction

        now_s = int(now)
        expires = int(timestamp) + self._window
        nonces = table("hmac_replay_nonces")
        with transaction(write=True) as db:
            if is_postgres():
                db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (_ADVISORY_KEY,))
            db.execute(f"DELETE FROM {nonces} WHERE expires_at < ?", (now_s,))
            if db.execute(f"SELECT 1 AS hit FROM {nonces} WHERE nonce = ?", (nonce,)).fetchone() is not None:
                raise ReplayDetected("nonce already used")
            live = db.execute(f"SELECT COUNT(*) AS n FROM {nonces} WHERE expires_at >= ?", (now_s,)).fetchone()["n"]
            if int(live) >= self._max:
                raise ReplayStoreSaturated("replay store is full of live nonces")
            cur = db.execute(
                f"INSERT INTO {nonces} (nonce, expires_at, recorded_at) VALUES (?, ?, ?) ON CONFLICT (nonce) DO NOTHING",
                (nonce, expires, now_s),
            )
            if cur.rowcount != 1:
                raise ReplayDetected("nonce already used")

    def live_count(self, *, now: float) -> int:
        from services.langgraph.persistence.database import table, transaction

        with transaction() as db:
            row = db.execute(f"SELECT COUNT(*) AS n FROM {table('hmac_replay_nonces')} WHERE expires_at >= ?",
                             (int(now),)).fetchone()
            return int(row["n"])


def build_replay_store(backend: str, *, window: int, max_entries: int) -> ReplayStore:
    if backend == "database":
        return DatabaseReplayStore(window=window, max_entries=max_entries)
    if backend == "memory":
        return MemoryReplayStore(window=window, max_entries=max_entries)
    raise ValueError(f"unknown replay store backend: {backend!r}")
