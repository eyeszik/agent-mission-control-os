"""N4 — artifact registry: branch lineage, serialization, and merge resolution.

Cross-department runs revise the same artifact concurrently: copy edits a
campaign package while design revises the brief it depends on. Overwriting in
place loses one of those edits silently, which is the failure this module
exists to prevent.

The model is deliberately small and git-shaped, because the semantics are
already familiar:

* an artifact has a **lineage** of immutable versions;
* a **branch** is a named line of revision off a base version;
* a **merge** of two branches is resolved by a declared matrix, never by
  "last write wins".

Nothing here mutates the database. The registry computes lineage and merge
outcomes over serializable records so the result can be checkpointed, replayed,
and asserted in tests without a live connection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from services.langgraph.agency.kernel.models import ArtifactStatus
from services.langgraph.agency.kernel.ontology import (
    ArtifactType,
    Department,
    assert_department_owns,
    resolve_artifact_type,
    resolve_department,
)

REGISTRY_VERSION = "amc-agency-registry/n4-v1"

MAIN_BRANCH = "main"


class MergeResolution(str, Enum):
    """How a concurrent revision pair is resolved."""

    fast_forward = "fast_forward"          # one side did not diverge
    take_incoming = "take_incoming"        # incoming supersedes base
    keep_base = "keep_base"                # base wins; incoming is discarded
    merge_content = "merge_content"        # both survive, content merged
    escalate = "escalate"                  # a human must decide


class MergeError(ValueError):
    """Raised when a merge is attempted across incompatible artifacts."""


@dataclass(frozen=True)
class ArtifactVersion:
    """One immutable point in an artifact's lineage."""

    artifact_id: str
    branch: str
    version: int
    status: ArtifactStatus
    artifact_type: ArtifactType
    owner_department: Department
    content_hash: str
    parent_version: int | None = None
    # The version on the base branch this branch forked from. None on main.
    forked_from: int | None = None
    generation_mode: str | None = None
    assumptions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "branch": self.branch,
            "version": self.version,
            "status": self.status.value,
            "artifact_type": self.artifact_type.value,
            "owner_department": self.owner_department.value,
            "content_hash": self.content_hash,
            "parent_version": self.parent_version,
            "forked_from": self.forked_from,
            "generation_mode": self.generation_mode,
            "assumptions": list(self.assumptions),
            "metadata": self.metadata,
        }

    @classmethod
    def deserialize(cls, payload: dict[str, Any]) -> "ArtifactVersion":
        return cls(
            artifact_id=payload["artifact_id"],
            branch=payload["branch"],
            version=int(payload["version"]),
            status=ArtifactStatus(payload["status"]),
            artifact_type=resolve_artifact_type(payload["artifact_type"]),
            owner_department=resolve_department(payload["owner_department"]),
            content_hash=payload["content_hash"],
            parent_version=payload.get("parent_version"),
            forked_from=payload.get("forked_from"),
            generation_mode=payload.get("generation_mode"),
            assumptions=tuple(payload.get("assumptions") or ()),
            metadata=payload.get("metadata") or {},
        )


def content_fingerprint(content: Any) -> str:
    """Stable content hash. Sorted keys so equal content always hashes equal."""
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Merge resolution matrix
# --------------------------------------------------------------------------
#
# Keyed by (base_status, incoming_status). The matrix is asymmetric on purpose:
# a released artifact is not silently replaced by a draft, and an invalidated
# artifact does not resurrect by being merged into.

_M = MergeResolution
_S = ArtifactStatus

