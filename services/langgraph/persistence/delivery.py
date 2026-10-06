"""Read-only lookups the delivery contract and release gate need.

Nothing here writes. Artifact versions, dependency edges and evidence are owned
by the N4/ProjectOS kernel tables; run events by the event log. These helpers
only project those records into the shapes ``agency.delivery`` hashes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from services.langgraph.agency.delivery.release import ArtifactRef
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence.agency_kernel import get_artifact, get_evidence
from services.langgraph.persistence.database import normalize_record, table, transaction
from services.langgraph.persistence.events import list_events_for_run


def current_artifact_refs(artifact_ids: Iterable[str]) -> tuple[ArtifactRef, ...]:
    """The artifacts' current head versions (missing artifacts are omitted)."""

    refs = []
    for artifact_id in sorted(set(artifact_ids)):
        artifact = get_artifact(artifact_id)
        if artifact is None:
            continue
        refs.append(
            ArtifactRef(
                artifact_id=artifact["artifact_id"],
                version_ref=f"{artifact['artifact_id']}:v{artifact['version']}",
                content_hash=artifact.get("content_hash"),
            )
        )
    return tuple(refs)


def dependency_edges(artifact_ids: Iterable[str]) -> list[dict]:
    """Every dependency edge touching these artifacts, with upstream versions."""

    ids = sorted(set(artifact_ids))
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    with transaction() as db:
        rows = db.execute(
            f"""
            SELECT d.artifact_id, d.depends_on_artifact_id, d.relationship, u.version AS depends_on_version
            FROM {table('artifact_dependencies')} d
            JOIN {table('agency_artifacts')} u ON u.artifact_id = d.depends_on_artifact_id
            WHERE d.artifact_id IN ({placeholders}) OR d.depends_on_artifact_id IN ({placeholders})
            ORDER BY d.artifact_id, d.depends_on_artifact_id
            """,
            [*ids, *ids],
        ).fetchall()
    edges = []
    for row in rows:
        record = normalize_record(row)
        edges.append(
            {
                "artifact_id": record["artifact_id"],
                "depends_on_artifact_id": record["depends_on_artifact_id"],
                "relationship": record.get("relationship") or "hard",
                "depends_on_version_ref": f"{record['depends_on_artifact_id']}:v{record['depends_on_version']}",
            }
        )
    return edges


def _parse_time(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evidence_resolver(*, tenant_id: str, project_id: str, now: datetime) -> Callable[[str], Optional[str]]:
    """Resolve a fact's ``verification_ref`` to the evidence's current hash.

    Returns ``None`` (unverifiable) when the evidence does not exist, belongs to
    another tenant or project, or is past its own freshness window. The hash
    covers the evidence's claim, status, source, payload and collection time, so
    any change to the backing evidence changes it.
    """

    def resolve(verification_ref: str) -> Optional[str]:
        record = get_evidence(verification_ref)
        if record is None or record.get("tenant_id") != tenant_id or record.get("project_id") != project_id:
            return None
        collected = _parse_time(record.get("collected_at"))
        freshness = record.get("freshness_seconds")
        if collected is not None and freshness is not None and collected + timedelta(seconds=int(freshness)) <= now:
            return None
        return evidence_record_hash(record)

    return resolve


def evidence_record_hash(record: dict) -> str:
    return canonical_hash(
        {
            "evidence_id": record.get("evidence_id"),
            "claim": record.get("claim"),
            "epistemic_status": record.get("epistemic_status"),
            "source_ref": record.get("source_ref"),
            "payload": record.get("payload") or {},
            "collected_at": str(record.get("collected_at")),
        }
    )


def execution_lineage_hash(run_id: str) -> str:
    """Hash of the run's ordered event chain: the causal record of execution."""

    events = list_events_for_run(run_id, limit=5000)
    return canonical_hash(
        [
            {"sequence": event["sequence"], "event_id": event["event_id"], "node_id": event.get("node_id"), "event_type": event["event_type"]}
            for event in events
        ]
    )


def evaluate_run_contract(
    contract_payload: Optional[dict],
    content,
    *,
    tenant_id: str,
    project_id: str,
    contract_mode: str,
    now: Optional[datetime] = None,
) -> dict:
    """Run the deterministic critic for one run and return its stored form.

    ``content`` is the campaign package; evidence resolves against the run's
    own tenant and project. With no contract the evaluation says so plainly:
    it is never reported as passing.
    """

    from services.langgraph.agency.delivery.contract import DeliveryContract, contract_hash
    from services.langgraph.agency.delivery.critic import evaluate_contract, result_hash

    evaluated_at = now or datetime.now(timezone.utc)
    if not contract_payload:
        return {
            "status": "NO_CONTRACT",
            "contract_mode": contract_mode,
            "contract_hash": None,
            "dod": None,
            "result": None,
            "result_hash": None,
            "evaluated_at": evaluated_at.isoformat(),
        }
    contract = DeliveryContract.model_validate(contract_payload)
    result = evaluate_contract(
        contract,
        content,
        now=evaluated_at,
        resolve_evidence=evidence_resolver(tenant_id=tenant_id, project_id=project_id, now=evaluated_at),
    )
    return {
        "status": "EVALUATED",
        "contract_mode": contract_mode,
        "contract_hash": contract_hash(contract),
        "dod": result.dod,
        "result": result.model_dump(mode="json"),
        "result_hash": result_hash(result),
        "evaluated_at": evaluated_at.isoformat(),
    }
