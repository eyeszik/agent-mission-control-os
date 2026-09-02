from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from services.langgraph.agency.reliability.models import (
    AuditCheckpoint,
    IdempotencyRecord,
    OutboxMessage,
    PolicyDecisionRecord,
    RecoveryCase,
    TenantProjectBinding,
)
from services.langgraph.agency.reliability.store import ReliabilityState, ReliabilityStoreError
from services.langgraph.persistence.database import json_param, table, transaction


def _payload_to_model(model_cls, payload: str):
    return model_cls.model_validate_json(payload)


class DatabaseReliabilityStore:
    @property
    def state(self) -> ReliabilityState:
        state = ReliabilityState()
        with transaction() as db:
            for row in db.execute(f"SELECT payload FROM {table('tenant_project_bindings')} ORDER BY project_id").fetchall():
                binding = _payload_to_model(TenantProjectBinding, row["payload"])
                state.bindings[binding.project_id] = binding
            for row in db.execute(f"SELECT payload FROM {table('policy_decision_records')} ORDER BY decided_at, decision_id").fetchall():
                record = _payload_to_model(PolicyDecisionRecord, row["payload"])
                state.policy_decisions[record.decision_id] = record
            for row in db.execute(f"SELECT payload FROM {table('trust_idempotency_records')} ORDER BY updated_at, idempotency_key").fetchall():
                record = _payload_to_model(IdempotencyRecord, row["payload"])
                state.idempotency[record.idempotency_key] = record
            for row in db.execute(f"SELECT payload FROM {table('outbox_messages')} ORDER BY created_at, message_id").fetchall():
                record = _payload_to_model(OutboxMessage, row["payload"])
                state.outbox[record.message_id] = record
            for row in db.execute(f"SELECT payload FROM {table('audit_checkpoints')} ORDER BY seq").fetchall():
                state.audits.append(_payload_to_model(AuditCheckpoint, row["payload"]))
            for row in db.execute(f"SELECT payload FROM {table('recovery_cases')} ORDER BY created_at, recovery_id").fetchall():
                record = _payload_to_model(RecoveryCase, row["payload"])
                state.recovery[record.recovery_id] = record
        return state

    @contextmanager
    def transaction(self) -> Iterator:
        with transaction(write=True) as db:
            yield db

    @staticmethod
    def put_binding(tx, value: TenantProjectBinding) -> None:
        tx.execute(
            f"""
            INSERT INTO {table('tenant_project_bindings')}
            (project_id, tenant_id, status, binding_hash, payload, created_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_id) DO UPDATE
            SET tenant_id = excluded.tenant_id,
                status = excluded.status,
                binding_hash = excluded.binding_hash,
                payload = excluded.payload,
                revoked_at = excluded.revoked_at
            """,
            (
                value.project_id,
                value.tenant_id,
                value.status.value,
                value.binding_hash,
                value.model_dump_json(),
                value.created_at.isoformat(),
                value.revoked_at.isoformat() if value.revoked_at else None,
            ),
        )

    @staticmethod
    def put_policy(tx, value: PolicyDecisionRecord) -> None:
        cursor = tx.execute(
            f"""
            INSERT INTO {table('policy_decision_records')}
            (decision_id, tenant_id, project_id, subject_ref, action, target, policy_version, input_hash, effect, required_authority_refs, evidence_refs, decision_hash, payload, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (decision_id) DO NOTHING
            """,
            (
                value.decision_id,
                value.tenant_id,
                value.project_id,
                value.subject_ref,
                value.action,
                value.target,
                value.policy_version,
                value.input_hash,
                value.effect.value,
                json_param(value.model_dump(mode="json")["required_authority_refs"]),
                json_param(value.model_dump(mode="json")["evidence_refs"]),
                value.decision_hash,
                value.model_dump_json(),
                value.decided_at.isoformat(),
            ),
        )
        if cursor.rowcount != 1:
            raise ReliabilityStoreError("policy decision immutable")

    @staticmethod
    def put_idempotency(tx, value: IdempotencyRecord) -> None:
        tx.execute(
            f"""
            INSERT INTO {table('trust_idempotency_records')}
            (idempotency_key, tenant_id, project_id, operation_id, request_hash, status, result_ref, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (idempotency_key) DO UPDATE
            SET tenant_id = excluded.tenant_id,
                project_id = excluded.project_id,
                operation_id = excluded.operation_id,
                request_hash = excluded.request_hash,
                status = excluded.status,
                result_ref = excluded.result_ref,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                value.idempotency_key,
                value.tenant_id,
                value.project_id,
                value.operation_id,
                value.request_hash,
                value.status.value,
                value.result_ref,
                value.model_dump_json(),
                value.created_at.isoformat(),
                value.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def put_outbox(tx, value: OutboxMessage) -> None:
        tx.execute(
            f"""
            INSERT INTO {table('outbox_messages')}
            (message_id, tenant_id, project_id, topic, payload_hash, payload_ref, idempotency_key, status, attempts, claimed_by, next_attempt_at, delivered_at, last_error, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (message_id) DO UPDATE
            SET status = excluded.status,
                attempts = excluded.attempts,
                claimed_by = excluded.claimed_by,
                next_attempt_at = excluded.next_attempt_at,
                delivered_at = excluded.delivered_at,
                last_error = excluded.last_error,
                payload = excluded.payload
            """,
            (
                value.message_id,
                value.tenant_id,
                value.project_id,
                value.topic,
                value.payload_hash,
                value.payload_ref,
                value.idempotency_key,
                value.status.value,
                value.attempts,
                value.claimed_by,
                value.next_attempt_at.isoformat() if value.next_attempt_at else None,
                value.delivered_at.isoformat() if value.delivered_at else None,
                value.last_error,
                value.model_dump_json(),
                value.created_at.isoformat(),
            ),
        )

    @staticmethod
    def append_audit(tx, value: AuditCheckpoint) -> None:
        last = tx.execute(f"SELECT seq FROM {table('audit_checkpoints')} ORDER BY seq DESC LIMIT 1").fetchone()
        expected = (int(last["seq"]) + 1) if last else 1
        if value.seq != expected:
            raise ReliabilityStoreError("audit sequence discontinuity")
        tx.execute(
            f"""
            INSERT INTO {table('audit_checkpoints')}
            (seq, tenant_id, project_id, event_type, object_ref, payload_hash, previous_hash, checkpoint_hash, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                value.seq,
                value.tenant_id,
                value.project_id,
                value.event_type,
                value.object_ref,
                value.payload_hash,
                value.previous_hash,
                value.checkpoint_hash,
                value.model_dump_json(),
                value.created_at.isoformat(),
            ),
        )

    @staticmethod
    def put_recovery(tx, value: RecoveryCase) -> None:
        tx.execute(
            f"""
            INSERT INTO {table('recovery_cases')}
            (recovery_id, tenant_id, project_id, operation_id, reason, execution_ref, observation_ref, idempotency_key, status, evidence_refs, payload, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (recovery_id) DO UPDATE
            SET status = excluded.status,
                evidence_refs = excluded.evidence_refs,
                payload = excluded.payload,
                resolved_at = excluded.resolved_at
            """,
            (
                value.recovery_id,
                value.tenant_id,
                value.project_id,
                value.operation_id,
                value.reason,
                value.execution_ref,
                value.observation_ref,
                value.idempotency_key,
                value.status.value,
                json_param(value.model_dump(mode="json")["evidence_refs"]),
                value.model_dump_json(),
                value.created_at.isoformat(),
                value.resolved_at.isoformat() if value.resolved_at else None,
            ),
        )
