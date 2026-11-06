"""Memory, KnowledgeOps, provider profiles, growth experiments, learning.

The learning ledger is the compiled-agency ``LearningLedger``, persisted: each
tenant's chain is replayed from ``learning_signals`` and every append goes
through ``LearningLedger.append`` so quarantine, protected-target and evidence
rules are exactly the ones the planner already enforces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4

from services.langgraph.agency.compiled.learning import (
    ALLOWED_HEURISTICS,
    PROTECTED_TARGETS,
    LearningLedger,
    LearningSignal,
)
from services.langgraph.agency.project_os.knowledge import (
    PROMOTION_SCORE_FLOOR,
    PipelineOutcome,
    SourceDocument,
    promotion_authority,
    run_pipeline,
)
from services.langgraph.agency.project_os.memory import (
    MemoryPolicyError,
    can_promote,
    decide_write,
    resolve,
    validate_placement,
)
from services.langgraph.agency.project_os.models import (
    GrowthExperiment,
    KnowledgeCapsuleMeta,
    KnowledgeClaim,
    MemoryRecord,
    ProviderCapabilityProfile,
)
from services.langgraph.agency.project_os.vocabulary import LEARNING_PROMOTION_STAGES
from services.langgraph.agency.project_os.workspace import canonical_json, sha256_bytes
from services.langgraph.persistence.database import decode_json, is_postgres, json_param, normalize_record, table, transaction
from services.langgraph.persistence.projects import ProjectConflictError, ProjectNotFoundError, require_project_workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list(value: Any) -> list:
    return list(decode_json(value, []) or [])


def _dict(value: Any) -> dict:
    return dict(decode_json(value, {}) or {})


def _ensure_tenant(db: Any, tenant_id: str) -> None:
    db.execute(
        f"INSERT INTO {table('tenants')} (tenant_id, name) VALUES (?, ?) ON CONFLICT (tenant_id) DO NOTHING",
        (tenant_id, tenant_id),
    )


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------


def _memory(row: Any) -> MemoryRecord:
    r = normalize_record(row)
    return MemoryRecord(
        memory_id=r["memory_id"], tenant_id=r["tenant_id"], project_id=r.get("project_id"), thread_id=r.get("thread_id"),
        scope=r["scope"], authority=r["authority"], subject_key=r["subject_key"], body=_dict(r.get("body")),
        source_refs=tuple(_list(r.get("source_refs"))), fresh_until=str(r["fresh_until"]) if r.get("fresh_until") else None,
        status=r["status"], supersedes=r.get("supersedes"), content_hash=r["content_hash"], created_by=r["created_by"],
        created_at=str(r["created_at"]),
    )


def _active_for_subject(db: Any, *, tenant_id: str, project_id: Optional[str], subject_key: str) -> list[MemoryRecord]:
    if project_id is None:
        rows = db.execute(
            f"SELECT * FROM {table('memory_records')} WHERE tenant_id = ? AND project_id IS NULL AND subject_key = ? AND status = 'ACTIVE'",
            (tenant_id, subject_key),
        ).fetchall()
    else:
        rows = db.execute(
            f"SELECT * FROM {table('memory_records')} WHERE tenant_id = ? AND project_id = ? AND subject_key = ? AND status = 'ACTIVE'",
            (tenant_id, project_id, subject_key),
        ).fetchall()
    return [_memory(row) for row in rows]


def write_memory(
    *,
    tenant_id: str,
    actor: str,
    scope: str,
    authority: str,
    subject_key: str,
    body: Mapping[str, Any],
    project_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    source_refs: Iterable[str] = (),
    fresh_until: Optional[str] = None,
) -> dict[str, Any]:
    validate_placement(scope=scope, authority=authority, project_id=project_id, thread_id=thread_id)
    if scope == "M1_BRAND_CANON" and not list(source_refs):
        raise MemoryPolicyError("brand canon must cite its approved source (e.g. the brand_core version ref)")
    if project_id is not None:
        require_project_workspace(project_id)
    content_hash = sha256_bytes(canonical_json({"scope": scope, "subject": subject_key, "body": dict(body)}))
    with transaction(write=True) as db:
        _ensure_tenant(db, tenant_id)
        if is_postgres():
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (f"amc-memory|{tenant_id}|{project_id}|{subject_key}",))
        active = _active_for_subject(db, tenant_id=tenant_id, project_id=project_id, subject_key=subject_key)
        decision = decide_write(authority=authority, content_hash=content_hash, active=active)
        if decision.status == "DUPLICATE":
            existing = next(record for record in active if record.memory_id == decision.supersedes)
            return {"memory": existing, "status": "DUPLICATE", "reason": decision.reason}
        if decision.supersedes:
            db.execute(f"UPDATE {table('memory_records')} SET status = 'SUPERSEDED' WHERE memory_id = ?", (decision.supersedes,))
        memory_id = f"mem-{uuid4().hex}"
        db.execute(
            f"""
            INSERT INTO {table('memory_records')}
            (memory_id, tenant_id, project_id, thread_id, scope, authority, subject_key, body, source_refs, fresh_until, status, supersedes, content_hash, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, tenant_id, project_id, thread_id, scope, authority, subject_key, json_param(dict(body)),
             json_param(sorted(set(source_refs))), fresh_until, decision.status, decision.supersedes, content_hash, actor, _now()),
        )
        row = db.execute(f"SELECT * FROM {table('memory_records')} WHERE memory_id = ?", (memory_id,)).fetchone()
    return {"memory": _memory(row), "status": decision.status, "reason": decision.reason}


