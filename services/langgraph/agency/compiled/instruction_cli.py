"""Compile-only CLI packaging. Output is a candidate, never execution evidence."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

from .instruction_models import ExecutionReport, InstructionDelivery, ValidationReport
from .instructions import diff_instructions


def write_compilation(schedule, context, output: Path) -> int:
    from services.langgraph.agency.execution_fabric.instructions import compile_bound_instructions
    from services.langgraph.agency.execution_fabric.skills import ARTIFACT_SKILLS

    if context.instructions is None:
        from services.langgraph.agency.cli import BriefError

        raise BriefError("compile-instructions requires an explicit instructions selection")
    packages, blockers = {}, []
    for cid, cell in sorted(schedule.cells.items()):
        report = compile_bound_instructions(context, cell, ARTIFACT_SKILLS.get(cell.artifact_type or ""))
        package = report.package
        blockers.extend(f"{cid}:{reason}" for reason in report.blockers)
        packages[cid] = {**report.model_dump(mode="json"),
                         "diff": diff_instructions(None, package).model_dump(mode="json") if package else None}
    output.write_text(json.dumps(packages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    delivery = _delivery(output, blockers)
    Draft202012Validator(InstructionDelivery.model_json_schema()).validate(delivery.model_dump(mode="json"))
    print(delivery.model_dump_json(indent=2))
    return 1 if blockers else 0


def _delivery(output, blockers):
    return InstructionDelivery(
        status="BLOCKED" if blockers else "COMPLETE", operation="PROMPT", artifact=str(output),
        assumptions=("Compiled candidate only; no work executed or approvals established",),
        validation=ValidationReport(result="PARTIAL" if blockers else "PASS", checks=("typed compilation",), blockers=tuple(blockers)),
        execution=ExecutionReport(performed=("compiled instruction candidates",)),
        next_action="Resolve compilation blockers" if blockers else "Review candidate before opt-in fabric execution",
    )
