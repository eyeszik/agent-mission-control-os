"""Closed vocabularies for the governed action plane. Pure: no I/O.

R0–R6 are *governance* risk classes for an action's effect. They are unrelated
to the local visual engine's R1–R5 render routes (``agency.visual``); the two
are never compared or converted.
"""

from __future__ import annotations

from enum import Enum

ACTIONS_VERSION = "amc-actions/v1"
# Bumping the policy version invalidates every approval bound to the old one.
RISK_POLICY_VERSION = "amc-action-risk/v1"


class RiskClass(str, Enum):
    R0 = "R0"  # view / research
    R1 = "R1"  # local create / prepare
    R2 = "R2"  # external unpublished draft
    R3 = "R3"  # publish / communicate
    R4 = "R4"  # spend / budget
    R5 = "R5"  # critical asset or data mutation
    R6 = "R6"  # governance / permission mutation

    @property
    def rank(self) -> int:
        return int(self.value[1])


RISK_LABELS = {
    RiskClass.R0: "View or research",
    RiskClass.R1: "Local create or prepare",
    RiskClass.R2: "External unpublished draft",
    RiskClass.R3: "Publish or communicate",
    RiskClass.R4: "Spend or budget",
    RiskClass.R5: "Critical asset or data mutation",
    RiskClass.R6: "Governance or permission change",
}


class Environment(str, Enum):
    LOCAL = "LOCAL"
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"


class OperationKind(str, Enum):
    READ = "READ"
    CREATE_LOCAL = "CREATE_LOCAL"
    WRITE_DRAFT = "WRITE_DRAFT"
    PUBLISH = "PUBLISH"
    COMMUNICATE = "COMMUNICATE"
    SPEND = "SPEND"
    DELETE = "DELETE"
    TRANSFER = "TRANSFER"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    POLICY_CHANGE = "POLICY_CHANGE"


class Reversibility(str, Enum):
    REVERSIBLE = "REVERSIBLE"
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE = "IRREVERSIBLE"

    @property
    def rank(self) -> int:  # higher is worse
        return {"REVERSIBLE": 0, "COMPENSATABLE": 1, "IRREVERSIBLE": 2}[self.value]


class Audience(str, Enum):
    NONE = "NONE"
    INTERNAL = "INTERNAL"
    CLIENT = "CLIENT"
    PUBLIC = "PUBLIC"

    @property
    def rank(self) -> int:
        return {"NONE": 0, "INTERNAL": 1, "CLIENT": 2, "PUBLIC": 3}[self.value]


class DataClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"

    @property
    def rank(self) -> int:
        return {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3}[self.value]


class RetryClass(str, Enum):
    RETRY_SAFE = "RETRY_SAFE"
    NON_RETRYABLE = "NON_RETRYABLE"
    COMPENSATABLE = "COMPENSATABLE"


class ImplStatus(str, Enum):
    """Truthful implementation status of a catalogue entry.

    IMPLEMENTED means code exists; TESTED means named tests exercise it;
    VERIFIED is reserved for an independently observed outcome and is never set
    on a catalogue entry by this module."""

    DEFINED = "DEFINED"
    IMPLEMENTED = "IMPLEMENTED"
    TESTED = "TESTED"
    VERIFIED = "VERIFIED"
    LIVE_GATED = "LIVE_GATED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    PROVIDER_GAP = "PROVIDER_GAP"
    VOID_DETECTED = "VOID_DETECTED"


class Control(str, Enum):
    TENANT_SCOPE = "TENANT_SCOPE"
    PURPOSE_RECORDED = "PURPOSE_RECORDED"
    RATE_LIMIT = "RATE_LIMIT"
    DATA_ACCESS_CHECK = "DATA_ACCESS_CHECK"
    WORK_CONTRACT = "WORK_CONTRACT"
    OUTPUT_VALIDATION = "OUTPUT_VALIDATION"
    VERIFIED_TARGET = "VERIFIED_TARGET"
    IDEMPOTENCY = "IDEMPOTENCY"
    REVERSIBLE_PLAN = "REVERSIBLE_PLAN"
    READ_BACK = "READ_BACK"
    EXACT_APPROVAL = "EXACT_APPROVAL"
    APPROVAL_EXPIRY = "APPROVAL_EXPIRY"
    FINANCIAL_APPROVAL = "FINANCIAL_APPROVAL"
    BUDGET_RESERVATION = "BUDGET_RESERVATION"
    SPEND_RECONCILIATION = "SPEND_RECONCILIATION"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    INDEPENDENT_APPROVER = "INDEPENDENT_APPROVER"
    RECOVERY_ANALYSIS = "RECOVERY_ANALYSIS"
    BLAST_RADIUS_REVIEW = "BLAST_RADIUS_REVIEW"
    PRIVILEGED_REVIEW = "PRIVILEGED_REVIEW"
    NO_SELF_APPROVAL = "NO_SELF_APPROVAL"
    POLICY_VERSION_PIN = "POLICY_VERSION_PIN"
    DEPENDENCY_IMPACT_REVIEW = "DEPENDENCY_IMPACT_REVIEW"
    LIVE_GATE = "LIVE_GATE"