def list_memory(*, tenant_id: str, project_id: Optional[str], scope: Optional[str] = None, status: Optional[str] = None) -> list[MemoryRecord]:
    if project_id is None:
        query = f"SELECT * FROM {table('memory_records')} WHERE tenant_id = ? AND project_id IS NULL"
        params: list[Any] = [tenant_id]
    else:
        query = f"SELECT * FROM {table('memory_records')} WHERE tenant_id = ? AND project_id = ?"
        params = [tenant_id, project_id]
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY subject_key, created_at"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_memory(row) for row in rows]


def resolve_memory(*, tenant_id: str, project_id: str, subject_key: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """Project memory first; agency memory (M0) only fills a gap, never overrides."""
    with transaction() as db:
        rows = db.execute(
            f"""
            SELECT * FROM {table('memory_records')}
            WHERE tenant_id = ? AND subject_key = ? AND (project_id = ? OR project_id IS NULL)
            """,
            (tenant_id, subject_key, project_id),
        ).fetchall()
    records = [_memory(row) for row in rows]
    result = resolve(records, now=now or datetime.now(timezone.utc))
    winner = result["winner"]
    return {**result, "winner": winner.model_dump(mode="json") if winner else None}


def promote_memory(*, memory_id: str, to_authority: str, actor: str, project_id: Optional[str]) -> MemoryRecord:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('memory_records')} WHERE memory_id = ?", (memory_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError("memory record not found")
    record = _memory(row)
    if record.project_id != project_id:
        raise ProjectNotFoundError("memory record not found in this project")
    can_promote(scope=record.scope.value, from_authority=record.authority.value, to_authority=to_authority)
    result = write_memory(
        tenant_id=record.tenant_id, actor=actor, scope=record.scope.value, authority=to_authority, subject_key=record.subject_key,
        body={**record.body, "promoted_from": record.memory_id, "promoted_by": actor}, project_id=record.project_id,
        thread_id=record.thread_id, source_refs=(*record.source_refs, f"memory:{record.memory_id}"), fresh_until=record.fresh_until,
    )
    if record.status.value in {"QUARANTINED", "ACTIVE"}:
        with transaction(write=True) as db:
            db.execute(f"UPDATE {table('memory_records')} SET status = 'SUPERSEDED' WHERE memory_id = ? AND status <> 'SUPERSEDED'", (memory_id,))
    return result["memory"]


