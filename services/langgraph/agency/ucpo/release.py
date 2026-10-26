"""ReleaseProof: one record that binds every exact revision a release decision depends on.

The proof is eligible for human approval only when every gate is PASS. It never
authorizes deployment (``deployment`` is always ``NOT_AUTHORIZED``); approval goes
through the existing ``open_artifact_approval`` / ``/approvals/{id}/decide`` path and
the release verdict through ``artifact_release_verdict``. ``stale_reasons`` re-reads the
artifact heads: any stage whose head moved since the proof was sealed makes it stale, so
an approval of an old proof can never carry over to changed work.
"""

from __future__ import annotations

from typing import Callable, Optional

from .contracts import BrowserVerification, BuildResult, ReleaseProof, SemanticCoverageReport

GATES = ("isolation", "build", "browser_qa", "coverage", "deployment_authority")


def gate_results(build: Optional[BuildResult], qa: Optional[BrowserVerification],
                 coverage: Optional[SemanticCoverageReport]) -> dict[str, str]:
    iso = "BLOCKED" if build is None or build.status == "BLOCKED_ISOLATION" else "PASS"
    b = "NOT_RUN" if build is None else {"PASSED": "PASS", "BLOCKED_ISOLATION": "BLOCKED"}.get(build.status, "FAIL")
    q = "NOT_RUN" if qa is None else {"PASSED": "PASS", "FAILED": "FAIL"}.get(qa.status, "BLOCKED" if qa.status == "BLOCKED" else "NOT_RUN")
    c = "NOT_RUN" if coverage is None else ("FAIL" if coverage.release_blocked else "PASS")
    # Approval of this proof is a human decision about the work. Deploying it is a separate, explicit act
    # that no route here performs; the gate records that, and does not count against eligibility.
    return {"isolation": iso, "build": b, "browser_qa": q, "coverage": c, "deployment_authority": "NOT_REQUESTED"}


def seal_proof(*, project_ref: str, site_id: str, revisions: dict[str, str], artifact_refs: dict[str, str],
               build: Optional[BuildResult], qa: Optional[BrowserVerification],
               coverage: Optional[SemanticCoverageReport]) -> ReleaseProof:
    gates = gate_results(build, qa, coverage)
    reasons = tuple(f"{g}:{v}" for g, v in gates.items() if g != "deployment_authority" and v != "PASS")
    if qa is not None and build is not None and qa.build_output_hash != build.output_hash:
        reasons += ("browser_qa verified a different build output",)
    if coverage is not None:
        reasons += tuple(f"semantic_debt:{d.req_id}" for d in coverage.debt[:20])
    return ReleaseProof(project_ref=project_ref, site_id=site_id, revisions=dict(revisions), artifact_refs=dict(artifact_refs),
                        gates=gates, eligible_for_approval=not reasons, reasons=reasons)


def parse_ref(ref: str) -> tuple[str, int]:
    """'artifact:<id>@v<n>' -> (id, n)."""
    if not ref.startswith("artifact:") or "@v" not in ref:
        raise ValueError(f"not an artifact ref: {ref!r}")
    body = ref[len("artifact:"):]
    artifact_id, _, version = body.rpartition("@v")
    return artifact_id, int(version)


def stale_reasons(proof: ReleaseProof, head_of: Callable[[str], Optional[dict]]) -> list[str]:
    reasons = []
    for stage, ref in sorted(proof.artifact_refs.items()):
        artifact_id, version = parse_ref(ref)
        head = head_of(artifact_id)
        if head is None:
            reasons.append(f"PROOF_STALE:{stage}: artifact missing")
        elif int(head["version"]) != version:
            reasons.append(f"PROOF_STALE:{stage}: v{version} -> v{head['version']}")
        elif head.get("status") in {"invalidated", "review_required"}:
            reasons.append(f"PROOF_STALE:{stage}: {head['status']} by an upstream change")
    return reasons


__all__ = ["GATES", "gate_results", "parse_ref", "seal_proof", "stale_reasons"]
