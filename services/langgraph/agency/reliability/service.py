from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..execution.canonical import canonical_hash
from ..execution.models import ExecutionReceipt, ObservationReceipt
from .models import (
    AuditCheckpoint,
    BindingStatus,
    IdempotencyRecord,
    IdempotencyStatus,
    OutboxMessage,
    OutboxStatus,
    PolicyDecisionRecord,
    PolicyEffect,
    RecoveryCase,
    RecoveryStatus,
    ReliabilitySnapshot,
    TenantProjectBinding,
)
from .store import ReliabilityStore


ZERO_HASH = "0" * 64


class ReliabilityError(RuntimeError):
    pass


class ProductionTrustKernel:
    """Production-facing trust primitives around the proof-carrying runtime.

    The kernel does not grant authority. It records and verifies tenant scope,
    policy outcomes, idempotency claims, outbox delivery state, tamper-evident
    audit checkpoints, and ambiguous execution recovery cases.
    """

    def __init__(self, store: ReliabilityStore):
        self.store = store

    def bind_project(self, *, tenant_id: str, project_id: str) -> TenantProjectBinding:
        payload = {"tenant_id": tenant_id, "project_id": project_id, "protocol": "AMC-SCOPE-1"}
        binding = TenantProjectBinding(
            tenant_id=tenant_id,
            project_id=project_id,
            binding_hash=canonical_hash(payload),
        )
        current = self.store.state.bindings.get(project_id)
        if current and current.tenant_id != tenant_id and current.status == BindingStatus.ACTIVE:
            raise ReliabilityError("PROJECT_ALREADY_BOUND_TO_DIFFERENT_TENANT")
        with self.store.transaction() as tx:
            self.store.put_binding(tx, binding)
        return binding

    def assert_scope(self, *, tenant_id: str, project_id: str) -> TenantProjectBinding:
        binding = self.store.state.bindings.get(project_id)
        if binding is None:
            raise ReliabilityError("UNKNOWN_PROJECT_SCOPE")
        if binding.status != BindingStatus.ACTIVE:
            raise ReliabilityError("PROJECT_SCOPE_REVOKED")
        if binding.tenant_id != tenant_id:
            raise ReliabilityError("CROSS_TENANT_ACCESS_DENIED")
        expected = canonical_hash({"tenant_id": tenant_id, "project_id": project_id, "protocol": "AMC-SCOPE-1"})
        if binding.binding_hash != expected:
            raise ReliabilityError("PROJECT_SCOPE_BINDING_TAMPERED")
        return binding

    def record_policy_decision(
        self,
        *,
        tenant_id: str,
        project_id: str,
        decision_id: str,
        subject_ref: str,
        action: str,
        target: str,
        policy_version: str,
        policy_input: Any,
        effect: PolicyEffect,
        required_authority_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> PolicyDecisionRecord:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        input_hash = canonical_hash(policy_input)
        payload = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "decision_id": decision_id,
            "subject_ref": subject_ref,
            "action": action,
            "target": target,
            "policy_version": policy_version,
            "input_hash": input_hash,
            "effect": effect.value,
            "required_authority_refs": sorted(required_authority_refs),
            "evidence_refs": sorted(evidence_refs),
        }
        record = PolicyDecisionRecord(
            decision_id=decision_id,
            tenant_id=tenant_id,
            project_id=project_id,
            subject_ref=subject_ref,
            action=action,
            target=target,
            policy_version=policy_version,
            input_hash=input_hash,
            effect=effect,
            required_authority_refs=tuple(sorted(required_authority_refs)),
            evidence_refs=tuple(sorted(evidence_refs)),
            decision_hash=canonical_hash(payload),
        )
        with self.store.transaction() as tx:
            self.store.put_policy(tx, record)
            self.store.append_audit(tx, self._next_audit(tenant_id, project_id, "policy_decision", decision_id, record.decision_hash))
        return record

    @staticmethod
    def require_policy(record: PolicyDecisionRecord, *, authority_refs: set[str]) -> None:
        if record.effect == PolicyEffect.DENY:
            raise ReliabilityError("POLICY_DENIED")
        if record.effect == PolicyEffect.REQUIRE_APPROVAL:
            missing = [ref for ref in record.required_authority_refs if ref not in authority_refs]
            if missing:
                raise ReliabilityError("POLICY_AUTHORITY_REQUIRED:" + ",".join(sorted(missing)))

    def claim_idempotency(
        self,
        *,
        tenant_id: str,
        project_id: str,
        idempotency_key: str,
        operation_id: str,
        request: Any,
    ) -> IdempotencyRecord:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        request_hash = canonical_hash(request)
        existing = self.store.state.idempotency.get(idempotency_key)
        if existing:
            if existing.tenant_id != tenant_id or existing.project_id != project_id:
                raise ReliabilityError("IDEMPOTENCY_SCOPE_CONFLICT")
            if existing.operation_id != operation_id or existing.request_hash != request_hash:
                self.open_recovery_case(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    operation_id=operation_id,
                    reason="IDEMPOTENCY_CONFLICT",
                    idempotency_key=idempotency_key,
                    evidence_refs=(existing.request_hash, request_hash),
                )
                raise ReliabilityError("IDEMPOTENCY_CONFLICT")
            return existing
        record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            project_id=project_id,
            operation_id=operation_id,
            request_hash=request_hash,
        )
        with self.store.transaction() as tx:
            self.store.put_idempotency(tx, record)
        return record

    def complete_idempotency(
        self,
        *,
        idempotency_key: str,
        result_ref: str | None,
        status: IdempotencyStatus = IdempotencyStatus.SUCCEEDED,
    ) -> IdempotencyRecord:
        current = self.store.state.idempotency.get(idempotency_key)
        if current is None:
            raise ReliabilityError("UNKNOWN_IDEMPOTENCY_KEY")
        updated = current.model_copy(update={
            "status": status,
            "result_ref": result_ref,
            "updated_at": datetime.now(timezone.utc),
        })
        with self.store.transaction() as tx:
            self.store.put_idempotency(tx, updated)
        return updated

    def enqueue_outbox(
        self,
        *,
        tenant_id: str,
        project_id: str,
        message_id: str,
        topic: str,
        payload: Any,
        payload_ref: str,
        idempotency_key: str,
    ) -> OutboxMessage:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        existing = self.store.state.outbox.get(message_id)
        payload_hash = canonical_hash(payload)
        if existing:
            if existing.payload_hash != payload_hash or existing.idempotency_key != idempotency_key:
                raise ReliabilityError("OUTBOX_MESSAGE_CONFLICT")
            return existing
        msg = OutboxMessage(
            message_id=message_id,
            tenant_id=tenant_id,
            project_id=project_id,
            topic=topic,
            payload_hash=payload_hash,
            payload_ref=payload_ref,
            idempotency_key=idempotency_key,
        )
        with self.store.transaction() as tx:
            self.store.put_outbox(tx, msg)
            self.store.append_audit(tx, self._next_audit(tenant_id, project_id, "outbox_enqueued", message_id, payload_hash))
        return msg

    def claim_outbox(self, *, message_id: str, worker_id: str) -> OutboxMessage:
        current = self.store.state.outbox.get(message_id)
        if current is None:
            raise ReliabilityError("UNKNOWN_OUTBOX_MESSAGE")
        if current.status == OutboxStatus.DELIVERED:
            return current
        if current.attempts >= 3:
            raise ReliabilityError("OUTBOX_RETRY_EXHAUSTED")
        updated = current.model_copy(update={
            "status": OutboxStatus.CLAIMED,
            "claimed_by": worker_id,
            "attempts": current.attempts + 1,
        })
        with self.store.transaction() as tx:
            self.store.put_outbox(tx, updated)
        return updated

    def mark_outbox_delivered(self, *, message_id: str) -> OutboxMessage:
        current = self.store.state.outbox.get(message_id)
        if current is None:
            raise ReliabilityError("UNKNOWN_OUTBOX_MESSAGE")
        updated = current.model_copy(update={
            "status": OutboxStatus.DELIVERED,
            "delivered_at": datetime.now(timezone.utc),
            "last_error": None,
        })
        with self.store.transaction() as tx:
            self.store.put_outbox(tx, updated)
            self.store.append_audit(tx, self._next_audit(current.tenant_id, current.project_id, "outbox_delivered", message_id, current.payload_hash))
        return updated

    def mark_outbox_failed(self, *, message_id: str, error: str) -> OutboxMessage:
        current = self.store.state.outbox.get(message_id)
        if current is None:
            raise ReliabilityError("UNKNOWN_OUTBOX_MESSAGE")
        updated = current.model_copy(update={"status": OutboxStatus.FAILED, "last_error": error})
        with self.store.transaction() as tx:
            self.store.put_outbox(tx, updated)
        return updated

    def open_recovery_case(
        self,
        *,
        tenant_id: str,
        project_id: str,
        operation_id: str,
        reason: str,
        execution_ref: str | None = None,
        observation_ref: str | None = None,
        idempotency_key: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> RecoveryCase:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        recovery_id = "recovery-" + canonical_hash({
            "tenant_id": tenant_id,
            "project_id": project_id,
            "operation_id": operation_id,
            "reason": reason,
        })[:24]
        existing = self.store.state.recovery.get(recovery_id)
        if existing:
            return existing
        case = RecoveryCase(
            recovery_id=recovery_id,
            tenant_id=tenant_id,
            project_id=project_id,
            operation_id=operation_id,
            reason=reason,
            execution_ref=execution_ref,
            observation_ref=observation_ref,
            idempotency_key=idempotency_key,
            evidence_refs=evidence_refs,
        )
        with self.store.transaction() as tx:
            self.store.put_recovery(tx, case)
            self.store.append_audit(tx, self._next_audit(tenant_id, project_id, "recovery_opened", recovery_id, canonical_hash(case.model_dump(mode="json"))))
        return case

    def reconcile_receipt_pairs(
        self,
        *,
        tenant_id: str,
        project_id: str,
        executions: dict[str, ExecutionReceipt],
        observations: dict[str, ObservationReceipt],
    ) -> tuple[RecoveryCase, ...]:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        created: list[RecoveryCase] = []
        for operation_id, execution in executions.items():
            observation = observations.get(operation_id)
            if observation is None:
                created.append(self.open_recovery_case(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    operation_id=operation_id,
                    reason="EXECUTION_WITHOUT_OBSERVATION",
                    execution_ref=execution.result_ref or operation_id,
                    idempotency_key=execution.idempotency_key,
                ))
            elif not observation.matches:
                created.append(self.open_recovery_case(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    operation_id=operation_id,
                    reason="OBSERVATION_MISMATCH",
                    execution_ref=execution.result_ref or operation_id,
                    observation_ref=operation_id,
                    idempotency_key=execution.idempotency_key,
                ))
        return tuple(created)

    def resolve_recovery(self, *, recovery_id: str, status: RecoveryStatus, evidence_refs: tuple[str, ...] = ()) -> RecoveryCase:
        if status == RecoveryStatus.OPEN:
            raise ReliabilityError("RECOVERY_RESOLUTION_MUST_BE_TERMINAL")
        current = self.store.state.recovery.get(recovery_id)
        if current is None:
            raise ReliabilityError("UNKNOWN_RECOVERY_CASE")
        updated = current.model_copy(update={
            "status": status,
            "evidence_refs": tuple(sorted(set(current.evidence_refs + evidence_refs))),
            "resolved_at": datetime.now(timezone.utc),
        })
        with self.store.transaction() as tx:
            self.store.put_recovery(tx, updated)
            self.store.append_audit(tx, self._next_audit(current.tenant_id, current.project_id, "recovery_resolved", recovery_id, canonical_hash(updated.model_dump(mode="json"))))
        return updated

    def verify_audit_chain(self) -> bool:
        previous = ZERO_HASH
        for expected_seq, item in enumerate(self.store.state.audits, start=1):
            if item.seq != expected_seq or item.previous_hash != previous:
                return False
            payload = {
                "seq": item.seq,
                "tenant_id": item.tenant_id,
                "project_id": item.project_id,
                "event_type": item.event_type,
                "object_ref": item.object_ref,
                "payload_hash": item.payload_hash,
                "previous_hash": item.previous_hash,
            }
            if canonical_hash(payload) != item.checkpoint_hash:
                return False
            previous = item.checkpoint_hash
        return True

    def snapshot(self, *, tenant_id: str, project_id: str) -> ReliabilitySnapshot:
        self.assert_scope(tenant_id=tenant_id, project_id=project_id)
        state = self.store.state
        audits = [a for a in state.audits if a.tenant_id == tenant_id and a.project_id == project_id]
        return ReliabilitySnapshot(
            tenant_id=tenant_id,
            project_id=project_id,
            policy_decisions=sum(1 for p in state.policy_decisions.values() if p.tenant_id == tenant_id and p.project_id == project_id),
            pending_outbox=sum(1 for m in state.outbox.values() if m.tenant_id == tenant_id and m.project_id == project_id and m.status != OutboxStatus.DELIVERED),
            open_recovery_cases=sum(1 for r in state.recovery.values() if r.tenant_id == tenant_id and r.project_id == project_id and r.status == RecoveryStatus.OPEN),
            audit_head_hash=audits[-1].checkpoint_hash if audits else ZERO_HASH,
            idempotency_claims=sum(1 for i in state.idempotency.values() if i.tenant_id == tenant_id and i.project_id == project_id),
        )

    def _next_audit(self, tenant_id: str, project_id: str, event_type: str, object_ref: str, payload_hash: str) -> AuditCheckpoint:
        state = self.store.state
        seq = len(state.audits) + 1
        previous_hash = state.audits[-1].checkpoint_hash if state.audits else ZERO_HASH
        payload = {
            "seq": seq,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "event_type": event_type,
            "object_ref": object_ref,
            "payload_hash": payload_hash,
            "previous_hash": previous_hash,
        }
        return AuditCheckpoint(
            seq=seq,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=event_type,
            object_ref=object_ref,
            payload_hash=payload_hash,
            previous_hash=previous_hash,
            checkpoint_hash=canonical_hash(payload),
        )
