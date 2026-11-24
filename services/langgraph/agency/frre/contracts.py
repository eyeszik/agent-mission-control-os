"""FRRE W1 contracts: strict, versioned, fail closed (pure).

Every model forbids unknown fields, is frozen and validates in strict mode (no lax coercion
of ``"2"`` to 2 or ``"yes"`` to True). Defaults are pessimistic: no verdict defaults to PASS,
no capability defaults to enabled, and success-shaped states need the evidence that earns them.

These models are not API-visible in W1 (no route, no persisted row), so per CLAUDE.md they do
not yet need Zod twins; W2 adds the twins and recorded fixtures with the first route or table.
Schemas are not runtime authorization: :mod:`.guards` decides whether a move may happen.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from fnmatch import fnmatchcase
from typing import Annotated, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .fsm import PERMIT_GATES, IncidentState, assert_transition
from .policy import CONCURRENCY_PER_WORKSPACE, DEFAULT_MAX_ATTEMPTS, DEFAULT_MAX_RECOVERIES, is_protected

SCHEMA: Literal["amc-frre/v1"] = "amc-frre/v1"

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Ident = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
RepoPath = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.*/-]{1,300}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FailureClass(str, Enum):
    CI_GATE = "CI_GATE"
    CI_TEST = "CI_TEST"
    DEPENDENCY = "DEPENDENCY"
    BUILD = "BUILD"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    MIGRATION = "MIGRATION"
    API_CONTRACT = "API_CONTRACT"
    SECURITY = "SECURITY"
    ENVIRONMENT = "ENVIRONMENT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CauseClass(str, Enum):
    CODE = "CODE"
    CONFIG = "CONFIG"
    DEPENDENCY = "DEPENDENCY"
    ENVIRONMENT = "ENVIRONMENT"
    FLAKY = "FLAKY"
    AUTHORIZATION = "AUTHORIZATION"
    STALE_CHECK = "STALE_CHECK"
    OUTAGE = "OUTAGE"
    UNKNOWN = "UNKNOWN"


class PermitStage(str, Enum):
    READ = "READ"
    REPRODUCE = "REPRODUCE"
    MUTATE = "MUTATE"
    VALIDATE = "VALIDATE"
    RELEASE = "RELEASE"


class EffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE = "REVERSIBLE"
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE = "IRREVERSIBLE"


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REPORTED = "REPORTED"
    ASSUMED = "ASSUMED"
    INFERENCE = "INFERENCE"
    SPECULATIVE = "SPECULATIVE"
    UNVERIFIED = "UNVERIFIED"
    STALE_RISK = "STALE_RISK"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BLOCKED = "BLOCKED"


class TestResult(str, Enum):
    __test__ = False  # not a pytest class
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_RUN = "NOT_RUN"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Maturity(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    INTEGRATED = "INTEGRATED"
    ENABLED = "ENABLED"
    INVOKED = "INVOKED"
    TESTED = "TESTED"
    DEPLOYED = "DEPLOYED"
    OPERATIONALLY_VERIFIED = "OPERATIONALLY_VERIFIED"


_MATURITY_ORDER = tuple(Maturity)
Verdict = Literal["PASS", "FAIL", "BLOCKED"]
Confidence = Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"]  # qualitative until calibrated


class Witness(_Strict):
    claim: Text
    status: EvidenceStatus
    source: Text
    path: Optional[RepoPath] = None
    sha: Optional[GitSha] = None
    method: Text
    observed_result: Text
    environment: Text
    time: datetime
    limitations: tuple[Text, ...] = ()


class Budget(_Strict):
    attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=0, le=DEFAULT_MAX_ATTEMPTS)
    recoveries: int = Field(default=DEFAULT_MAX_RECOVERIES, ge=0, le=DEFAULT_MAX_RECOVERIES)
    runtime_s: int = Field(ge=1, le=86_400)
    tokens: int = Field(ge=0)
    cost_usd_cents: int = Field(ge=0)
    files: int = Field(ge=1, le=50)
    concurrency: int = Field(default=CONCURRENCY_PER_WORKSPACE, ge=1, le=CONCURRENCY_PER_WORKSPACE)
    effects: int = Field(default=0, ge=0, le=1)


class Incident(_Strict):
    schema_version: Literal["amc-frre/v1"] = SCHEMA
    id: Ident
    tenant_id: Ident
    project_id: Ident
    source: Text
    event_ref: Text
    fingerprint: Digest
    time: datetime
    baseline_sha: GitSha
    environment: Text
    severity: Severity
    failure_class: FailureClass
    symptoms: tuple[Text, ...] = Field(min_length=1)
    evidence: tuple[Witness, ...] = ()
    state: IncidentState = IncidentState.OBSERVED
    version: int = Field(default=0, ge=0)


class Hypothesis(_Strict):
    cause: Text
    classification: CauseClass
    evidence_for: tuple[Text, ...] = ()
    evidence_against: tuple[Text, ...] = ()
    reproduction: Literal["REPRODUCED", "NOT_REPRODUCED", "NOT_RUN"] = "NOT_RUN"
    confidence: Confidence = "UNKNOWN"
    limitations: tuple[Text, ...] = ()


class Diagnosis(_Strict):
    incident_id: Ident
    tenant_id: Ident
    hypotheses: tuple[Hypothesis, ...] = Field(min_length=1)
    selected_cause: Optional[int] = Field(default=None, ge=0)
    nodes: tuple[Text, ...] = ()
    closure: tuple[RepoPath, ...] = ()
    unknowns: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _selected_cause_is_reproduced(self) -> "Diagnosis":
        if self.selected_cause is None:
            return self
        if self.selected_cause >= len(self.hypotheses):
            raise ValueError("selected_cause does not index a hypothesis")
        if self.hypotheses[self.selected_cause].reproduction != "REPRODUCED":
            raise ValueError("an unreproduced cause cannot be selected for repair (qualified inference only)")
        return self


class RepairPlan(_Strict):
    id: Ident
    incident_id: Ident
    tenant_id: Ident
    project_id: Ident
    baseline_sha: GitSha
    objective: Text
    allowed_paths: tuple[RepoPath, ...] = Field(min_length=1, max_length=50)
    protected_paths: tuple[RepoPath, ...] = ()
    operations: tuple[Text, ...] = Field(min_length=1)
    risk: EffectClass
    preconditions: tuple[Text, ...] = ()
    acceptance: tuple[Digest, ...] = Field(min_length=1)
    negative_controls: tuple[Digest, ...] = Field(min_length=1)
    regressions: tuple[Text, ...] = ()
    recovery: Text
    budget: Budget
    required_authority: PermitStage

    @model_validator(mode="after")
    def _scope_is_safe(self) -> "RepairPlan":
        floor = [p for p in self.allowed_paths if is_protected(p)]
        if floor:
            raise ValueError(f"allowed_paths overlap the protected floor: {floor}")
        own = [p for p in self.allowed_paths for q in self.protected_paths if fnmatchcase(p, q) or fnmatchcase(q, p)]
        if own:
            raise ValueError(f"allowed_paths overlap this plan's protected_paths: {own}")
        if self.risk is EffectClass.IRREVERSIBLE:
            raise ValueError("FRRE never plans an irreversible effect; it needs a human-run change")
        return self


class Permit(_Strict):
    id: Ident
    stage: PermitStage
    actor: Ident
    tool: Ident
    target: Text
    args_digest: Digest
    tenant_id: Ident
    project_id: Ident
    scope: tuple[RepoPath, ...] = ()
    baseline_sha: GitSha
    plan_digest: Optional[Digest] = None
    policy_digest: Digest
    candidate_digest: Optional[Digest] = None
    environment: Text
    issued_at: datetime
    expires_at: datetime
    revocation_ref: Optional[Text] = None
    approval_ref: Optional[Ident] = None

    @model_validator(mode="after")
    def _stage_bindings(self) -> "Permit":
        if self.expires_at <= self.issued_at:
            raise ValueError("permit expires before it is issued")
        needs_candidate = self.stage in (PermitStage.VALIDATE, PermitStage.RELEASE)
        if needs_candidate != (self.candidate_digest is not None):
            raise ValueError("candidate_digest is required for VALIDATE/RELEASE and forbidden before a candidate exists")
        if self.stage in (PermitStage.MUTATE, PermitStage.VALIDATE, PermitStage.RELEASE) and self.plan_digest is None:
            raise ValueError(f"{self.stage.value} permit must bind a plan_digest")
        if self.stage is PermitStage.RELEASE and self.approval_ref is None:
            raise ValueError("RELEASE permit must reference a human approval")
        return self


class Candidate(_Strict):
    id: Ident
    incident_id: Ident
    plan_digest: Digest
    patch_digest: Digest
    changed_files: tuple[RepoPath, ...] = Field(min_length=1, max_length=50)
    candidate_digest: Digest
    semantic_diff_digest: Digest
    attempt: int = Field(ge=1, le=DEFAULT_MAX_ATTEMPTS)
    cost_usd_cents: int = Field(ge=0)
    provenance: Text

    @model_validator(mode="after")
    def _no_protected_writes(self) -> "Candidate":
        touched = [p for p in self.changed_files if is_protected(p)]
        if touched:
            raise ValueError(f"candidate writes protected paths: {touched}")
        return self


class Validation(_Strict):
    candidate_digest: Digest
    baseline_results: Mapping[Text, TestResult] = Field(min_length=1)
    target_results: Mapping[Text, TestResult] = Field(min_length=1)
    regressions: tuple[Text, ...] = ()
    security: tuple[Text, ...] = ()
    contracts: tuple[Text, ...] = ()
    verifier: Ident
    evidence: tuple[Witness, ...] = ()
    skipped: tuple[Text, ...] = ()
    unknown: tuple[Text, ...] = ()
    verdict: Verdict
    limitations: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _pass_is_earned(self) -> "Validation":
        if self.verdict != "PASS":
            return self
        if self.skipped or self.unknown or self.regressions:
            raise ValueError("PASS is impossible with skipped, unknown or regressed mandatory checks")
        if any(r is not TestResult.PASS for r in self.target_results.values()):
            raise ValueError("PASS needs every target check to PASS on the candidate")
        if not any(r is TestResult.FAIL for r in self.baseline_results.values()):
            raise ValueError("PASS needs the baseline to FAIL a target check (counterfactual discrimination)")
        return self


class Capability(_Strict):
    failure_class: FailureClass
    handler: Ident
    entrypoint: Text
    dependencies: tuple[Text, ...] = ()
    tools: tuple[Ident, ...] = ()
    authority: PermitStage
    enabled: bool = False
    maturity: Maturity = Maturity.DOCUMENTED
    tests: tuple[Text, ...] = ()
    evidence: tuple[Witness, ...] = ()
    promotion_ref: Optional[Ident] = None

    @model_validator(mode="after")
    def _enabled_needs_promotion(self) -> "Capability":
        if self.enabled and (self.promotion_ref is None
                             or _MATURITY_ORDER.index(self.maturity) < _MATURITY_ORDER.index(Maturity.ENABLED)):
            raise ValueError("a capability is enabled only with an owner promotion_ref and maturity >= ENABLED")
        return self


class Transition(_Strict):
    incident_id: Ident
    tenant_id: Ident
    from_state: IncidentState
    to_state: IncidentState
    actor: Ident
    time: datetime
    expected_version: int = Field(ge=0)
    new_version: int = Field(ge=1)
    permit_id: Optional[Ident] = None
    evidence: tuple[Witness, ...] = ()
    idempotency_key: Ident
    fencing_token: int = Field(ge=1)
    reason: Text

    @model_validator(mode="after")
    def _edge_is_legal(self) -> "Transition":
        assert_transition(self.from_state, self.to_state)
        if self.new_version != self.expected_version + 1:
            raise ValueError("new_version must be expected_version + 1 (compare-and-set)")
        if self.to_state in PERMIT_GATES and self.permit_id is None:
            raise ValueError(f"entering {self.to_state.value} requires a permit")
        return self


class Outcome(_Strict):
    incident_id: Ident
    candidate_id: Optional[Ident] = None
    state: IncidentState
    verdict: Optional[Verdict] = None
    authority: tuple[Ident, ...] = ()
    evidence: tuple[Witness, ...] = ()
    review_url: Optional[Text] = None
    recovery: Text
    gaps: tuple[Text, ...] = ()
    metrics: Mapping[Ident, Literal["NOT_MEASURED", "N/A"]] = Field(default_factory=dict)
    next_action: Text
    stop_reason: Optional[Text] = None

    @model_validator(mode="after")
    def _resolved_needs_pass(self) -> "Outcome":
        if self.state is IncidentState.RESOLVED and self.verdict != "PASS":
            raise ValueError("RESOLVED requires a PASS verdict")
        return self


__all__ = [
    "Budget", "Candidate", "Capability", "CauseClass", "Diagnosis", "Digest", "EffectClass", "EvidenceStatus",
    "FailureClass", "Hypothesis", "Incident", "Maturity", "Outcome", "Permit", "PermitStage", "RepairPlan",
    "SCHEMA", "Severity", "TestResult", "Transition", "Validation", "Witness",
]
