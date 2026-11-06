"""Shared, engine-independent contracts for the mission council.

Every engine produces the same validated objects. Model output is untrusted:
it only reaches mission state after it parses into these models, and scaffold
file paths are checked against a strict boundary before anything is written.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Engine = Literal["langgraph", "crewai", "autogen"]
ENGINES: tuple[str, ...] = ("langgraph", "crewai", "autogen")
Seat = Literal["george", "fable", "arty"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
Sensitivity = Literal["READ", "WRITE", "SHELL", "EXTERNAL"]
ModelMode = Literal["MOCK_DETERMINISTIC", "PROVIDER"]

# Run statuses a council mission moves through. ``needs_approval`` is the status
# /approvals/{id}/decide requires, so a council approval is decided there.
MissionStatus = Literal["queued", "running", "needs_approval", "resuming", "completed", "rejected", "failed", "cancelled"]
TERMINAL_STATUSES = frozenset({"completed", "rejected", "failed", "cancelled"})
Phase = Literal["STRATEGY", "AUDIT", "GATE", "PROTOTYPE", "DONE"]

POLICY_VERSION = "amc-council-policy/v1"
# Every event a council mission writes to run_events, in lifecycle order. ``approval_decided`` is
# recorded by /approvals/{id}/decide. The Zod twin (CouncilEventTypeSchema) must list the same values.
COUNCIL_EVENT_TYPES: tuple[str, ...] = (
    "MISSION_QUEUED",
    "MISSION_STARTED",
    "SEAT_STARTED",
    "SEAT_COMPLETED",
    "RISK_ASSESSED",
    "CHECKPOINT_SAVED",
    "APPROVAL_REQUIRED",
    "approval_decided",
    "MISSION_RESUMING",
    "APPROVAL_APPLIED",
    "TOOL_INVOKED",
    "MISSION_COMPLETED",
    "MISSION_REJECTED",
    "MISSION_BLOCKED",
    "MISSION_FAILED",
    "CANCEL_REQUESTED",
    "MISSION_CANCELLED",
    "MISSION_RETRYING",
    "MISSION_RECOVERING",
)
PIPELINE = "mission_council"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskNode(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    title: str = Field(min_length=3, max_length=160)
    seat: Seat
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    acceptance: str = Field(min_length=3, max_length=300)


class Strategy(_Strict):
    """George's decomposition: goals, an architecture outline and a task DAG."""

    summary: str = Field(min_length=10, max_length=1200)
    goals: list[str] = Field(min_length=1, max_length=8)
    architecture: list[str] = Field(min_length=1, max_length=10)
    tasks: list[TaskNode] = Field(min_length=2, max_length=24)

    @model_validator(mode="after")
    def _dag(self) -> Strategy:
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        known = set(ids)
        for task in self.tasks:
            missing = [d for d in task.depends_on if d not in known]
            if missing:
                raise ValueError(f"task {task.id} depends on unknown tasks {missing}")
        # Kahn's algorithm: every task must be schedulable, so the graph is acyclic.
        indegree = {t.id: len(t.depends_on) for t in self.tasks}
        children: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                children[dep].append(task.id)
        ready = [i for i, d in indegree.items() if d == 0]
        seen = 0
        while ready:
            node = ready.pop()
            seen += 1
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if seen != len(self.tasks):
            raise ValueError("task graph contains a cycle")
        return self


class RequestedAction(_Strict):
    """A side effect the prototype step wants. Each one must be allowlisted and approved."""

    tool_id: str = Field(min_length=3, max_length=80)
    sensitivity: Sensitivity
    target: str = Field(min_length=1, max_length=300)


class RiskFinding(_Strict):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: Severity
    detail: str = Field(min_length=3, max_length=400)
    source: Literal["POLICY", "MODEL"]


class RiskAssessment(_Strict):
    level: Severity
    findings: list[RiskFinding] = Field(default_factory=list, max_length=40)
    requires_approval: bool
    blocked: bool = False
    requested_actions: list[RequestedAction] = Field(default_factory=list, max_length=20)
    narrative: str = Field(default="", max_length=1200)
    policy_version: str = POLICY_VERSION


