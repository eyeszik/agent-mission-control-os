"""Brand OS 4.0 SOP index and procedure sources: identity, provenance and ordered steps. Documentary only.

``data/brand_os_index.v1.json`` declares the 60 Brand OS ids (F01-F60). F01-F08 point at newly
written drafts in ``data/brand_os/`` (origin ``NEWLY_AUTHORED_SOP``), pinned by the SHA-256 of their
bytes. The original Brand OS 3.0 procedures were never recovered, so no entry may claim to be one.

This module only reads and checks. It registers nothing, approves nothing and grants nothing: a draft
becomes canonical in a project only through a native adoption approval (``source_approval.py``), and
runtime permission stays with the approvals route and the N2 guards (``runtime_authorized`` is typed).
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATA_DIR = Path(__file__).resolve().parent / "data"
INDEX_FILE = DATA_DIR / "brand_os_index.v1.json"
SOP_ID = r"^F(0[1-9]|[1-5][0-9]|60)$"
SHA256 = r"^[0-9a-f]{64}$"
ProcedureStatus = Literal["NEWLY_AUTHORED_DRAFT", "SOURCE_UNAVAILABLE"]
_STEP = re.compile(r"^(\d+)\.\s+(.+)$")
_PROCEDURE_HEADING = "## Procedure"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProcedureSource(_Record):
    path: str = Field(pattern=r"^brand_os/F(0[1-9]|[1-5][0-9]|60)_[A-Za-z0-9_]+\.md$")
    sha256: str = Field(pattern=SHA256)
    # Only newly written procedures exist. An original would need its own authenticated source.
    origin: Literal["NEWLY_AUTHORED_SOP"]
    version: str = Field(min_length=1)
    draft_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class IndexEntry(_Record):
    sop_id: str = Field(pattern=SOP_ID)
    name: str = Field(min_length=1)
    department_id: str = Field(pattern=r"^D(0[1-9]|1[0-2])$")
    department_name: str = Field(min_length=1)
    batch: Literal["BATCH_1", "INDEX_ONLY"]
    procedure_status: ProcedureStatus
    procedure_source: Optional[ProcedureSource] = None

    @model_validator(mode="after")
    def _status_matches_source(self) -> "IndexEntry":
        if (self.procedure_status == "NEWLY_AUTHORED_DRAFT") != (self.procedure_source is not None):
            raise ValueError(f"{self.sop_id}: a draft needs a procedure_source, and only a draft may have one")
        if self.procedure_source and not self.procedure_source.path.startswith(f"brand_os/{self.sop_id}_"):
            raise ValueError(f"{self.sop_id}: procedure_source path belongs to another SOP")
        return self


class BrandOsIndex(_Record):
    schema_version: Literal["amc-brand-os-index/v1"]
    identity_provenance: dict[str, str]
    draft_pack: dict[str, object]
    entries: tuple[IndexEntry, ...]

    @model_validator(mode="after")
    def _exact_identities(self) -> "BrandOsIndex":
        ids = [e.sop_id for e in self.entries]
        if ids != [f"F{n:02d}" for n in range(1, 61)]:
            raise ValueError("index must hold F01-F60 exactly once, in numeric order")
        wrong = [e.sop_id for e in self.entries if e.batch != ("BATCH_1" if int(e.sop_id[1:]) <= 12 else "INDEX_ONLY")]
        if wrong:
            raise ValueError(f"wrong batch for {wrong}")
        if self.identity_provenance.get("origin") != "USER_DECLARATION":
            raise ValueError("identities are a user declaration, not procedure text")
        return self

    def entry(self, sop_id: str) -> IndexEntry:
        return next(e for e in self.entries if e.sop_id == sop_id)


@lru_cache(maxsize=1)
def load_index() -> BrandOsIndex:
    return BrandOsIndex.model_validate(json.loads(INDEX_FILE.read_text(encoding="utf-8")))


def draft_bytes(entry: IndexEntry) -> bytes:
    if entry.procedure_source is None:
        raise LookupError(f"{entry.sop_id}: no procedure source exists")
    path = (DATA_DIR / entry.procedure_source.path).resolve()
    if DATA_DIR.resolve() not in path.parents:
        raise PermissionError(f"{entry.sop_id}: procedure source escapes the data directory")
    return path.read_bytes()


def verified_draft_bytes(entry: IndexEntry) -> bytes:
    """The draft's bytes, only if they still hash to the pinned digest."""
    data = draft_bytes(entry)
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry.procedure_source.sha256:  # type: ignore[union-attr]
        raise ValueError(f"{entry.sop_id}: draft bytes changed (sha256 {actual} != pinned)")
    return data