def invalidate_memory(*, memory_id: str, project_id: Optional[str]) -> None:
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('memory_records')} SET status = 'INVALIDATED' WHERE memory_id = ? AND (project_id = ? OR (? IS NULL AND project_id IS NULL))",
            (memory_id, project_id, project_id),
        )
        if cursor.rowcount != 1:
            raise ProjectNotFoundError("memory record not found in this scope")


# --------------------------------------------------------------------------
# KnowledgeOps
# --------------------------------------------------------------------------


def _knowledge(row: Any) -> KnowledgeCapsuleMeta:
    r = normalize_record(row)
    return KnowledgeCapsuleMeta(
        item_id=r["item_id"], tenant_id=r["tenant_id"], project_id=r.get("project_id"), domain=r["domain"], source_uri=r["source_uri"],
        rights_class=r["rights_class"], stage=r["stage"], status=r["status"],
        claims=tuple(KnowledgeClaim(**claim) for claim in _list(r.get("claims"))), evidence_score=float(r["evidence_score"]),
        rejection_reasons=tuple(_list(r.get("rejection_reasons"))), content_hash=r["content_hash"],
        fetched_at=str(r["fetched_at"]) if r.get("fetched_at") else None, created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def ingest_knowledge(*, tenant_id: str, document: SourceDocument, project_id: Optional[str] = None, now: Optional[datetime] = None) -> KnowledgeCapsuleMeta:
    if project_id is not None:
        require_project_workspace(project_id)
    with transaction() as db:
        if project_id is None:
            rows = db.execute(f"SELECT * FROM {table('knowledge_items')} WHERE tenant_id = ? AND project_id IS NULL AND status <> 'REJECTED'", (tenant_id,)).fetchall()
        else:
            rows = db.execute(f"SELECT * FROM {table('knowledge_items')} WHERE tenant_id = ? AND (project_id = ? OR project_id IS NULL) AND status <> 'REJECTED'", (tenant_id, project_id)).fetchall()
    existing = [_knowledge(row) for row in rows]
    outcome: PipelineOutcome = run_pipeline(
        document,
        now=now or datetime.now(timezone.utc),
        known_hashes=[item.content_hash for item in existing],
        corpus=[(item.source_uri, claim.text) for item in existing for claim in item.claims],
    )
    item_id = f"kn-{uuid4().hex[:20]}"
    now_s = _now()
    with transaction(write=True) as db:
        _ensure_tenant(db, tenant_id)
        db.execute(
            f"""
            INSERT INTO {table('knowledge_items')}
            (item_id, tenant_id, project_id, domain, source_uri, rights_class, stage, status, claims, evidence_score, rejection_reasons, content_hash, fetched_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, tenant_id, project_id, document.domain, document.source_uri, outcome.rights_class.value, outcome.stage, outcome.status,
             json_param([claim.model_dump(mode="json") for claim in outcome.claims]), outcome.evidence_score,
             json_param(list(outcome.rejection_reasons)), outcome.content_hash, document.fetched_at, now_s, now_s),
        )
        row = db.execute(f"SELECT * FROM {table('knowledge_items')} WHERE item_id = ?", (item_id,)).fetchone()
    return _knowledge(row)


def list_knowledge(*, tenant_id: str, project_id: Optional[str], status: Optional[str] = None) -> list[KnowledgeCapsuleMeta]:
    if project_id is None:
        query, params = f"SELECT * FROM {table('knowledge_items')} WHERE tenant_id = ? AND project_id IS NULL", [tenant_id]
    else:
        query, params = f"SELECT * FROM {table('knowledge_items')} WHERE tenant_id = ? AND project_id = ?", [tenant_id, project_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC, item_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_knowledge(row) for row in rows]


def review_knowledge(*, item_id: str, tenant_id: str, project_id: Optional[str], reviewer: str, accept: bool) -> dict[str, Any]:
    """Human REVIEW → PROMOTE. Promotion writes evidence memory; the score
    decides whether it is VERIFIED_EVIDENCE or only WORKING_CONTEXT."""
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('knowledge_items')} WHERE item_id = ?", (item_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError("knowledge item not found")
    item = _knowledge(row)
    if item.tenant_id != tenant_id or item.project_id != project_id:
        raise ProjectNotFoundError("knowledge item not found in this scope")
    if item.status.value != "AWAITING_REVIEW":
        raise ProjectConflictError(f"knowledge item is {item.status.value}, not awaiting review")
    status = "PROMOTED" if accept else "REJECTED"
    with transaction(write=True) as db:
        db.execute(
            f"UPDATE {table('knowledge_items')} SET status = ?, stage = ?, updated_at = ? WHERE item_id = ? AND status = 'AWAITING_REVIEW'",
            (status, "PROMOTE" if accept else "REVIEW", _now(), item_id),
        )
    memory = None
    if accept and project_id is not None:
        authority = promotion_authority(item.evidence_score)
        memory = write_memory(
            tenant_id=tenant_id, actor=reviewer, scope="M4_EVIDENCE", authority=authority, subject_key=f"knowledge:{item.domain}:{item.item_id}",
            body={"claims": [claim.text for claim in item.claims], "evidence_score": item.evidence_score, "rights_class": item.rights_class.value},
            project_id=project_id, source_refs=(item.source_uri, f"knowledge:{item.item_id}"),
        )["memory"]
    return {"item_id": item_id, "status": status, "memory": memory.model_dump(mode="json") if memory else None,
            "authority_floor": PROMOTION_SCORE_FLOOR}


# --------------------------------------------------------------------------
# Provider capability profiles
# --------------------------------------------------------------------------


def upsert_provider_profile(*, tenant_id: str, profile: Mapping[str, Any]) -> ProviderCapabilityProfile:
    body = {**dict(profile), "tenant_id": tenant_id, "profile_id": profile.get("profile_id") or f"prov-{uuid4().hex[:16]}", "created_at": _now()}
    parsed = ProviderCapabilityProfile.model_validate(body)
    with transaction(write=True) as db:
        _ensure_tenant(db, tenant_id)
        existing = db.execute(
            f"SELECT profile_id, created_at FROM {table('provider_profiles')} WHERE tenant_id = ? AND provider = ? AND model = ? AND task = ?",
            (tenant_id, parsed.provider, parsed.model, parsed.task),
        ).fetchone()
        if existing is not None:
            prior = normalize_record(existing)
            parsed = parsed.model_copy(update={"profile_id": prior["profile_id"], "created_at": str(prior["created_at"])})
            db.execute(
                f"UPDATE {table('provider_profiles')} SET mode = ?, body = ?, last_verified_at = ? WHERE profile_id = ?",
                (parsed.mode.value, json_param(parsed.model_dump(mode="json")), parsed.last_verified_at, parsed.profile_id),
            )
        else:
            db.execute(
                f"INSERT INTO {table('provider_profiles')} (profile_id, tenant_id, provider, model, task, mode, body, last_verified_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (parsed.profile_id, tenant_id, parsed.provider, parsed.model, parsed.task, parsed.mode.value,
                 json_param(parsed.model_dump(mode="json")), parsed.last_verified_at, parsed.created_at),
            )
    return parsed


def list_provider_profiles(tenant_id: str, *, task: Optional[str] = None) -> list[ProviderCapabilityProfile]:
    query = f"SELECT body FROM {table('provider_profiles')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if task:
        query += " AND task = ?"
        params.append(task)
    query += " ORDER BY provider, model, task"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [ProviderCapabilityProfile.model_validate(_dict(normalize_record(row)["body"])) for row in rows]


# --------------------------------------------------------------------------
# Growth experiments
# --------------------------------------------------------------------------


def _experiment(row: Any) -> GrowthExperiment:
    r = normalize_record(row)
    return GrowthExperiment(
        experiment_id=r["experiment_id"], tenant_id=r["tenant_id"], project_id=r["project_id"], hypothesis=r["hypothesis"],
        target_metric=r["target_metric"], segment=r["segment"], intervention=r["intervention"], asset_refs=tuple(_list(r.get("asset_refs"))),
        start_at=str(r["start_at"]) if r.get("start_at") else None, end_at=str(r["end_at"]) if r.get("end_at") else None,
        sample_requirement=int(r["sample_requirement"]), status=r["status"],
        observed_result=decode_json(r.get("observed_result"), None), decision=r.get("decision"),
        learning_signal_id=r.get("learning_signal_id"), created_at=str(r["created_at"]), updated_at=str(r["updated_at"]),
    )


def create_experiment(*, tenant_id: str, project_id: str, spec: Mapping[str, Any]) -> GrowthExperiment:
    require_project_workspace(project_id)
    experiment_id = f"exp-{uuid4().hex[:16]}"
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('growth_experiments')}
            (experiment_id, tenant_id, project_id, hypothesis, target_metric, segment, intervention, asset_refs, start_at, end_at, sample_requirement, status, observed_result, decision, learning_signal_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', NULL, NULL, NULL, ?, ?)
            """,
            (experiment_id, tenant_id, project_id, spec["hypothesis"], spec["target_metric"], spec.get("segment") or "all",
             spec["intervention"], json_param(list(spec.get("asset_refs") or [])), spec.get("start_at"), spec.get("end_at"),
             int(spec.get("sample_requirement") or 1), now, now),
        )
        row = db.execute(f"SELECT * FROM {table('growth_experiments')} WHERE experiment_id = ?", (experiment_id,)).fetchone()
    return _experiment(row)


def list_experiments(project_id: str) -> list[GrowthExperiment]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('growth_experiments')} WHERE project_id = ? ORDER BY created_at", (project_id,)).fetchall()
    return [_experiment(row) for row in rows]


