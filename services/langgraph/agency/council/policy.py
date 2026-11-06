"""Fable/Cipher's audit is policy first: deterministic rules decide risk and approval.

A model may add findings (they can only raise risk), but it can never lower the
level, clear ``requires_approval`` or unblock a CRITICAL finding. Deny by
default: any requested side effect other than READ needs a human approval.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from services.langgraph.security.pii import (
    _EXTRA_SECRET_PATTERNS,
    PII_PATTERNS,
)

from .contracts import (
    POLICY_VERSION,
    SEVERITY_ORDER,
    RequestedAction,
    RiskAssessment,
    RiskFinding,
)

_SECRET_PATTERNS = (PII_PATTERNS["api_key_like"], PII_PATTERNS["bearer"], *_EXTRA_SECRET_PATTERNS,
                    re.compile(r"(?i)\b(password|passwd|secret|token)\s*[:=]\s*\S{6,}"))
_PII_PATTERNS = (PII_PATTERNS["email"], PII_PATTERNS["phone"], PII_PATTERNS["ssn"])

# (code, severity, regex, detail). Keyword rules flag intent; they never execute anything.
_RULES: tuple[tuple[str, str, re.Pattern, str], ...] = (
    ("SHELL_EXECUTION_REQUESTED", "HIGH",
     re.compile(r"(?i)\b(shell|bash|subprocess|sudo|chmod|rm\s+-rf|exec\(|eval\(|curl\s+[^|]*\|\s*(sh|bash))"),
     "Shell or code execution requested; the gateway exposes no shell tool and generated code is never run"),
    ("EXTERNAL_DISPATCH_REQUESTED", "HIGH",
     re.compile(r"(?i)\b(deploy|publish|send (an )?e-?mail|sms|webhook|post to|tweet|payment|charge|purchase|invoice)"),
     "External dispatch requested; publication, sending and spend stay disabled without an approved adapter"),
    ("DESTRUCTIVE_OPERATION_REQUESTED", "HIGH",
     re.compile(r"(?i)\b(drop table|truncate|wipe|delete (all|every|the database|production))"),
     "Destructive data operation requested"),
    ("PRIVILEGE_ESCALATION_REQUESTED", "HIGH",
     re.compile(r"(?i)\b(root access|admin access|bypass|disable (auth|authentication|approval)|skip (the )?approval)"),
     "Privilege escalation or control bypass requested"),
    ("PROMPT_INJECTION_SUSPECTED", "HIGH",
     re.compile(r"(?i)(ignore (all )?(previous|prior) instructions|you are now|reveal (the )?system prompt)"),
     "Instruction-override text found in the idea; it is treated as data, not instructions"),
)


def _max_level(findings: Iterable[RiskFinding]) -> str:
    level = "LOW"
    for finding in findings:
        if SEVERITY_ORDER[finding.severity] > SEVERITY_ORDER[level]:
            level = finding.severity
    return level


def scan(text: str, requested_actions: Iterable[RequestedAction]) -> RiskAssessment:
    """Deterministic risk assessment of the mission input and its requested side effects."""
    findings: list[RiskFinding] = []
    if any(p.search(text) for p in _SECRET_PATTERNS):
        findings.append(RiskFinding(code="SECRET_IN_INPUT", severity="CRITICAL", source="POLICY",
                                    detail="A credential-shaped value is present in the input; the mission is blocked"))
    if any(p.search(text) for p in _PII_PATTERNS):
        findings.append(RiskFinding(code="PII_IN_INPUT", severity="MEDIUM", source="POLICY",
                                    detail="Personal data is present; it is redacted from audit logs"))
    for code, severity, pattern, detail in _RULES:
        if pattern.search(text):
            findings.append(RiskFinding(code=code, severity=severity, source="POLICY", detail=detail))
    actions = list(requested_actions)
    for action in actions:
        if action.sensitivity != "READ":
            findings.append(RiskFinding(code=f"{action.sensitivity}_ACTION_REQUESTED", severity="MEDIUM",
                                        source="POLICY", detail=f"{action.tool_id} -> {action.target}"[:400]))
    level = _max_level(findings)
    requires = any(a.sensitivity != "READ" for a in actions) or SEVERITY_ORDER[level] >= SEVERITY_ORDER["HIGH"]
    return RiskAssessment(level=level, findings=findings, requires_approval=requires, blocked=level == "CRITICAL",
                          requested_actions=actions, policy_version=POLICY_VERSION)


def merge_model_findings(policy: RiskAssessment, model_output: Mapping[str, Any]) -> RiskAssessment:
    """Add validated model findings and narrative. Risk can only go up."""
    extra: list[RiskFinding] = []
    for raw in (model_output.get("additional_findings") or [])[:10]:
        if not isinstance(raw, Mapping):
            continue
        try:
            extra.append(RiskFinding(code=str(raw.get("code", "MODEL_FINDING"))[:64].upper().replace(" ", "_"),
                                     severity=raw.get("severity", "MEDIUM"), detail=str(raw.get("detail", ""))[:400] or "n/a",
                                     source="MODEL"))
        except ValueError:
            continue  # untrusted output that does not validate is dropped, not repaired
    findings = [*policy.findings, *extra]
    level = _max_level(findings)
    requires = policy.requires_approval or SEVERITY_ORDER[level] >= SEVERITY_ORDER["HIGH"]
    narrative = str(model_output.get("narrative") or "")[:1200]
    return policy.model_copy(update={"findings": findings, "level": level, "requires_approval": requires,
                                     "blocked": policy.blocked or level == "CRITICAL", "narrative": narrative})


__all__ = ["merge_model_findings", "scan"]