class ProcedureStep(_Record):
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1)
    line: int = Field(ge=1, description="1-based line of the step in the source file")


def step_ref(sop_id: str, sequence: int) -> str:
    """Stable step reference; always read together with the source digest it was taken from."""
    return f"{sop_id}.S{sequence}"


def _procedure_lines(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _PROCEDURE_HEADING) + 1
    except StopIteration as exc:
        raise ValueError("no '## Procedure' section") from exc
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [(i + 1, lines[i]) for i in range(start, end)]


def procedure_steps(text: str) -> tuple[ProcedureStep, ...]:
    """The ordered numbered steps of the Procedure section, exactly as written. Fails on gaps or reordering.

    Numbered lines outside the Procedure section (examples, outputs) are never steps.
    """
    steps = []
    for number, line in _procedure_lines(text):
        match = _STEP.match(line.strip())
        if match:
            steps.append(ProcedureStep(sequence=int(match.group(1)), text=match.group(2).strip(), line=number))
    if not steps:
        raise ValueError("the Procedure section has no numbered steps")
    if [s.sequence for s in steps] != list(range(1, len(steps) + 1)):
        raise ValueError(f"steps must be numbered 1..n in order, got {[s.sequence for s in steps]}")
    return tuple(steps)


class ProcedureSummary(_Record):
    """What the repository can say about one SOP. Never a grant of authority."""

    sop_id: str = Field(pattern=SOP_ID)
    name: str
    procedure_status: ProcedureStatus
    origin: Optional[Literal["NEWLY_AUTHORED_SOP"]]
    sha256: Optional[str]
    steps: tuple[ProcedureStep, ...] = ()
    original_authenticated: Literal[False] = False
    adoption: Literal["REQUIRES_NATIVE_APPROVAL"] = "REQUIRES_NATIVE_APPROVAL"
    runtime_authorized: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"


def summarize(sop_id: str) -> ProcedureSummary:
    entry = load_index().entry(sop_id)
    source = entry.procedure_source
    steps = procedure_steps(verified_draft_bytes(entry).decode("utf-8")) if source else ()
    return ProcedureSummary(sop_id=sop_id, name=entry.name, procedure_status=entry.procedure_status,
                            origin=source.origin if source else None, sha256=source.sha256 if source else None,
                            steps=steps)


# ----------------------------------------------------------------------------- companion and AGM mapping (advisory)
COMPANION_FILE = DATA_DIR / "brand_os_companion.v1.json"
MAPPING_FILE = DATA_DIR / "brand_os_agm_mapping.v1.json"
DISPOSITIONS = ("EXACT_CONTRACT_MATCH", "COMPOSITE_MATCH", "PARTIAL_MATCH", "CONFLICT", "NEW_EXTENSION_REQUIRED", "UNRESOLVED")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inventory() -> dict[str, tuple[str, list[tuple[str, int]]]]:
    """sop_id -> (pinned sha256, [(step_ref, line)]) from the actual draft bytes."""
    out = {}
    for entry in load_index().entries:
        if entry.procedure_source:
            steps = procedure_steps(verified_draft_bytes(entry).decode("utf-8"))
            out[entry.sop_id] = (entry.procedure_source.sha256, [(step_ref(entry.sop_id, s.sequence), s.line) for s in steps])
    return out