def conclude_experiment(*, project_id: str, experiment_id: str, observed: Mapping[str, Any], actor: str) -> GrowthExperiment:
    """Record an *observed* result. Below the declared sample requirement the
    decision is INCONCLUSIVE regardless of the effect size reported."""
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('growth_experiments')} WHERE experiment_id = ?", (experiment_id,)).fetchone()
    if row is None or _experiment(row).project_id != project_id:
        raise ProjectNotFoundError("experiment not found in project")
    experiment = _experiment(row)
    sample = int(observed.get("sample_size") or 0)
    if not observed.get("evidence_ref"):
        raise ValueError("an observed result needs an evidence_ref (analytics export, report id)")
    lift = observed.get("lift")
    if sample < experiment.sample_requirement or lift is None:
        decision = "INCONCLUSIVE"
    else:
        decision = "ADOPT" if float(lift) > 0 else "REJECT"
    signal = append_learning_signal(
        tenant_id=experiment.tenant_id,
        observation=f"experiment {experiment_id} on {experiment.target_metric}: {decision} (n={sample})",
        evidence_refs=(str(observed["evidence_ref"]),),
        target_heuristic="estimation_hints",
        run_refs=(),
    )
    with transaction(write=True) as db:
        db.execute(
            f"UPDATE {table('growth_experiments')} SET status = 'CONCLUDED', observed_result = ?, decision = ?, learning_signal_id = ?, updated_at = ? WHERE experiment_id = ?",
            (json_param({**dict(observed), "recorded_by": actor}), decision, signal["signal_id"], _now(), experiment_id),
        )
        row = db.execute(f"SELECT * FROM {table('growth_experiments')} WHERE experiment_id = ?", (experiment_id,)).fetchone()
    return _experiment(row)


