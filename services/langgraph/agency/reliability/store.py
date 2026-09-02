from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol, Any

from .models import (
    AuditCheckpoint,
    IdempotencyRecord,
    OutboxMessage,
    PolicyDecisionRecord,
    RecoveryCase,
    TenantProjectBinding,
)


class ReliabilityStoreError(RuntimeError):
    pass


@dataclass
class ReliabilityState:
    bindings: dict[str, TenantProjectBinding] = field(default_factory=dict)
    policy_decisions: dict[str, PolicyDecisionRecord] = field(default_factory=dict)
    idempotency: dict[str, IdempotencyRecord] = field(default_factory=dict)
    outbox: dict[str, OutboxMessage] = field(default_factory=dict)
    audits: list[AuditCheckpoint] = field(default_factory=list)
    recovery: dict[str, RecoveryCase] = field(default_factory=dict)


class ReliabilityStore(Protocol):
    @property
    def state(self) -> ReliabilityState: ...
    def transaction(self): ...
    def put_binding(self, tx: Any, value: TenantProjectBinding) -> None: ...
    def put_policy(self, tx: Any, value: PolicyDecisionRecord) -> None: ...
    def put_idempotency(self, tx: Any, value: IdempotencyRecord) -> None: ...
    def put_outbox(self, tx: Any, value: OutboxMessage) -> None: ...
    def append_audit(self, tx: Any, value: AuditCheckpoint) -> None: ...
    def put_recovery(self, tx: Any, value: RecoveryCase) -> None: ...


class InMemoryReliabilityStore:
    def __init__(self) -> None:
        self._state = ReliabilityState()

    @property
    def state(self) -> ReliabilityState:
        return copy.deepcopy(self._state)

    @contextmanager
    def transaction(self) -> Iterator[ReliabilityState]:
        working = copy.deepcopy(self._state)
        try:
            yield working
        except Exception:
            raise
        else:
            self._state = working

    @staticmethod
    def put_binding(tx: ReliabilityState, value: TenantProjectBinding) -> None:
        tx.bindings[value.project_id] = value

    @staticmethod
    def put_policy(tx: ReliabilityState, value: PolicyDecisionRecord) -> None:
        if value.decision_id in tx.policy_decisions:
            raise ReliabilityStoreError("policy decision immutable")
        tx.policy_decisions[value.decision_id] = value

    @staticmethod
    def put_idempotency(tx: ReliabilityState, value: IdempotencyRecord) -> None:
        tx.idempotency[value.idempotency_key] = value

    @staticmethod
    def put_outbox(tx: ReliabilityState, value: OutboxMessage) -> None:
        tx.outbox[value.message_id] = value

    @staticmethod
    def append_audit(tx: ReliabilityState, value: AuditCheckpoint) -> None:
        if tx.audits and value.seq != tx.audits[-1].seq + 1:
            raise ReliabilityStoreError("audit sequence discontinuity")
        if not tx.audits and value.seq != 1:
            raise ReliabilityStoreError("audit sequence must start at 1")
        tx.audits.append(value)

    @staticmethod
    def put_recovery(tx: ReliabilityState, value: RecoveryCase) -> None:
        tx.recovery[value.recovery_id] = value


SCHEMA_VERSION = 1

DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS reliability_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reliability_bindings(
  project_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reliability_policy_decisions(
  decision_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reliability_idempotency(
  idempotency_key TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reliability_outbox(
  message_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reliability_audit_chain(
  seq INTEGER PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  checkpoint_hash TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reliability_recovery(
  recovery_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL
);
"""


class SqliteReliabilityStore:
    """Durable trust-kernel reference adapter.

    It may share the same SQLite file as the proof ledger. It intentionally uses
    separate tables and a compatible transaction contract; repository activation
    should merge these tables into the canonical migration system rather than
    create another authoritative database.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(DDL)
        self.conn.execute(
            "INSERT OR REPLACE INTO reliability_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    @property
    def state(self) -> ReliabilityState:
        state = ReliabilityState()
        for project_id, payload in self.conn.execute("SELECT project_id,payload FROM reliability_bindings"):
            state.bindings[project_id] = TenantProjectBinding.model_validate_json(payload)
        for decision_id, payload in self.conn.execute("SELECT decision_id,payload FROM reliability_policy_decisions"):
            state.policy_decisions[decision_id] = PolicyDecisionRecord.model_validate_json(payload)
        for key, payload in self.conn.execute("SELECT idempotency_key,payload FROM reliability_idempotency"):
            state.idempotency[key] = IdempotencyRecord.model_validate_json(payload)
        for message_id, payload in self.conn.execute("SELECT message_id,payload FROM reliability_outbox"):
            state.outbox[message_id] = OutboxMessage.model_validate_json(payload)
        for (payload,) in self.conn.execute("SELECT payload FROM reliability_audit_chain ORDER BY seq"):
            state.audits.append(AuditCheckpoint.model_validate_json(payload))
        for recovery_id, payload in self.conn.execute("SELECT recovery_id,payload FROM reliability_recovery"):
            state.recovery[recovery_id] = RecoveryCase.model_validate_json(payload)
        return state

    @staticmethod
    def put_binding(tx: sqlite3.Connection, value: TenantProjectBinding) -> None:
        tx.execute(
            "INSERT INTO reliability_bindings(project_id,tenant_id,payload) VALUES(?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET tenant_id=excluded.tenant_id,payload=excluded.payload",
            (value.project_id, value.tenant_id, value.model_dump_json()),
        )

    @staticmethod
    def put_policy(tx: sqlite3.Connection, value: PolicyDecisionRecord) -> None:
        try:
            tx.execute(
                "INSERT INTO reliability_policy_decisions(decision_id,tenant_id,project_id,payload) VALUES(?,?,?,?)",
                (value.decision_id, value.tenant_id, value.project_id, value.model_dump_json()),
            )
        except sqlite3.IntegrityError as exc:
            raise ReliabilityStoreError("policy decision immutable") from exc

    @staticmethod
    def put_idempotency(tx: sqlite3.Connection, value: IdempotencyRecord) -> None:
        tx.execute(
            "INSERT INTO reliability_idempotency(idempotency_key,tenant_id,project_id,request_hash,payload) VALUES(?,?,?,?,?) "
            "ON CONFLICT(idempotency_key) DO UPDATE SET tenant_id=excluded.tenant_id,project_id=excluded.project_id,request_hash=excluded.request_hash,payload=excluded.payload",
            (value.idempotency_key, value.tenant_id, value.project_id, value.request_hash, value.model_dump_json()),
        )

    @staticmethod
    def put_outbox(tx: sqlite3.Connection, value: OutboxMessage) -> None:
        tx.execute(
            "INSERT INTO reliability_outbox(message_id,tenant_id,project_id,status,payload) VALUES(?,?,?,?,?) "
            "ON CONFLICT(message_id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
            (value.message_id, value.tenant_id, value.project_id, value.status.value, value.model_dump_json()),
        )

    @staticmethod
    def append_audit(tx: sqlite3.Connection, value: AuditCheckpoint) -> None:
        last = tx.execute("SELECT seq FROM reliability_audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
        expected = (int(last[0]) + 1) if last else 1
        if value.seq != expected:
            raise ReliabilityStoreError("audit sequence discontinuity")
        tx.execute(
            "INSERT INTO reliability_audit_chain(seq,tenant_id,project_id,checkpoint_hash,payload) VALUES(?,?,?,?,?)",
            (value.seq, value.tenant_id, value.project_id, value.checkpoint_hash, value.model_dump_json()),
        )

    @staticmethod
    def put_recovery(tx: sqlite3.Connection, value: RecoveryCase) -> None:
        tx.execute(
            "INSERT INTO reliability_recovery(recovery_id,tenant_id,project_id,status,payload) VALUES(?,?,?,?,?) "
            "ON CONFLICT(recovery_id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
            (value.recovery_id, value.tenant_id, value.project_id, value.status.value, value.model_dump_json()),
        )