_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*(/[A-Za-z0-9][A-Za-z0-9_\-]*)*\.(tsx|ts|css|md|json)$")
MAX_FILE_BYTES = 16_000
MAX_SCAFFOLD_BYTES = 96_000


class ScaffoldFile(_Strict):
    path: str = Field(min_length=3, max_length=160)
    content: str = Field(max_length=MAX_FILE_BYTES)

    @field_validator("path")
    @classmethod
    def _bounded(cls, value: str) -> str:
        # Relative, no traversal, no hidden files, text extensions only.
        if not _SAFE_PATH.match(value) or ".." in value.split("/"):
            raise ValueError(f"unsafe scaffold path {value!r}")
        return value


class ComponentSpec(_Strict):
    name: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,63}$")
    purpose: str = Field(min_length=3, max_length=300)
    props: list[str] = Field(default_factory=list, max_length=12)


class Scaffold(_Strict):
    """Arty's validated UI/code scaffold. It is text, never executed."""

    summary: str = Field(min_length=10, max_length=1200)
    components: list[ComponentSpec] = Field(min_length=1, max_length=16)
    design_tokens: list[str] = Field(default_factory=list, max_length=24)
    files: list[ScaffoldFile] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _budget(self) -> Scaffold:
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("scaffold paths must be unique")
        if sum(len(f.content.encode("utf-8")) for f in self.files) > MAX_SCAFFOLD_BYTES:
            raise ValueError("scaffold exceeds the size budget")
        return self


class AgentResult(_Strict):
    seat: Seat
    engine: Engine
    model_mode: ModelMode
    attempts: int = Field(ge=1)
    started_at: str
    completed_at: str
    output: dict[str, Any]


class ApprovalDecision(_Strict):
    """The decision a paused mission is resumed with. Bound to one approval and one subject."""

    approval_id: str
    decision: Literal["approve", "reject"]
    decided_by: str
    subject_hash: str
    policy_version: str = POLICY_VERSION


class ToolInvocation(_Strict):
    tool_id: str
    seat: Seat | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None


class Idea(_Strict):
    idea_id: str
    tenant_id: str
    project_id: str
    title: str
    description: str
    status: Literal["OPEN", "PROMOTED"]
    created_by: str
    created_at: str
    updated_at: str


class IdeaCreate(_Strict):
    project_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=4000)


class DispatchRequest(_Strict):
    """Dispatch one idea to one engine. ``materialize_scaffold`` asks Arty's files to be
    written to the mission workspace, a WRITE side effect that always needs approval."""

    idea_id: str = Field(min_length=1, max_length=80)
    engine: str = Field(min_length=1, max_length=32)
    materialize_scaffold: bool = True


class CheckpointRecord(_Strict):
    checkpoint_id: str
    mission_id: str
    seq: int
    phase: Phase
    engine: Engine
    state_hash: str
    prev_hash: str
    native_checkpoint_id: str | None = None
    created_at: str


class TimelineEvent(_Strict):
    sequence: int
    event_type: str
    node_id: str | None
    observed_at: str
    payload: dict[str, Any]


__all__ = [
    "COUNCIL_EVENT_TYPES",
    "ENGINES",
    "PIPELINE",
    "POLICY_VERSION",
    "SEVERITY_ORDER",
    "TERMINAL_STATUSES",
    "AgentResult",
    "ApprovalDecision",
    "CheckpointRecord",
    "ComponentSpec",
    "DispatchRequest",
    "Engine",
    "Idea",
    "IdeaCreate",
    "MissionStatus",
    "ModelMode",
    "Phase",
    "RequestedAction",
    "RiskAssessment",
    "RiskFinding",
    "Scaffold",
    "ScaffoldFile",
    "Seat",
    "Sensitivity",
    "Severity",
    "Strategy",
    "TaskNode",
    "TimelineEvent",
    "ToolInvocation",
]
