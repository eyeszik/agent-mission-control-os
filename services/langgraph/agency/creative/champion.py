"""Champion / Challenger benchmark on one mission.

- Champion: the context-free baseline — no context portfolio, one candidate
  (exploration forced to ``single``), no search.
- Challenger: the full runtime — governed context, derived requirements,
  bounded search when the mission justifies it.

Both are scored by the *same* deterministic critics and hard gate. The
comparison is on the first-pass output (before any human action), so the
correction loop does not blur it. It measures structural, explainable quality
under this repository's rubric; it is not a human-preference study, a
conversion forecast or a model benchmark, and the report says so.
"""

from __future__ import annotations

from typing import Any, Mapping

from .runtime import CreativeRun, run_creative_mission


def _summary(run: CreativeRun) -> dict[str, Any]:
    front = [run.results[c] for c in run.front]
    objectives = sorted({k for r in front for k in r.scores})
    best = {k: max((r.scores[k].value for r in front if k in r.scores), default=None) for k in objectives}
    unc = {k: max((r.scores[k].uncertainty for r in front if k in r.scores), default=0.0) for k in objectives}
    findings = sorted({f.code for r in front for e in r.evaluations for f in e.findings})
    a11y = sum(1 for r in front for e in r.evaluations if e.evaluator_id == "accessibility_critic" for _ in e.findings)
    feasible = sum(1 for r in run.results.values() if r.feasibility.verdict != "INFEASIBLE")
    return {
        "state": run.state, "topology": run.plan.topology_class if run.plan else None,
        "context_units": len(run.context.selected) if run.context else 0, "requirements": list(run.requirements),
        "candidates": len(run.candidates), "feasible": feasible, "front_size": len(run.front),
        "distinct_concepts": len({c.concept for c in run.candidates if c.concept is not None}),
        "best_scores": best, "uncertainty": unc, "accessibility_findings_on_front": a11y, "finding_codes": findings,
        "cost": run.usage.model_dump(),
    }


def compare(brief: Mapping[str, Any], *, run_id_prefix: str = "cc") -> dict[str, Any]:
    champion_brief = {**dict(brief), "exploration": {"mode": "single"}}
    champion = run_creative_mission(champion_brief, run_id=f"{run_id_prefix}-champion", use_context=False)
    challenger = run_creative_mission(dict(brief), run_id=f"{run_id_prefix}-challenger")
    a, b = _summary(champion), _summary(challenger)
    better, worse = [], []
    for k in sorted(set(a["best_scores"]) & set(b["best_scores"])):
        margin = max(a["uncertainty"][k], b["uncertainty"][k])
        if b["best_scores"][k] - a["best_scores"][k] > margin:
            better.append(k)
        elif a["best_scores"][k] - b["best_scores"][k] > margin:
            worse.append(k)
    if champion.state != "AWAITING_SELECTION" or challenger.state != "AWAITING_SELECTION":
        verdict = "NOT_COMPARABLE"
    elif better and not worse:
        verdict = "CHALLENGER_BETTER"
    elif worse and not better:
        verdict = "CHAMPION_BETTER"
    elif not better and not worse:
        verdict = "NO_MEASURABLE_DIFFERENCE"
    else:
        verdict = "MIXED"
    return {
        "champion": a, "challenger": b, "challenger_better_on": better, "challenger_worse_on": worse, "verdict": verdict,
        "method": "same deterministic critics and hard gate on first-pass output; difference must exceed the larger "
                  "declared uncertainty",
        "limitations": [
            "structural rubric only; no human preference, conversion or model-quality claim",
            "distinctiveness is undefined for a single candidate and is excluded from the comparison",
            "the champion is a deterministic baseline, not an LLM run",
        ],
    }


__all__ = ["compare"]