def _keying_problems(name: str, sops: list[dict]) -> list[str]:
    inventory = _inventory()
    problems = [] if [s["sop_id"] for s in sops] == sorted(inventory) else [f"{name}: SOP set differs from the drafts"]
    for sop in sops:
        pinned, steps = inventory.get(sop["sop_id"], (None, []))
        if sop["source_sha256"] != pinned:
            problems.append(f"{name}: {sop['sop_id']} keyed to a digest that is not the pinned draft")
        if [(s["step_ref"], s["line"]) for s in sop["steps"]] != steps:
            problems.append(f"{name}: {sop['sop_id']} steps do not match the extracted procedure")
    return problems


def companion_problems(companion: Optional[dict] = None) -> list[str]:
    from services.langgraph.agency.kernel import ROLE_REGISTRY

    doc = companion if companion is not None else _load(COMPANION_FILE)
    problems = [] if doc.get("scope") == "ADVISORY" else ["companion must stay ADVISORY (it is not adopted content)"]
    problems += _keying_problems("companion", doc["sops"])
    for sop in doc["sops"]:
        for step in sop["steps"]:
            role = step["native_role"]
            if role["binding"] == "MISSING" and role["role"] is not None:
                problems.append(f"{step['step_ref']}: MISSING binding cannot name a role")
            if role["binding"] != "MISSING" and role["role"] not in ROLE_REGISTRY:
                problems.append(f"{step['step_ref']}: {role['role']} is not an N3 role")
            if not all(step.get(k) for k in ("performer_suggested", "inputs", "output", "evidence", "acceptance", "on_failure")):
                problems.append(f"{step['step_ref']}: incomplete operational detail")
    return problems


def mapping_problems(mapping: Optional[dict] = None) -> list[str]:
    from services.langgraph.agency.operating_framework.catalog import load_catalog

    doc = mapping if mapping is not None else _load(MAPPING_FILE)
    catalog = load_catalog()
    problems = [] if doc["catalog_sha256"] == catalog.sha256 else ["mapping was made against another catalog revision"]
    problems += _keying_problems("mapping", doc["sops"])
    known, counts = {t.task_id for t in catalog.tasks}, {}
    for step in (s for sop in doc["sops"] for s in sop["steps"]):
        disposition = step["disposition"]
        counts[disposition] = counts.get(disposition, 0) + 1
        problems += [f"{step['step_ref']}: unknown task {t}" for t in step["task_ids"] if t not in known]
        if disposition not in DISPOSITIONS:
            problems.append(f"{step['step_ref']}: unknown disposition {disposition}")
        if disposition in ("EXACT_CONTRACT_MATCH", "COMPOSITE_MATCH") and (step["missing"] or not step["task_ids"]):
            problems.append(f"{step['step_ref']}: {disposition} needs tasks and no missing behaviour")
        if disposition == "PARTIAL_MATCH" and not (step["task_ids"] and step["covered"] and step["missing"]):
            problems.append(f"{step['step_ref']}: PARTIAL_MATCH must name tasks, covered and missing behaviour")
        if disposition == "UNRESOLVED" and step["task_ids"]:
            problems.append(f"{step['step_ref']}: UNRESOLVED cannot cite a task as a match")
    if doc["summary"]["by_disposition"] != counts or doc["summary"]["steps"] != sum(counts.values()):
        problems.append("mapping summary does not reconcile with the step dispositions")
    return problems


__all__ = [
    "BrandOsIndex",
    "companion_problems",
    "mapping_problems",
    "IndexEntry",
    "ProcedureSource",
    "ProcedureStep",
    "ProcedureSummary",
    "draft_bytes",
    "load_index",
    "procedure_steps",
    "step_ref",
    "summarize",
    "verified_draft_bytes",
]
