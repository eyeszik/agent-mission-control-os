"""Compile the minimal, governed context a mission needs from Project OS memory.

This wraps the existing memory authority rules (``project_os.memory.resolve``),
it does not replace them. The pipeline per requested subject is:

    tenant + project scope -> thread scope (M3 only from this thread)
    -> drop quarantined learning (M6) -> existing resolve() (authority, then
    project over M0, then newest; stale reported) -> authority floor ->
    same-authority conflict check -> byte budget

Hard filters run before ranking. If every record is stale the subject is
UNRESOLVED_STALE, never a guessed fresh value. A same-authority conflict stays
visible and the subject is withheld rather than silently picking one.

The capsule hash covers the project fingerprint and every selected record, so
a change to selected memory, or to the project's artifact heads, changes it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.memory import resolve
from services.langgraph.agency.project_os.models import MemoryRecord
from services.langgraph.agency.project_os.vocabulary import authority_rank

from .contracts import ContextCapsule, MemoryChoice, MemoryUseReceipt

DEFAULT_BYTE_BUDGET = 16_384


def _body_bytes(body: Mapping) -> int:
    return len(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def project_fingerprint(project_id: str, *, exclude_types: Iterable[str] = ()) -> str:
    """Hash of the project's manifest and current artifact heads.

    ``exclude_types`` leaves out the artifact types a mission itself produces,
    so the mission's identity depends on its inputs, not on its own output
    (otherwise a replay would look like a new mission).
    """
    from services.langgraph.persistence.projects import list_project_artifacts, require_project_workspace

    skip = set(exclude_types)
    workspace = require_project_workspace(project_id)
    heads = sorted((a.artifact_id, a.version, a.content_hash or "")
                   for a in list_project_artifacts(project_id, limit=1000) if a.artifact_type not in skip)
    return canonical_hash({"project_id": project_id, "manifest_hash": workspace.manifest_hash, "heads": heads})


def _load_records(tenant_id: str, project_id: str) -> list[MemoryRecord]:
    from services.langgraph.persistence.project_knowledge import list_memory

    return [*list_memory(tenant_id=tenant_id, project_id=project_id), *list_memory(tenant_id=tenant_id, project_id=None)]


def compile_context(
    *,
    tenant_id: str,
    project_id: str,
    subjects: Mapping[str, str],
    thread_id: Optional[str] = None,
    now: Optional[datetime] = None,
    byte_budget: int = DEFAULT_BYTE_BUDGET,
    records: Optional[Iterable[MemoryRecord]] = None,
    fingerprint: Optional[str] = None,
) -> tuple[ContextCapsule, MemoryUseReceipt]:
    """``subjects`` maps each needed subject key to its minimum authority."""
    moment = now or datetime.now(timezone.utc)
    pool = [r for r in (records if records is not None else _load_records(tenant_id, project_id))
            if r.tenant_id == tenant_id and r.project_id in (project_id, None)]
    fp = fingerprint or project_fingerprint(project_id)

    choices: list[MemoryChoice] = []
    memory: dict[str, object] = {}
    unknowns: list[str] = []
    exclusions: dict[str, str] = {}
    used = 0
    for subject, floor in subjects.items():
        subject_records = [r for r in pool if r.subject_key == subject]
        other_thread = sorted(r.memory_id for r in subject_records
                              if r.scope.value == "M3_CONVERSATION" and r.thread_id != thread_id)
        for memory_id in other_thread:
            exclusions[memory_id] = "OTHER_THREAD"
        for r in subject_records:
            if r.scope.value == "M6_LEARNING":
                exclusions[r.memory_id] = "LEARNING_QUARANTINED"
        admissible = [r for r in subject_records
                      if r.memory_id not in other_thread and r.scope.value != "M6_LEARNING"]
        result = resolve(admissible, now=moment)
        winner: Optional[MemoryRecord] = result["winner"]
        base = dict(subject_key=subject, shadowed=tuple(result["shadowed"]), stale=tuple(result["stale"]),
                    excluded_other_thread=tuple(other_thread))
        if winner is None:
            status = "UNRESOLVED_STALE" if result["stale"] else "UNRESOLVED"
            choices.append(MemoryChoice(memory_id=None, authority=None, scope=None, content_hash=None, status=status, **base))
            unknowns.append(subject)
            continue
        ident = dict(memory_id=winner.memory_id, authority=winner.authority.value, scope=winner.scope.value,
                     content_hash=winner.content_hash)
        if authority_rank(winner.authority.value) < authority_rank(floor):
            choices.append(MemoryChoice(status="BELOW_AUTHORITY_FLOOR", **ident, **base))
            exclusions[winner.memory_id] = f"BELOW_AUTHORITY_FLOOR:{floor}"
            unknowns.append(subject)
            continue
        rivals = [r for r in admissible
                  if r.memory_id != winner.memory_id and r.status.value == "ACTIVE"
                  and r.authority == winner.authority and (r.project_id is None) == (winner.project_id is None)
                  and r.content_hash != winner.content_hash and r.memory_id not in result["stale"]]
        if rivals:
            choices.append(MemoryChoice(status="CONFLICT", **ident, **{**base, "shadowed": tuple(sorted(
                {*base["shadowed"], *(r.memory_id for r in rivals)}))}))
            unknowns.append(subject)
            continue
        size = _body_bytes(winner.body)
        if used + size > byte_budget:
            choices.append(MemoryChoice(status="EXCLUDED_BUDGET", **ident, **base))
            exclusions[winner.memory_id] = "BYTE_BUDGET"
            unknowns.append(subject)
            continue
        used += size
        memory[subject] = {"body": winner.body, "memory_id": winner.memory_id, "authority": winner.authority.value,
                           "content_hash": winner.content_hash}
        choices.append(MemoryChoice(status="RESOLVED", **ident, **base))

    body = {"project_id": project_id, "fingerprint": fp, "memory": memory, "unknowns": sorted(unknowns),
            "exclusions": dict(sorted(exclusions.items())), "byte_budget": byte_budget}
    capsule_hash = canonical_hash(body)
    capsule = ContextCapsule(project_id=project_id, project_fingerprint=fp, memory=memory, unknowns=tuple(sorted(unknowns)),
                             exclusions=dict(sorted(exclusions.items())), byte_budget=byte_budget, byte_size=used,
                             capsule_hash=capsule_hash)
    receipt = MemoryUseReceipt(tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, as_of=moment.isoformat(),
                               authority_floor=dict(subjects), choices=tuple(choices), context_hash=capsule_hash)
    return capsule, receipt


__all__ = ["DEFAULT_BYTE_BUDGET", "compile_context", "project_fingerprint"]
