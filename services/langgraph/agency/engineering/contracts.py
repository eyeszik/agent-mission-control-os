"""Strict, bounded contracts for agency-to-repository engineering handoffs.

These records describe requests, immutable evidence, and review state. They do
not grant authority. Tenant/project identity and approvals are server-derived;
execution and durable transitions stay with the existing AMC owners.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.execution.canonical import canonical_hash

CONTRACT_VERSION = "amc-engineering-contracts/v1"
_HASH = r"^[a-f0-9]{64}$"
_ID = r"^[A-Z][A-Z0-9_-]{1,63}$"
_SLUG = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_MODULE = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
_SENSITIVE_PARTS = frozenset({".git", ".env", ".venv", "node_modules", "__pycache__", ".ssh", "secrets"})


def safe_repo_path(value: str) -> str:
    """Validate an untrusted repository-relative POSIX path without resolving it."""
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("repository path must be a non-empty POSIX path")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("repository path must not be absolute, empty, or traversing")
    path = PurePosixPath(value)
    if any(part.lower() in _SENSITIVE_PARTS or part.lower().startswith(".env.") for part in path.parts):
        raise ValueError("repository path includes an excluded sensitive/runtime directory")
    return value


class EvidenceState(str, Enum):
    OBSERVED = "OBSERVED"
    ASSUMPTION = "ASSUMPTION"
    PROPOSED = "PROPOSED"
    UNVERIFIED = "UNVERIFIED"
    BLOCKED = "BLOCKED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RetryClass(str, Enum):
    RETRY_SAFE = "RETRY_SAFE"
    COMPENSATABLE = "COMPENSATABLE"
    RECONCILE_BEFORE_RETRY = "RECONCILE_BEFORE_RETRY"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RequestedAction(str, Enum):
    LOCAL_PATCH = "LOCAL_PATCH"
    RUN_CHECKS = "RUN_CHECKS"
    REQUEST_REVIEW = "REQUEST_REVIEW"
    CREATE_DRAFT_PR = "CREATE_DRAFT_PR"


class DeliverableKind(str, Enum):
    REPOSITORY_PATCH = "REPOSITORY_PATCH"
    WEBSITE = "WEBSITE"
    LANDING_PAGE = "LANDING_PAGE"
    TEST_REPORT = "TEST_REPORT"


class OutputDestination(str, Enum):
    PROJECT_ARTIFACT = "PROJECT_ARTIFACT"
    LOCAL_REVIEW = "LOCAL_REVIEW"
    DRAFT_PR = "DRAFT_PR"


class RightsStatus(str, Enum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    UNKNOWN = "UNKNOWN"


class BudgetUnit(str, Enum):
    MICRO_USD = "MICRO_USD"
    INPUT_TOKEN = "INPUT_TOKEN"
    OUTPUT_TOKEN = "OUTPUT_TOKEN"
    CPU_MILLISECOND = "CPU_MILLISECOND"
    STORAGE_BYTE = "STORAGE_BYTE"


class EffectOutcome(str, Enum):
    NO_EFFECT = "NO_EFFECT"
    APPLIED = "APPLIED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
    RECONCILED = "RECONCILED"


class ReviewStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    NOT_RUN = "NOT_RUN"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceRef(_Strict):
    artifact_id: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1, le=2**31 - 1)
    content_hash: str = Field(pattern=_HASH)
    source_kind: str = Field(min_length=1, max_length=80)


class AssetRef(_Strict):
    source: SourceRef
    rights: RightsStatus
    rights_ref: str | None = Field(default=None, max_length=200)
    permitted_use: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def licensed_asset_has_rights_reference(self):
        if self.rights is RightsStatus.LICENSED and not self.rights_ref:
            raise ValueError("licensed assets require a rights reference")
        if self.rights is RightsStatus.UNKNOWN:
            raise ValueError("unknown asset rights block dependent deliverables")
        return self


class RouteSpec(_Strict):
    path: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)
    required: bool = True

    @field_validator("path")
    @classmethod
    def route_is_local_path(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value.split("/") or "?" in value or "#" in value:
            raise ValueError("route must be an absolute local path without traversal, query, or fragment")
        return value


class FeatureSpec(_Strict):
    feature_id: str = Field(pattern=_SLUG)
    description: str = Field(min_length=1, max_length=500)
    integration_ref: str | None = Field(default=None, max_length=160)


class AcceptanceCriterion(_Strict):
    criterion_id: str = Field(pattern=_ID)
    description: str = Field(min_length=1, max_length=600)
    evidence_required: tuple[str, ...] = Field(min_length=1, max_length=12)


class DeliverableSpec(_Strict):
    kind: DeliverableKind
    title: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=800)
    approved_brief: str = Field(min_length=1, max_length=4000)
    brief_ref: SourceRef | None = None
    tokens_ref: SourceRef | None = None
    copy_refs: tuple[SourceRef, ...] = Field(default=(), max_length=40)
    assets: tuple[AssetRef, ...] = Field(default=(), max_length=40)
    routes: tuple[RouteSpec, ...] = Field(default=(), max_length=40)
    features: tuple[FeatureSpec, ...] = Field(default=(), max_length=80)
    integrations: tuple[str, ...] = Field(default=(), max_length=40)
    acceptance: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def website_has_route_contract(self):
        if self.kind in {DeliverableKind.WEBSITE, DeliverableKind.LANDING_PAGE}:
            if not self.routes:
                raise ValueError("website deliverables require explicit routes")
            if self.tokens_ref is None:
                raise ValueError("website deliverables require a canonical token reference")
        return self


class BudgetCeiling(_Strict):
    max_provider_cost_microusd: int = Field(ge=0, le=10**12)
    max_compute_seconds: int = Field(ge=0, le=86_400)
    max_storage_bytes: int = Field(ge=0, le=10**10)
    price_version: str | None = Field(default=None, max_length=80)


class HandoffRequest(_Strict):
    record_type: Literal["HandoffRequest"] = "HandoffRequest"
    schema_version: Literal["amc-engineering-handoff/v1"] = "amc-engineering-handoff/v1"
    campaign_id: str | None = Field(default=None, max_length=160)
    source_refs: tuple[SourceRef, ...] = Field(min_length=1, max_length=80)
    repository_id: str = Field(pattern=_SLUG)
    objective: str = Field(min_length=1, max_length=2000)
    deliverable: DeliverableSpec
    requested_actions: tuple[RequestedAction, ...] = Field(min_length=1, max_length=4)
    output_destinations: tuple[OutputDestination, ...] = Field(min_length=1, max_length=3)
    budget_ceiling: BudgetCeiling
    retry_of_task_id: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def no_duplicate_refs_or_actions(self):
        refs = [r.artifact_id for r in self.source_refs]
        if len(refs) != len(set(refs)):
            raise ValueError("source refs must be unique")
        if len(self.requested_actions) != len(set(self.requested_actions)):
            raise ValueError("requested actions must be unique")
        return self


class AuthorityReceipt(_Strict):
    policy_version: str = Field(min_length=1, max_length=80)
    evidence_state: EvidenceState
    authorized_actions: tuple[RequestedAction, ...] = ()
    approval_refs: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    checked_at: str = Field(min_length=1, max_length=80)


class EvidenceRef(_Strict):
    evidence_id: str = Field(min_length=1, max_length=160)
    state: EvidenceState
    path_or_uri: str | None = Field(default=None, max_length=500)
    content_hash: str | None = Field(default=None, pattern=_HASH)
    description: str = Field(min_length=1, max_length=500)


class TaskRecord(_Strict):
    record_type: Literal["Task"] = "Task"
    schema_version: Literal["amc-engineering-task/v1"] = "amc-engineering-task/v1"
    task_id: str = Field(min_length=1, max_length=160)
    owner: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    source_refs: tuple[SourceRef, ...] = Field(min_length=1, max_length=80)
    repository_id: str = Field(pattern=_SLUG)
    objective: str = Field(min_length=1, max_length=2000)
    scope: tuple[str, ...] = Field(min_length=1, max_length=100)
    inputs: tuple[str, ...] = Field(max_length=100)
    deps: tuple[str, ...] = Field(max_length=100)
    outputs: tuple[str, ...] = Field(min_length=1, max_length=40)
    acceptance: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=80)
    checks: tuple[str, ...] = Field(max_length=40)
    risk: RiskLevel
    authority: AuthorityReceipt
    budget: BudgetCeiling
    retry_class: RetryClass
    stop_conditions: tuple[str, ...] = Field(min_length=1, max_length=40)
    status: RunState
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=100)
    input_hash: str = Field(pattern=_HASH)
    policy_version: str = Field(min_length=1, max_length=80)
    created_at: str = Field(min_length=1, max_length=80)

    @field_validator("scope")
    @classmethod
    def task_paths_are_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(safe_repo_path(value) for value in values)


class LeaseRecord(_Strict):
    record_type: Literal["Lease"] = "Lease"
    owner: str = Field(min_length=1, max_length=160)
    fence: int = Field(ge=0, le=2**63 - 1)
    expiry: str = Field(min_length=1, max_length=80)
    heartbeat: str | None = Field(default=None, max_length=80)
    version: int = Field(ge=1, le=2**31 - 1)


class SourceSpan(_Strict):
    start_line: int = Field(ge=1, le=10**8)
    end_line: int = Field(ge=1, le=10**8)
    start_column: int = Field(ge=0, le=10**6)
    end_column: int = Field(ge=0, le=10**6)

    @model_validator(mode="after")
    def span_is_ordered(self):
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise ValueError("source span end must not precede its start")
        return self


class ContextFile(_Strict):
    path: str = Field(min_length=1, max_length=240)
    blob_hash: str = Field(pattern=_HASH)
    byte_size: int = Field(ge=0, le=2_000_000)
    spans: tuple[SourceSpan, ...] = Field(default=(), max_length=100)

    @field_validator("path")
    @classmethod
    def context_path_is_safe(cls, value: str) -> str:
        return safe_repo_path(value)


def context_manifest_hash(revision: str, files: tuple[ContextFile, ...], method: str,
                          omissions: tuple[str, ...], byte_size: int) -> str:
    """Hash the complete ordered context manifest using AMC-CANON-1."""
    return canonical_hash({
        "revision": revision,
        "files": [item.model_dump(mode="json") for item in files],
        "method": method,
        "omissions": list(omissions),
        "byte_size": byte_size,
    })


class ContextRecord(_Strict):
    record_type: Literal["Context"] = "Context"
    revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    files: tuple[ContextFile, ...] = Field(max_length=500)
    method: Literal["SCOPED_RIPGREP", "SYMBOL", "AST", "EXPLICIT_FILE"]
    omissions: tuple[str, ...] = Field(default=(), max_length=300)
    byte_size: int = Field(ge=0, le=20_000_000)
    context_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def file_list_is_unique_and_bounded(self):
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("context paths must be unique")
        if paths != sorted(paths, key=lambda value: value.encode("utf-8")):
            raise ValueError("context paths must use deterministic UTF-8 ordering")
        if sum(f.byte_size for f in self.files) > self.byte_size:
            raise ValueError("context byte size cannot be less than its included files")
        if self.context_hash != context_manifest_hash(self.revision, self.files, self.method,
                                                      self.omissions, self.byte_size):
            raise ValueError("context hash does not match its immutable manifest")
        return self


class PlanStep(_Strict):
    step_id: str = Field(pattern=_ID)
    objective: str = Field(min_length=1, max_length=500)
    depends_on: tuple[str, ...] = Field(default=(), max_length=40)


class ExecutionLimits(_Strict):
    max_wall_seconds: int = Field(ge=1, le=600)
    max_cpu_seconds: int = Field(ge=1, le=300)
    max_memory_bytes: int = Field(ge=16_000_000, le=1_073_741_824)
    max_processes: int = Field(ge=1, le=32)
    max_files: int = Field(ge=1, le=200)
    max_file_bytes: int = Field(ge=1, le=200_000)
    max_workspace_bytes: int = Field(ge=1, le=16_000_000)
    max_output_bytes: int = Field(ge=1, le=262_144)


class CheckSpec(_Strict):
    requirement_id: str = Field(pattern=_ID)
    argv: tuple[str, ...] = Field(min_length=6, max_length=40)
    cwd: str = ""
    timeout_seconds: int = Field(ge=1, le=600)

    @field_validator("cwd")
    @classmethod
    def check_cwd_is_safe(cls, value: str) -> str:
        return safe_repo_path(value) if value else value

    @field_validator("argv")
    @classmethod
    def check_argv_is_narrow(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value[:5] != ("python", "-S", "-m", "unittest", "-v"):
            raise ValueError("only the stdlib Python unittest invocation is supported")
        modules = value[5:]
        if not modules or any(not re.fullmatch(_MODULE, module) for module in modules):
            raise ValueError("unittest argv must contain one or more dotted test module names")
        return value


class PlanRecord(_Strict):
    record_type: Literal["Plan"] = "Plan"
    plan_id: str = Field(min_length=1, max_length=160)
    plan_hash: str | None = Field(default=None, pattern=_HASH)
    base_revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    base_tree_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=40)
    allowed_paths: tuple[str, ...] = Field(min_length=1, max_length=100)
    allowed_argv: tuple[Literal["PYTHON_UNITTEST"], ...] = Field(min_length=1, max_length=8)
    checks: tuple[CheckSpec, ...] = Field(min_length=1, max_length=40)
    limits: ExecutionLimits
    stop_conditions: tuple[str, ...] = Field(min_length=1, max_length=40)

    @field_validator("allowed_paths")
    @classmethod
    def allowed_paths_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(safe_repo_path(value) for value in values)

    @model_validator(mode="after")
    def plan_graph_is_acyclic(self):
        by_id = {step.step_id: step for step in self.steps}
        if len(by_id) != len(self.steps):
            raise ValueError("plan step ids must be unique")
        if any(len(step.depends_on) != len(set(step.depends_on)) for step in self.steps):
            raise ValueError("plan step dependencies must be unique")
        if any(dep not in by_id for step in self.steps for dep in step.depends_on):
            raise ValueError("plan step dependency is missing")
        if len({check.requirement_id for check in self.checks}) != len(self.checks):
            raise ValueError("check requirement ids must be unique within a plan")
        remaining = {key: set(step.depends_on) for key, step in by_id.items()}
        while remaining:
            ready = {key for key, deps in remaining.items() if not deps}
            if not ready:
                raise ValueError("plan step dependencies contain a cycle")
            for key in ready:
                remaining.pop(key)
            for deps in remaining.values():
                deps.difference_update(ready)
        if len(self.allowed_paths) != len(set(self.allowed_paths)):
            raise ValueError("allowed paths must be unique")
        if any(check.timeout_seconds > self.limits.max_wall_seconds for check in self.checks):
            raise ValueError("check timeout cannot exceed the plan wall-clock budget")
        if any(check.argv[:5] != ("python", "-S", "-m", "unittest", "-v") for check in self.checks):
            raise ValueError("plan contains a check outside the supported argv allowlist")
        expected_hash = canonical_hash(self.model_dump(mode="json", exclude={"plan_hash"}))
        if self.plan_hash is None:
            object.__setattr__(self, "plan_hash", expected_hash)
        elif self.plan_hash != expected_hash:
            raise ValueError("plan hash does not match its immutable contents")
        return self


class IntentReceiptRecord(_Strict):
    record_type: Literal["IntentReceipt"] = "IntentReceipt"
    operation: str = Field(min_length=1, max_length=160)
    target: str = Field(min_length=1, max_length=500)
    preimage_hash: str = Field(pattern=_HASH)
    authority_ref: str | None = Field(default=None, max_length=200)
    outcome: EffectOutcome
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=80)
    observed_at: str = Field(min_length=1, max_length=80)


class CheckRecord(_Strict):
    record_type: Literal["Check"] = "Check"
    requirement_id: str = Field(pattern=_ID)
    plan_hash: str = Field(pattern=_HASH)
    argv: tuple[str, ...] = Field(min_length=1, max_length=40)
    cwd: str = ""
    tree_hash: str = Field(pattern=_HASH)
    environment_hash: str = Field(pattern=_HASH)
    exit_code: int | None = Field(default=None, ge=-255, le=255)
    status: CheckStatus
    output_sha256: str | None = Field(default=None, pattern=_HASH)
    output_bytes: int = Field(ge=0, le=262_144)
    summary: str = Field(max_length=300)
    started_at: str = Field(min_length=1, max_length=80)
    finished_at: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def passing_check_has_complete_success_evidence(self):
        if self.status is CheckStatus.PASS and (self.exit_code != 0 or self.output_sha256 is None):
            raise ValueError("a passing check requires exit code zero and complete output hash")
        if self.status in {CheckStatus.BLOCKED, CheckStatus.NOT_RUN} and self.exit_code is not None:
            raise ValueError("blocked or not-run checks cannot claim a process exit code")
        return self


class BudgetRecord(_Strict):
    record_type: Literal["Budget"] = "Budget"
    window_start: str = Field(min_length=1, max_length=80)
    window_end: str = Field(min_length=1, max_length=80)
    unit: BudgetUnit
    currency: Literal["USD"] | None = None
    ceiling: int = Field(ge=0, le=10**15)
    reserved: int = Field(ge=0, le=10**15)
    settled: int = Field(ge=0, le=10**15)
    unknown: int = Field(ge=0, le=10**15)
    price_version: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def budget_exposure_stays_below_ceiling(self):
        if self.reserved + self.settled + self.unknown > self.ceiling:
            raise ValueError("settled, reserved, and unknown exposure exceed the task ceiling")
        if (self.unit is BudgetUnit.MICRO_USD) != (self.currency == "USD"):
            raise ValueError("MICRO_USD requires currency USD; non-money budgets have no currency")
        if self.window_start >= self.window_end:
            raise ValueError("budget window must have a positive duration")
        return self


class ArtifactRecord(_Strict):
    record_type: Literal["Artifact"] = "Artifact"
    artifact_type: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern=_HASH)
    byte_size: int = Field(ge=0, le=50_000_000)
    media_type: str = Field(min_length=1, max_length=120)
    storage_ref: str = Field(min_length=1, max_length=500)
    provenance: tuple[str, ...] = Field(default=(), max_length=100)
    retention_policy: str = Field(min_length=1, max_length=120)


class ApprovalRecord(_Strict):
    record_type: Literal["Approval"] = "Approval"
    reviewer: str | None = Field(default=None, max_length=160)
    action: RequestedAction
    target: str = Field(min_length=1, max_length=500)
    plan_id: str = Field(min_length=1, max_length=160)
    plan_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    tree_hash: str = Field(pattern=_HASH)
    patch_hash: str = Field(pattern=_HASH)
    artifact_ref: str = Field(min_length=1, max_length=500)
    policy_version: str = Field(min_length=1, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    revoked_at: str | None = Field(default=None, max_length=80)
    decision: Literal["PENDING", "APPROVED", "REJECTED", "STALE", "REVOKED"]

    @model_validator(mode="after")
    def approved_record_has_separate_reviewer(self):
        if self.decision == "APPROVED" and (not self.reviewer or self.revoked_at is not None):
            raise ValueError("approved action requires a reviewer and cannot be revoked")
        if self.decision == "REVOKED" and self.revoked_at is None:
            raise ValueError("revoked approvals require a revocation timestamp")
        return self


class ReviewRecord(_Strict):
    record_type: Literal["Review"] = "Review"
    plan_id: str = Field(min_length=1, max_length=160)
    plan_hash: str = Field(pattern=_HASH)
    context_hash: str = Field(pattern=_HASH)
    base_revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    head_revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    base_tree_hash: str = Field(pattern=_HASH)
    head_tree_hash: str = Field(pattern=_HASH)
    patch_hash: str = Field(pattern=_HASH)
    checks: tuple[CheckRecord, ...] = Field(min_length=1, max_length=80)
    limits: ExecutionLimits
    source_refs: tuple[SourceRef, ...] = Field(min_length=1, max_length=80)
    status: ReviewStatus
    findings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def passed_review_has_nonempty_unchanged_evidence(self):
        if any(check.plan_hash != self.plan_hash for check in self.checks):
            raise ValueError("review checks must bind the exact reviewed plan")
        if self.status is ReviewStatus.PASSED:
            if self.base_tree_hash == self.head_tree_hash:
                raise ValueError("a no-op patch cannot pass review")
            if not self.checks or any(check.status is not CheckStatus.PASS for check in self.checks):
                raise ValueError("passed review requires non-empty passing checks")
            if any(check.tree_hash != self.head_tree_hash for check in self.checks):
                raise ValueError("passed review checks must bind the reviewed head tree")
        return self


class IsolationReceipt(_Strict):
    record_type: Literal["IsolationReceipt"] = "IsolationReceipt"
    available: bool
    environment_hash: str | None = Field(default=None, pattern=_HASH)
    mode: Literal["USER_MOUNT_NET_PID_NAMESPACE_CHROOT"]
    filesystem: Literal["READ_ONLY_WORKSPACE_EPHEMERAL_TMPFS"]
    network: Literal["ISOLATED_NO_EGRESS"]
    memory_limit: str
    cpu_limit: str
    process_limit: str
    disk_limit: str
    output_limit: str
    seccomp: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    shared_kernel: Literal[True] = True
    blockers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def evidence_matches_availability(self):
        if self.available and (self.environment_hash is None or self.blockers):
            raise ValueError("available isolation requires an environment hash and no blockers")
        if not self.available and not self.blockers:
            raise ValueError("unavailable isolation requires an explicit blocker")
        return self


class ExecutionResultRecord(_Strict):
    record_type: Literal["ExecutionResult"] = "ExecutionResult"
    status: ReviewStatus
    execution_tier: Literal["SYNTHETIC_FIXTURE"]
    plan_id: str = Field(min_length=1, max_length=160)
    plan_hash: str = Field(pattern=_HASH)
    base_revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    context_hash: str = Field(pattern=_HASH)
    base_tree_hash: str = Field(pattern=_HASH)
    patch_hash: str = Field(pattern=_HASH)
    result_tree_hash: str = Field(pattern=_HASH)
    changed_paths: tuple[str, ...] = Field(min_length=1, max_length=200)
    checks: tuple[CheckRecord, ...] = Field(min_length=1, max_length=40)
    isolation: IsolationReceipt

    @field_validator("changed_paths")
    @classmethod
    def changed_paths_are_safe(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(safe_repo_path(value) for value in values)

    @model_validator(mode="after")
    def pass_requires_all_evidence(self):
        if any(check.plan_hash != self.plan_hash or check.tree_hash != self.result_tree_hash for check in self.checks):
            raise ValueError("execution checks must bind the exact plan and resulting tree")
        if self.status is ReviewStatus.PASSED:
            if not self.isolation.available or any(check.status is not CheckStatus.PASS for check in self.checks):
                raise ValueError("passed execution requires available isolation and passing non-empty checks")
            if any(check.tree_hash != self.result_tree_hash for check in self.checks):
                raise ValueError("passed execution checks must bind the resulting tree")
            if self.base_tree_hash == self.result_tree_hash:
                raise ValueError("a no-op patch cannot pass execution")
        return self


EngineeringRecord = Annotated[
    HandoffRequest | TaskRecord | LeaseRecord | ContextRecord | PlanRecord | IntentReceiptRecord | CheckRecord | BudgetRecord | ArtifactRecord | ApprovalRecord | ReviewRecord | IsolationReceipt | ExecutionResultRecord,
    Field(discriminator="record_type"),
]
ENGINEERING_RECORD_SCHEMA = TypeAdapter(list[EngineeringRecord]).json_schema()
ENGINEERING_RECORD_SCHEMA["$schema"] = "https://json-schema.org/draft/2020-12/schema"


__all__ = [
    "CONTRACT_VERSION",
    "ENGINEERING_RECORD_SCHEMA",
    "AcceptanceCriterion",
    "ApprovalRecord",
    "ArtifactRecord",
    "AssetRef",
    "AuthorityReceipt",
    "BudgetCeiling",
    "BudgetRecord",
    "BudgetUnit",
    "CheckRecord",
    "CheckSpec",
    "CheckStatus",
    "ContextFile",
    "ContextRecord",
    "DeliverableKind",
    "DeliverableSpec",
    "EffectOutcome",
    "EngineeringRecord",
    "EvidenceRef",
    "EvidenceState",
    "ExecutionLimits",
    "ExecutionResultRecord",
    "FeatureSpec",
    "HandoffRequest",
    "IntentReceiptRecord",
    "IsolationReceipt",
    "LeaseRecord",
    "OutputDestination",
    "PlanRecord",
    "PlanStep",
    "RequestedAction",
    "RetryClass",
    "ReviewRecord",
    "ReviewStatus",
    "RightsStatus",
    "RiskLevel",
    "RouteSpec",
    "RunState",
    "SourceRef",
    "SourceSpan",
    "TaskRecord",
    "context_manifest_hash",
    "safe_repo_path",
]