# --------------------------------------------------------------------------
# Learning (persisted LearningLedger + governed promotion)
# --------------------------------------------------------------------------


def _ledger_rows(db: Any, tenant_id: str) -> list[dict]:
    rows = db.execute(f"SELECT * FROM {table('learning_signals')} WHERE tenant_id = ? ORDER BY seq", (tenant_id,)).fetchall()
    return [normalize_record(row) for row in rows]


def load_ledger(tenant_id: str) -> LearningLedger:
    with transaction() as db:
        rows = _ledger_rows(db, tenant_id)
    return LearningLedger.replay(LearningSignal.model_validate(_dict(row["payload"])) for row in rows)


def append_learning_signal(
    *,
    tenant_id: str,
    observation: str,
    evidence_refs: Iterable[str],
    target_heuristic: str,
    run_refs: Iterable[str] = (),
    confidence: Optional[float] = None,
) -> dict[str, Any]:
    with transaction(write=True) as db:
        _ensure_tenant(db, tenant_id)
        if is_postgres():
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (f"amc-learning|{tenant_id}",))
        rows = _ledger_rows(db, tenant_id)
        ledger = LearningLedger.replay(LearningSignal.model_validate(_dict(row["payload"])) for row in rows)
        signal = ledger.append(LearningSignal(
            id=f"sig-{uuid4().hex[:20]}", tenant_scope=tenant_id, run_refs=tuple(run_refs), observation=observation,
            evidence_refs=tuple(evidence_refs), target_heuristic=target_heuristic, confidence=confidence, created_at=_now(),
        ))
        db.execute(
            f"INSERT INTO {table('learning_signals')} (signal_id, tenant_id, seq, status, payload, prev_hash, hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (signal.id, tenant_id, len(rows) + 1, signal.status.value, json_param(signal.model_dump(mode="json")), signal.prev_hash, signal.hash, _now()),
        )
    return {"signal_id": signal.id, "status": signal.status.value, "hash": signal.hash,
            "governance_proposal": signal.target_heuristic in PROTECTED_TARGETS}