MERGE_MATRIX: dict[tuple[ArtifactStatus, ArtifactStatus], MergeResolution] = {
    # A draft base accepts almost anything; nothing is at stake yet.
    (_S.draft, _S.draft): _M.merge_content,
    (_S.draft, _S.validating): _M.take_incoming,
    (_S.draft, _S.approved): _M.take_incoming,
    (_S.draft, _S.release_eligible): _M.take_incoming,
    (_S.draft, _S.released): _M.take_incoming,
    (_S.draft, _S.review_required): _M.take_incoming,
    (_S.draft, _S.invalidated): _M.keep_base,
    (_S.draft, _S.archived): _M.keep_base,

    # Validation in flight: an incoming change restarts validation.
    (_S.validating, _S.draft): _M.escalate,
    (_S.validating, _S.validating): _M.merge_content,
    (_S.validating, _S.approved): _M.take_incoming,
    (_S.validating, _S.release_eligible): _M.take_incoming,
    (_S.validating, _S.released): _M.take_incoming,
    (_S.validating, _S.review_required): _M.take_incoming,
    (_S.validating, _S.invalidated): _M.take_incoming,
    (_S.validating, _S.archived): _M.keep_base,

    # Approved work has passed a gate. Anything unreviewed forces re-review.
    (_S.approved, _S.draft): _M.escalate,
    (_S.approved, _S.validating): _M.escalate,
    (_S.approved, _S.approved): _M.escalate,
    (_S.approved, _S.release_eligible): _M.take_incoming,
    (_S.approved, _S.released): _M.take_incoming,
    (_S.approved, _S.review_required): _M.take_incoming,
    (_S.approved, _S.invalidated): _M.take_incoming,
    (_S.approved, _S.archived): _M.keep_base,

    # Release-eligible and released bases never regress without a human.
    (_S.release_eligible, _S.draft): _M.escalate,
    (_S.release_eligible, _S.validating): _M.escalate,
    (_S.release_eligible, _S.approved): _M.escalate,
    (_S.release_eligible, _S.release_eligible): _M.escalate,
    (_S.release_eligible, _S.released): _M.take_incoming,
    (_S.release_eligible, _S.review_required): _M.take_incoming,
    (_S.release_eligible, _S.invalidated): _M.take_incoming,
    (_S.release_eligible, _S.archived): _M.keep_base,

    (_S.released, _S.draft): _M.escalate,
    (_S.released, _S.validating): _M.escalate,
    (_S.released, _S.approved): _M.escalate,
    (_S.released, _S.release_eligible): _M.escalate,
    (_S.released, _S.released): _M.escalate,
    (_S.released, _S.review_required): _M.take_incoming,
    (_S.released, _S.invalidated): _M.take_incoming,
    (_S.released, _S.archived): _M.escalate,

    # A base already flagged for review absorbs changes but stays flagged.
    (_S.review_required, _S.draft): _M.keep_base,
    (_S.review_required, _S.validating): _M.keep_base,
    (_S.review_required, _S.approved): _M.escalate,
    (_S.review_required, _S.release_eligible): _M.escalate,
    (_S.review_required, _S.released): _M.escalate,
    (_S.review_required, _S.review_required): _M.merge_content,
    (_S.review_required, _S.invalidated): _M.take_incoming,
    (_S.review_required, _S.archived): _M.keep_base,

    # Invalidated content must be rebuilt, not merged over.
    (_S.invalidated, _S.draft): _M.take_incoming,
    (_S.invalidated, _S.validating): _M.take_incoming,
    (_S.invalidated, _S.approved): _M.escalate,
    (_S.invalidated, _S.release_eligible): _M.escalate,
    (_S.invalidated, _S.released): _M.escalate,
    (_S.invalidated, _S.review_required): _M.take_incoming,
    (_S.invalidated, _S.invalidated): _M.keep_base,
    (_S.invalidated, _S.archived): _M.take_incoming,

    # Archived is terminal.
    (_S.archived, _S.draft): _M.keep_base,
    (_S.archived, _S.validating): _M.keep_base,
    (_S.archived, _S.approved): _M.keep_base,
    (_S.archived, _S.release_eligible): _M.keep_base,
    (_S.archived, _S.released): _M.keep_base,
    (_S.archived, _S.review_required): _M.keep_base,
    (_S.archived, _S.invalidated): _M.keep_base,
    (_S.archived, _S.archived): _M.keep_base,
}


@dataclass(frozen=True)
class MergeOutcome:
    resolution: MergeResolution
    winner: ArtifactVersion | None
    reason: str
    requires_human: bool

    def serialize(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "winner": self.winner.serialize() if self.winner else None,
            "reason": self.reason,
            "requires_human": self.requires_human,
        }


