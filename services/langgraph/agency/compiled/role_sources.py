"""T02/T07 — source disposition ledger, RoleSourceIndex and JIT SKILL loading.

The Agency Role OS v2 archive is *source evidence*. The sealed
``runtime/role_os`` registry is the executable projection of it and stays the
only runtime authority for role identity. This module never widens that:

* every archive entry receives exactly one :class:`Disposition` (the ledger
  invariant is ``len(records) == verified_source_file_count``);
* the 1,097 role ``SKILL.md`` files are indexed by ``role_id + skill_path +
  sha256`` but are *not* vendored — their content is loaded just-in-time, only
  for selected specialists, and only after the bytes re-hash to the indexed
  value;
* loaded SKILL text is data. It is scanned for prompt-injection markers and a
  hit quarantines the load instead of passing the text through.

Nothing here can grant a permission: ``authority_class`` on every record is
descriptive, and the JIT loader returns procedure text, never authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

SOURCE_DISPOSITION_SCHEMA = "amc-compiled-source-disposition/v1"
ARCHIVE_ROOT = "agency-role-os-v2/"
DATA_DIR = Path(__file__).resolve().parent / "data"
LEDGER_PATH = DATA_DIR / "source_disposition.json"


class Disposition(str, Enum):
    RUNTIME_CANONICAL = "RUNTIME_CANONICAL"
    RUNTIME_COMPILED = "RUNTIME_COMPILED"
    JIT_SKILL_SOURCE = "JIT_SKILL_SOURCE"
    SCHEMA_SOURCE = "SCHEMA_SOURCE"
    ORCHESTRATOR_SOURCE = "ORCHESTRATOR_SOURCE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    ADVISORY = "ADVISORY"
    TEST_FIXTURE = "TEST_FIXTURE"
    DOCUMENTATION = "DOCUMENTATION"
    DUPLICATE_OF_RUNTIME = "DUPLICATE_OF_RUNTIME"
    SUPERSEDED_BY_REPO = "SUPERSEDED_BY_REPO"
    QUARANTINED_CONFLICT = "QUARANTINED_CONFLICT"


class LoadPolicy(str, Enum):
    JIT_ON_SELECTION = "JIT_ON_SELECTION"
    RUNTIME_PROJECTION_ONLY = "RUNTIME_PROJECTION_ONLY"
    NEVER_LOAD_AS_INSTRUCTION = "NEVER_LOAD_AS_INSTRUCTION"
    REVIEW_ONLY = "REVIEW_ONLY"


# Descriptive only. No value here is consulted by any authorization path.
AUTHORITY_PROCEDURAL = "PROCEDURAL_NON_AUTHORITATIVE"
AUTHORITY_SOURCE_OF_RUNTIME = "SOURCE_OF_SEALED_RUNTIME"
AUTHORITY_NONE = "NON_AUTHORITATIVE"


# --------------------------------------------------------------------------
# Prompt-injection screening
# --------------------------------------------------------------------------
#
# Narrow on purpose: a SKILL that *forbids* self-approval ("a role cannot
# approve its own high-risk work") must not trip the scanner, while text that
# instructs a reader to discard its instructions or exfiltrate secrets must.

INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore_prior_instructions", r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+(?:instructions|rules|guidance)\b"),
    ("disregard_controls", r"\bdisregard\s+(?:all\s+|the\s+|your\s+)?(?:previous|prior|system|safety|security)\b"),
    ("identity_override", r"\byou\s+are\s+now\s+(?:a|an|the|in)\b"),
    ("override_controls", r"\boverride\s+(?:the\s+)?(?:system|safety|security|governance)\s+(?:prompt|policy|policies|controls?)\b"),
    ("bypass_gate", r"\bbypass\s+(?:the\s+|any\s+|all\s+)?(?:approval|authentication|auth|guard|gate|review)s?\b"),
    ("secret_exfiltration", r"\b(?:output|reveal|print|send|post|upload)\s+(?:the\s+|your\s+)?(?:secret|api)[\s_-]?keys?\b"),
    ("script_injection", r"<\s*(?:script|img)[^>]*(?:onerror|javascript:)"),
)
_COMPILED_INJECTION = tuple((code, re.compile(p, re.IGNORECASE)) for code, p in INJECTION_PATTERNS)


def scan_for_injection(text: str) -> tuple[str, ...]:
    """Return the sorted, de-duplicated injection codes found in ``text``."""
    return tuple(sorted({code for code, rx in _COMPILED_INJECTION if rx.search(text)}))


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

# Imported specs whose substantive claims were already quarantined by the
# repository's own source-instruction disposition records (R08/R09/R12-R14,
# R21). The compiled ledger links to those records rather than re-deciding.
_QUARANTINE_MARKERS: tuple[tuple[str, str], ...] = (
    ("R08", r"cloudflare|durable object"),
    ("R09", r"\bMCP\b|model context protocol"),
    ("R12", r"stripe|HTTP 402"),
    ("R13", r"\bx402\b"),
    ("R14", r"\bTIP-20\b|\btempo\b"),
)

# Archive runtime policy files the repository already supersedes.
_SUPERSEDED: dict[str, tuple[str, str]] = {
    "runtime/retry-policy.yaml": (
        "services/langgraph/agency/role_os/work_order.py",
        "Repository retry_limit=3 and non-retryable classes are authoritative (R06).",
    ),
    "runtime/side-effect-policy.yaml": (
        "runtime/role_os/authority_registry.runtime.json",
        "DENY_CONSEQUENTIAL_BY_DEFAULT authority registry is authoritative.",
    ),
    "runtime/fsm.json": (
        "services/langgraph/agency/kernel/lifecycle.py",
        "N2 lifecycle matrices are the only lifecycle authority; runtime state_model is its RoleOS projection.",
    ),
}

_RUNTIME_COMPILED: dict[str, str] = {
    "registry/roles.json": "runtime/role_os/roles.runtime.json",
    "registry/phases.json": "runtime/role_os/phases.runtime.json",
    "registry/compiler-routing.json": "runtime/role_os/routing_index.runtime.json",
}


@dataclass(frozen=True)
class SourceDisposition:
    path: str
    sha256: str
    bytes: int
    type: str
    disposition: Disposition
    authority_class: str
    load_policy: LoadPolicy
    notes: str
    role_id: str | None = None
    orchestrator_id: str | None = None
    department: str | None = None
    family: str | None = None
    runtime_target: str | None = None
    injection_flags: tuple[str, ...] = ()
    linked_records: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "type": self.type,
            "role_id": self.role_id,
            "orchestrator_id": self.orchestrator_id,
            "department": self.department,
            "family": self.family,
            "disposition": self.disposition.value,
            "runtime_target": self.runtime_target,
            "authority_class": self.authority_class,
            "load_policy": self.load_policy.value,
            "injection_flags": list(self.injection_flags),
            "linked_records": list(self.linked_records),
            "notes": self.notes,
        }


def _file_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lstrip(".").lower()
    return suffix or "none"


def classify_entry(
    path: str,
    content: bytes,
    *,
    runtime_roles_by_path: Mapping[str, Mapping[str, Any]],
) -> SourceDisposition:
    """Assign exactly one disposition to one archive entry (path is archive-relative)."""
    sha = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8", errors="replace")
    flags = scan_for_injection(text)
    base = dict(path=path, sha256=sha, bytes=len(content), type=_file_type(path), injection_flags=flags)
    parts = PurePosixPath(path).parts

    if path in runtime_roles_by_path:
        role = runtime_roles_by_path[path]
        if flags:
            return SourceDisposition(
                **base,
                disposition=Disposition.QUARANTINED_CONFLICT,
                authority_class=AUTHORITY_NONE,
                load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
                role_id=role["role_id"],
                department=role["department"],
                family=role["family"],
                notes="Role SKILL contains prompt-injection markers; quarantined from JIT loading.",
            )
        return SourceDisposition(
            **base,
            disposition=Disposition.JIT_SKILL_SOURCE,
            authority_class=AUTHORITY_PROCEDURAL,
            load_policy=LoadPolicy.JIT_ON_SELECTION,
            role_id=role["role_id"],
            department=role["department"],
            family=role["family"],
            runtime_target="runtime/role_os/roles.runtime.json",
            notes="Procedure/expertise for a sealed RoleOS specialist; loaded only when selected; grants no authority.",
        )
    if parts[0] == "departments":
        # A department file with no sealed runtime role is a conflict, not a new role.
        return SourceDisposition(
            **base,
            disposition=Disposition.QUARANTINED_CONFLICT,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
            notes="Department file has no sealed runtime role; roles are never invented from source files.",
        )
    if parts[0] == "orchestrators":
        return SourceDisposition(
            **base,
            disposition=Disposition.ORCHESTRATOR_SOURCE,
            authority_class=AUTHORITY_PROCEDURAL,
            load_policy=LoadPolicy.REVIEW_ONLY,
            orchestrator_id=parts[1] if len(parts) > 1 else None,
            runtime_target="runtime/role_os/orchestrators.runtime.json",
            notes="Orchestrator routing procedure; the compiled control plane, not this text, schedules work.",
        )
    if path in _RUNTIME_COMPILED:
        return SourceDisposition(
            **base,
            disposition=Disposition.RUNTIME_COMPILED,
            authority_class=AUTHORITY_SOURCE_OF_RUNTIME,
            load_policy=LoadPolicy.RUNTIME_PROJECTION_ONLY,
            runtime_target=_RUNTIME_COMPILED[path],
            notes="Compiled into the sealed, hash-verified runtime registry; runtime reads the projection only.",
        )
    if path == "registry/roles.csv":
        return SourceDisposition(
            **base,
            disposition=Disposition.DUPLICATE_OF_RUNTIME,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
            runtime_target="runtime/role_os/roles.runtime.json",
            notes="Tabular duplicate of registry/roles.json.",
        )
    if path in _SUPERSEDED:
        target, note = _SUPERSEDED[path]
        return SourceDisposition(
            **base,
            disposition=Disposition.SUPERSEDED_BY_REPO,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
            runtime_target=target,
            notes=note,
        )
    if parts[0] == "schemas":
        return SourceDisposition(
            **base,
            disposition=Disposition.SCHEMA_SOURCE,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.REVIEW_ONLY,
            notes="Source schema; canonical Pydantic/Zod contracts remain authoritative (R26).",
        )
    if parts[0] == "references":
        linked = tuple(rid for rid, rx in _QUARANTINE_MARKERS if re.search(rx, text, re.IGNORECASE))
        if path.endswith("tool_proof_log.json"):
            linked = tuple(sorted(set(linked) | {"R21"}))
        if linked or flags:
            return SourceDisposition(
                **base,
                disposition=Disposition.QUARANTINED_CONFLICT,
                authority_class=AUTHORITY_NONE,
                load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
                linked_records=linked,
                notes="Imported spec asserts unverified platform/provider capability or embeds injection text; quarantined.",
            )
        return SourceDisposition(
            **base,
            disposition=Disposition.REFERENCE_ONLY,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.REVIEW_ONLY,
            notes="Imported design context; requirement, not proof (R25).",
        )
    if parts[0] == "prompts":
        return SourceDisposition(
            **base,
            disposition=Disposition.ADVISORY,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.NEVER_LOAD_AS_INSTRUCTION,
            notes="Compiler prompt text; treated as data, below repository/N1-N4 precedence.",
        )
    if parts[0] == "tests" or path == "architecture/sample-handoff.json":
        return SourceDisposition(
            **base,
            disposition=Disposition.TEST_FIXTURE,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.REVIEW_ONLY,
            notes="Source acceptance material; repository tests are the executed proof.",
        )
    if parts[0] in {"templates", "scripts"} or path == "runtime/compiler-pipeline.json":
        return SourceDisposition(
            **base,
            disposition=Disposition.REFERENCE_ONLY,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.REVIEW_ONLY,
            notes="Source tooling/template; never executed by AMC.",
        )
    if path == "runtime/context-budget-policy.yaml":
        return SourceDisposition(
            **base,
            disposition=Disposition.ADVISORY,
            authority_class=AUTHORITY_NONE,
            load_policy=LoadPolicy.REVIEW_ONLY,
            notes="Informs ContextLens minimum-context projection; not a runtime limit.",
        )
    return SourceDisposition(
        **base,
        disposition=Disposition.DOCUMENTATION,
        authority_class=AUTHORITY_NONE,
        load_policy=LoadPolicy.REVIEW_ONLY,
        notes="Archive documentation/provenance.",
    )


def _runtime_roles_by_path(runtime_roles: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {r["skill_path"]: r for r in runtime_roles}


def load_runtime_roles(runtime_root: Path | str) -> list[dict[str, Any]]:
    return json.loads((Path(runtime_root) / "roles.runtime.json").read_text(encoding="utf-8"))


def iter_archive(archive_path: Path | str) -> Iterable[tuple[str, bytes]]:
    """Yield ``(archive-relative path, bytes)`` for every file entry, sorted."""
    with zipfile.ZipFile(archive_path) as zf:
        names = sorted(n for n in zf.namelist() if not n.endswith("/"))
        for name in names:
            if not name.startswith(ARCHIVE_ROOT):
                raise ValueError(f"archive entry outside {ARCHIVE_ROOT!r}: {name}")
            rel = name[len(ARCHIVE_ROOT):]
            if ".." in PurePosixPath(rel).parts:
                raise ValueError(f"archive entry escapes root: {name}")
            yield rel, zf.read(name)


def build_disposition_ledger(archive_path: Path | str, runtime_root: Path | str) -> dict[str, Any]:
    """Programmatically disposition every archive entry. Deterministic."""
    archive_sha = hashlib.sha256(Path(archive_path).read_bytes()).hexdigest()
    by_path = _runtime_roles_by_path(load_runtime_roles(runtime_root))
    records = [classify_entry(p, c, runtime_roles_by_path=by_path) for p, c in iter_archive(archive_path)]
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec.disposition.value] = counts.get(rec.disposition.value, 0) + 1
    roles_json = next((r for r in records if r.path == "registry/roles.json"), None)
    manifest = json.loads((Path(runtime_root) / "manifest.runtime.json").read_text(encoding="utf-8"))
    ledger = {
        "schema": SOURCE_DISPOSITION_SCHEMA,
        "source_archive_sha256": archive_sha,
        "source_roles_sha256": roles_json.sha256 if roles_json else None,
        "runtime_registry_hash": manifest.get("registry_hash"),
        "verified_source_file_count": len(records),
        "disposition_count": len(records),
        "counts": dict(sorted(counts.items())),
        "records": [r.to_dict() for r in records],
    }
    ledger["ledger_hash"] = _ledger_hash(ledger)
    return ledger


def _ledger_hash(ledger: Mapping[str, Any]) -> str:
    body = {k: v for k, v in ledger.items() if k != "ledger_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class LedgerIntegrityError(RuntimeError):
    pass


def load_disposition_ledger(path: Path | str = LEDGER_PATH) -> dict[str, Any]:
    ledger = json.loads(Path(path).read_text(encoding="utf-8"))
    if ledger.get("schema") != SOURCE_DISPOSITION_SCHEMA:
        raise LedgerIntegrityError("unexpected source disposition schema")
    if ledger.get("ledger_hash") != _ledger_hash(ledger):
        raise LedgerIntegrityError("source disposition ledger hash mismatch")
    if len(ledger["records"]) != ledger["verified_source_file_count"]:
        raise LedgerIntegrityError("disposition_count != verified_source_file_count")
    return ledger


# --------------------------------------------------------------------------
# RoleSourceIndex + JIT loader
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleSourceEntry:
    role_id: str
    skill_path: str
    source_hash: str
    bytes: int


class RoleSourceIndex:
    """``role_id -> (skill_path, source_hash)`` for every sealed runtime role."""

    def __init__(self, entries: Iterable[RoleSourceEntry]):
        self._by_role = {e.role_id: e for e in entries}

    @classmethod
    def from_ledger(cls, ledger: Mapping[str, Any]) -> "RoleSourceIndex":
        return cls(
            RoleSourceEntry(r["role_id"], r["path"], r["sha256"], r["bytes"])
            for r in ledger["records"]
            if r["disposition"] == Disposition.JIT_SKILL_SOURCE.value
        )

    def __len__(self) -> int:
        return len(self._by_role)

    def __contains__(self, role_id: object) -> bool:
        return role_id in self._by_role

    def get(self, role_id: str) -> RoleSourceEntry | None:
        return self._by_role.get(role_id)

    def source_hashes(self, role_ids: Iterable[str]) -> list[str]:
        return sorted(self._by_role[r].source_hash for r in role_ids if r in self._by_role)


class JITLoadStatus(str, Enum):
    LOADED = "LOADED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NOT_INDEXED = "NOT_INDEXED"
    HASH_MISMATCH = "HASH_MISMATCH"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class JITSkill:
    role_id: str
    status: JITLoadStatus
    source_hash: str | None = None
    content: str | None = None
    injection_flags: tuple[str, ...] = ()
    authority: str = AUTHORITY_PROCEDURAL


@dataclass
class JITSkillLoader:
    """Load SKILL procedure text only for selected specialists, hash-verified.

    ``source`` may be the verified archive (``.zip``) or an extracted
    directory. With no source configured every load is ``SOURCE_UNAVAILABLE``
    — the planner still runs, it simply records that no procedure text was
    consulted. Dormant specialists are never read.
    """

    index: RoleSourceIndex
    source: Path | str | None = None
    loaded: dict[str, JITSkill] = field(default_factory=dict)

    def _read(self, skill_path: str) -> bytes | None:
        if self.source is None:
            return None
        src = Path(self.source)
        if src.is_file() and zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as zf:
                try:
                    return zf.read(ARCHIVE_ROOT + skill_path)
                except KeyError:
                    return None
        candidate = (src / skill_path).resolve()
        if src.resolve() not in candidate.parents or not candidate.is_file():
            return None
        return candidate.read_bytes()

    def load(self, role_id: str) -> JITSkill:
        if role_id in self.loaded:
            return self.loaded[role_id]
        entry = self.index.get(role_id)
        if entry is None:
            result = JITSkill(role_id, JITLoadStatus.NOT_INDEXED)
        else:
            raw = self._read(entry.skill_path)
            if raw is None:
                result = JITSkill(role_id, JITLoadStatus.SOURCE_UNAVAILABLE, entry.source_hash)
            elif hashlib.sha256(raw).hexdigest() != entry.source_hash:
                result = JITSkill(role_id, JITLoadStatus.HASH_MISMATCH, entry.source_hash)
            else:
                text = raw.decode("utf-8")
                flags = scan_for_injection(text)
                if flags:
                    result = JITSkill(role_id, JITLoadStatus.QUARANTINED, entry.source_hash, None, flags)
                else:
                    result = JITSkill(role_id, JITLoadStatus.LOADED, entry.source_hash, text)
        self.loaded[role_id] = result
        return result

    def load_selected(self, role_ids: Iterable[str]) -> list[JITSkill]:
        return [self.load(r) for r in sorted(set(role_ids))]


def default_role_source_index() -> RoleSourceIndex:
    return RoleSourceIndex.from_ledger(load_disposition_ledger())


def render_ledger(ledger: Mapping[str, Any]) -> str:
    """One record per line: reviewable diffs without an 800 KB pretty-print."""
    head = {k: v for k, v in ledger.items() if k != "records"}
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for r in ledger["records"]]
    head_text = json.dumps(head, indent=1, sort_keys=True)
    return head_text[:-2] + ',\n "records": [\n' + ",\n".join(lines) + "\n ]\n}\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exercised via CLI test
    import argparse

    parser = argparse.ArgumentParser(description="Build the compiled source disposition ledger.")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--runtime-root", default=str(Path(__file__).resolve().parents[4] / "runtime" / "role_os"))
    parser.add_argument("--output", default=str(LEDGER_PATH))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    ledger = build_disposition_ledger(args.archive, args.runtime_root)
    rendered = render_ledger(ledger)
    out = Path(args.output)
    if args.check:
        return 0 if out.is_file() and out.read_text(encoding="utf-8") == rendered else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(json.dumps({k: ledger[k] for k in ("verified_source_file_count", "counts", "ledger_hash")}, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