def list_learning_signals(tenant_id: str) -> dict[str, Any]:
    ledger = load_ledger(tenant_id)
    entries = ledger.entries(tenant_id)
    return {
        "chain_valid": ledger.verify_chain(),
        "signals": [entry.model_dump(mode="json") for entry in entries],
        "allowed_heuristics": sorted(ALLOWED_HEURISTICS),
        "protected_targets": sorted(PROTECTED_TARGETS),
    }


def _promotion(row: Any) -> dict:
    record = normalize_record(row)
    record["evidence"] = _dict(record.get("evidence"))
    return record


def start_promotion(*, tenant_id: str, signal_id: str) -> dict:
    ledger = load_ledger(tenant_id)
    signal = next((entry for entry in ledger.entries(tenant_id) if entry.id == signal_id), None)
    if signal is None:
        raise ProjectNotFoundError("learning signal not found for tenant")
    if signal.target_heuristic in PROTECTED_TARGETS:
        raise ProjectConflictError("protected targets are never promoted by the learning flow; they stay governance proposals")
    if signal.status.value != "QUARANTINED":
        raise ProjectConflictError(f"only QUARANTINED signals can enter promotion (signal is {signal.status.value})")
    promotion_id = f"promo-{uuid4().hex[:16]}"
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('learning_promotions')} (promotion_id, tenant_id, signal_id, stage, status, evidence, approved_by, created_at, updated_at) VALUES (?, ?, ?, 'QUARANTINE', 'IN_PROGRESS', ?, NULL, ?, ?)",
            (promotion_id, tenant_id, signal_id, json_param({"QUARANTINE": {"signal_hash": signal.hash}}), _now(), _now()),
        )
        row = db.execute(f"SELECT * FROM {table('learning_promotions')} WHERE promotion_id = ?", (promotion_id,)).fetchone()
    return _promotion(row)


_HUMAN_STAGES = {"HUMAN_APPROVAL"}