class ArtifactRegistry:
    """In-memory lineage over one artifact's versions across branches."""

    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self._versions: list[ArtifactVersion] = []

    # -- construction ------------------------------------------------------

    def commit(
        self,
        *,
        branch: str,
        status: ArtifactStatus,
        artifact_type: str | ArtifactType,
        owner_department: str | Department,
        content: Any,
        generation_mode: str | None = None,
        assumptions: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactVersion:
        """Append an immutable version to a branch."""
        resolved_type = resolve_artifact_type(artifact_type)
        resolved_department = resolve_department(owner_department)
        # N1 ownership is enforced at write time, not merely at read time.
        assert_department_owns(resolved_department, resolved_type)

        head = self.head(branch)
        forked_from: int | None = None
        if head is None and branch != MAIN_BRANCH:
            main_head = self.head(MAIN_BRANCH)
            if main_head is None:
                raise MergeError(
                    f"cannot open branch '{branch}' before '{MAIN_BRANCH}' has a version"
                )
            forked_from = main_head.version
        elif head is not None:
            forked_from = head.forked_from

        version = ArtifactVersion(
            artifact_id=self.artifact_id,
            branch=branch,
            version=self._next_version(),
            status=status,
            artifact_type=resolved_type,
            owner_department=resolved_department,
            content_hash=content_fingerprint(content),
            parent_version=head.version if head else None,
            forked_from=forked_from,
            generation_mode=generation_mode,
            assumptions=tuple(assumptions),
            metadata=metadata or {},
        )
        self._versions.append(version)
        return version

    def _next_version(self) -> int:
        return len(self._versions) + 1

    # -- reads -------------------------------------------------------------

    def head(self, branch: str) -> ArtifactVersion | None:
        for version in reversed(self._versions):
            if version.branch == branch:
                return version
        return None

    def branches(self) -> list[str]:
        seen: dict[str, None] = {}
        for version in self._versions:
            seen.setdefault(version.branch, None)
        return list(seen)

    def lineage(self, branch: str) -> list[ArtifactVersion]:
        return [version for version in self._versions if version.branch == branch]

    def all_versions(self) -> list[ArtifactVersion]:
        return list(self._versions)

    # -- merge -------------------------------------------------------------

    def merge(self, incoming_branch: str, base_branch: str = MAIN_BRANCH) -> MergeOutcome:
        """Resolve ``incoming_branch`` into ``base_branch`` via the matrix."""
        incoming = self.head(incoming_branch)
        base = self.head(base_branch)
        if incoming is None:
            raise MergeError(f"branch '{incoming_branch}' has no versions to merge")
        if base is None:
            raise MergeError(f"base branch '{base_branch}' has no versions")
        if incoming.artifact_type is not base.artifact_type:
            raise MergeError(
                f"cannot merge artifact type '{incoming.artifact_type.value}' into "
                f"'{base.artifact_type.value}'"
            )

        # Degraded output is never merged into a base by machine decision.
        if (incoming.generation_mode or "") == "FALLBACK_DEGRADED":
            return MergeOutcome(
                resolution=MergeResolution.escalate,
                winner=None,
                reason="incoming branch carries FALLBACK_DEGRADED provenance",
                requires_human=True,
            )

        # Identical content is a no-op regardless of status.
        if incoming.content_hash == base.content_hash:
            return MergeOutcome(
                resolution=MergeResolution.fast_forward,
                winner=base,
                reason="incoming content is identical to base",
                requires_human=False,
            )

        # The base has not moved since the fork: nothing to reconcile.
        if incoming.forked_from is not None and incoming.forked_from == base.version:
            return MergeOutcome(
                resolution=MergeResolution.fast_forward,
                winner=incoming,
                reason="base has not advanced since the branch forked",
                requires_human=False,
            )

        resolution = MERGE_MATRIX[(base.status, incoming.status)]
        if resolution is MergeResolution.escalate:
            winner = None
        elif resolution is MergeResolution.keep_base:
            winner = base
        else:
            winner = incoming

        return MergeOutcome(
            resolution=resolution,
            winner=winner,
            reason=(
                f"base '{base.status.value}' + incoming '{incoming.status.value}' "
                f"resolves to {resolution.value}"
            ),
            requires_human=resolution is MergeResolution.escalate,
        )

    # -- serialization -----------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        return {
            "registry_version": REGISTRY_VERSION,
            "artifact_id": self.artifact_id,
            "versions": [version.serialize() for version in self._versions],
        }

    @classmethod
    def deserialize(cls, payload: dict[str, Any]) -> "ArtifactRegistry":
        if payload.get("registry_version") != REGISTRY_VERSION:
            raise MergeError(
                f"unsupported registry version '{payload.get('registry_version')}'; "
                f"expected {REGISTRY_VERSION}"
            )
        registry = cls(payload["artifact_id"])
        registry._versions = [ArtifactVersion.deserialize(item) for item in payload["versions"]]
        return registry


def validate_merge_matrix() -> list[str]:
    """Every (base, incoming) status pair must have a declared resolution."""
    problems: list[str] = []
    for base in ArtifactStatus:
        for incoming in ArtifactStatus:
            if (base, incoming) not in MERGE_MATRIX:
                problems.append(
                    f"merge matrix missing resolution for base '{base.value}' + "
                    f"incoming '{incoming.value}'"
                )
    for (base, incoming), resolution in MERGE_MATRIX.items():
        if base is ArtifactStatus.archived and resolution is not MergeResolution.keep_base:
            problems.append(
                f"archived base must be terminal, but ({base.value}, {incoming.value}) "
                f"resolves to {resolution.value}"
            )
    return problems