# Minimum controls per class. An action's controls are the UNION over every
# class it carries, plus rule-specific controls, never just the highest class's.
CLASS_CONTROLS: dict[RiskClass, frozenset[Control]] = {
    RiskClass.R0: frozenset({Control.TENANT_SCOPE, Control.PURPOSE_RECORDED, Control.RATE_LIMIT}),
    RiskClass.R1: frozenset({Control.TENANT_SCOPE, Control.WORK_CONTRACT, Control.OUTPUT_VALIDATION}),
    RiskClass.R2: frozenset({Control.TENANT_SCOPE, Control.VERIFIED_TARGET, Control.IDEMPOTENCY,
                             Control.REVERSIBLE_PLAN, Control.READ_BACK}),
    RiskClass.R3: frozenset({Control.TENANT_SCOPE, Control.EXACT_APPROVAL, Control.APPROVAL_EXPIRY,
                             Control.IDEMPOTENCY, Control.READ_BACK, Control.LIVE_GATE}),
    RiskClass.R4: frozenset({Control.TENANT_SCOPE, Control.EXACT_APPROVAL, Control.FINANCIAL_APPROVAL,
                             Control.BUDGET_RESERVATION, Control.SPEND_RECONCILIATION, Control.APPROVAL_EXPIRY,
                             Control.IDEMPOTENCY, Control.LIVE_GATE}),
    RiskClass.R5: frozenset({Control.TENANT_SCOPE, Control.EXACT_APPROVAL, Control.STEP_UP_AUTH,
                             Control.INDEPENDENT_APPROVER, Control.RECOVERY_ANALYSIS, Control.BLAST_RADIUS_REVIEW,
                             Control.APPROVAL_EXPIRY, Control.IDEMPOTENCY, Control.LIVE_GATE}),
    RiskClass.R6: frozenset({Control.TENANT_SCOPE, Control.EXACT_APPROVAL, Control.PRIVILEGED_REVIEW,
                             Control.NO_SELF_APPROVAL, Control.POLICY_VERSION_PIN, Control.APPROVAL_EXPIRY,
                             Control.LIVE_GATE}),
}


class AutonomyLevel(str, Enum):
    """Upper bound on what may run *without* a human decision. It never grants
    authority: R3+ always need approval whatever the dial says."""

    OBSERVE = "OBSERVE"                    # R0 only
    DRAFT = "DRAFT"                        # up to R1
    PREPARE = "PREPARE"                    # up to R2 (sandbox drafts)
    REQUEST_APPROVAL = "REQUEST_APPROVAL"  # up to R2, and may open approvals for R3+

    @property
    def auto_ceiling(self) -> RiskClass:
        return {"OBSERVE": RiskClass.R0, "DRAFT": RiskClass.R1, "PREPARE": RiskClass.R2,
                "REQUEST_APPROVAL": RiskClass.R2}[self.value]

    @property
    def rank(self) -> int:
        return {"OBSERVE": 0, "DRAFT": 1, "PREPARE": 2, "REQUEST_APPROVAL": 3}[self.value]


DEFAULT_AUTONOMY = AutonomyLevel.DRAFT

# User-readable status mapping (ClientActionConsole). Technical value stays
# available on demand; this text is what a person sees first.
STATUS_LABELS = {
    "PROVIDER_GAP": "Tool not connected",
    "BLOCKED_DEPENDENCY": "Waiting on prerequisite",
    "AWAITING_APPROVAL": "Approval required",
    "RECONCILING": "Checking outcome",
    "LIVE_GATED": "External action disabled",
    "VERIFIED": "Independently checked",
    "PROPOSED": "Proposed",
    "VALIDATED": "Validated",
    "PREPARED": "Prepared",
    "AUTHORIZED": "Ready to run",
    "RESERVED": "Budget reserved",
    "DISPATCHING": "Running",
    "OBSERVING": "Reading back the result",
    "COMPLETED": "Done and checked",
    "REJECTED": "Rejected",
    "BLOCKED": "Blocked",
    "EXPIRED": "Expired",
    "CANCELLED": "Cancelled",
    "FAILED": "Failed",
    "UNKNOWN": "Outcome unknown",
    "NEEDS_HUMAN": "Needs a person",
    "NOT_IMPLEMENTED": "Not available",
    "UNAVAILABLE": "Unavailable here",
    "IMPLEMENTED": "Available locally",
    "TESTED": "Available locally (tested)",
    "VOID_DETECTED": "No source definition",
}

__all__ = [
    "ACTIONS_VERSION",
    "Audience",
    "AutonomyLevel",
    "CLASS_CONTROLS",
    "Control",
    "DEFAULT_AUTONOMY",
    "DataClass",
    "Environment",
    "ImplStatus",
    "OperationKind",
    "RISK_LABELS",
    "RISK_POLICY_VERSION",
    "RetryClass",
    "Reversibility",
    "RiskClass",
    "STATUS_LABELS",
]