def advance_promotion(*, tenant_id: str, promotion_id: str, evidence: Mapping[str, Any], actor: str, actor_is_approver: bool) -> dict:
    """Move one stage forward. Every stage needs evidence; HUMAN_APPROVAL needs
    an approver; a failed regression or twin check ends the promotion."""
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('learning_promotions')} WHERE promotion_id = ?", (promotion_id,)).fetchone()
    if row is None or normalize_record(row)["tenant_id"] != tenant_id:
        raise ProjectNotFoundError("promotion not found")
    current = _promotion(row)
    if current["status"] not in {"IN_PROGRESS", "AWAITING_HUMAN_APPROVAL"}:
        raise ProjectConflictError(f"promotion is {current['status']}")
    stages = list(LEARNING_PROMOTION_STAGES)
    index = stages.index(current["stage"])
    if current["stage"] == "MONITOR" and evidence.get("rollback"):
        target = "ROLLBACK"
    else:
        target = stages[min(index + 1, stages.index("MONITOR"))]
    if not evidence:
        raise ValueError("each promotion stage needs evidence")
    status = "IN_PROGRESS"
    approved_by = current.get("approved_by")
    if target in {"SHADOW_TEST", "DIGITAL_TWIN", "REGRESSION_COMPARISON"} and evidence.get("passed") is False:
        status = "REJECTED"
    if target == "GOVERNANCE_PROPOSAL":
        status = "AWAITING_HUMAN_APPROVAL"
    if target in _HUMAN_STAGES:
        if not actor_is_approver:
            raise PermissionError("HUMAN_APPROVAL requires an approver role")
        approved_by = actor
    if target == "VERSIONED_PROMOTION":
        status = "PROMOTED"
    if target == "MONITOR":
        status = "PROMOTED"
    if target == "ROLLBACK":
        status = "ROLLED_BACK"
    merged = {**current["evidence"], target: dict(evidence)}
    with transaction(write=True) as db:
        db.execute(
            f"UPDATE {table('learning_promotions')} SET stage = ?, status = ?, evidence = ?, approved_by = ?, updated_at = ? WHERE promotion_id = ? AND stage = ?",
            (target, status, json_param(merged), approved_by, _now(), promotion_id, current["stage"]),
        )
        row = db.execute(f"SELECT * FROM {table('learning_promotions')} WHERE promotion_id = ?", (promotion_id,)).fetchone()
    return _promotion(row)


def collect_project_learning(project_id: str) -> dict[str, Any]:
    """AutomatedPostMortem: measured operational facts for a project, each with
    the event or row ids it was computed from. Nothing is inferred."""
    with transaction() as db:
        events = db.execute(f"SELECT event_type, COUNT(*) AS n FROM {table('project_events')} WHERE project_id = ? GROUP BY event_type", (project_id,)).fetchall()
        revisions = db.execute(
            f"SELECT artifact_id, COUNT(*) AS n FROM {table('artifact_versions')} WHERE project_id = ? AND change_kind <> 'create' GROUP BY artifact_id",
            (project_id,),
        ).fetchall()
        attempts = db.execute(f"SELECT state, mode, COUNT(*) AS n FROM {table('publication_attempts')} WHERE project_id = ? GROUP BY state, mode", (project_id,)).fetchall()
        jobs = db.execute(f"SELECT status, COUNT(*) AS n FROM {table('scheduled_jobs')} WHERE project_id = ? GROUP BY status", (project_id,)).fetchall()
    event_counts = {normalize_record(r)["event_type"]: int(normalize_record(r)["n"]) for r in events}
    revision_counts = {normalize_record(r)["artifact_id"]: int(normalize_record(r)["n"]) for r in revisions}
    approvals = event_counts.get("APPROVED", 0)
    rejections = event_counts.get("REJECTED", 0)
    return {
        "project_id": project_id,
        "events": event_counts,
        "revisions_per_artifact": revision_counts,
        "mean_revisions": round(sum(revision_counts.values()) / len(revision_counts), 3) if revision_counts else 0.0,
        "approval_rate": round(approvals / (approvals + rejections), 3) if approvals + rejections else None,
        "qa_blocks": event_counts.get("QA_BLOCKED", 0),
        "publication_attempts": [normalize_record(r) for r in attempts],
        "jobs": {normalize_record(r)["status"]: int(normalize_record(r)["n"]) for r in jobs},
        "campaign_performance": "UNKNOWN_NO_OBSERVED_METRICS",
    }
