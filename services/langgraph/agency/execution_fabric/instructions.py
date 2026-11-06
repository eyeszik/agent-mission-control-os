"""Instruction binding for the existing fabric; no new execution surface."""
from services.langgraph.agency.compiled.instruction_models import CompilationReport, InstructionPackage
from services.langgraph.agency.compiled.instructions import (
    InstructionInput, compile_instructions, verify_package,
)

from .skills import FABRIC_SKILLS


def instruction_input(context, cell, skill_id):
    spec = FABRIC_SKILLS.get(skill_id or "")
    if spec is None or cell.n3_role_id is None or cell.work_order_id is None:
        return None
    return InstructionInput(
        tenant_id=context.tenant_id, project_id=context.project_id, work_order_id=cell.work_order_id,
        contract_hash=cell.contract_hash, context_hash=cell.context_hash,
        dependencies=tuple(sorted(cell.cell.input_refs)), role_id=cell.n3_role_id,
        capability=spec.skill.capability.value, artifact_type=cell.artifact_type or "",
        objective=cell.cell.objective, acceptance=cell.acceptance_criteria,
    )


def compile_bound_instructions(context, cell, skill_id):
    data = instruction_input(context, cell, skill_id)
    if data is None or context.instructions is None:
        return CompilationReport(package=None, blockers=("CONTRACT_INSTRUCTION_BINDING_UNAVAILABLE",), rejected=(), bytes_used=0, sections_used=0)
    return compile_instructions(data, context.instructions)


def bind_instructions(context, cell, skill_id):
    if context.instructions is None:
        return (), None
    report = compile_bound_instructions(context, cell, skill_id)
    return report.blockers, report.package


def check_instructions(context, cell, skill_id, raw):
    if context.instructions is None:
        return () if raw is None else ("CONTRACT_INSTRUCTION_UNSELECTED",)
    data = instruction_input(context, cell, skill_id)
    if data is None or raw is None:
        return ("CONTRACT_INSTRUCTION_BINDING_UNAVAILABLE",)
    from pydantic import ValidationError

    try:
        package = InstructionPackage.model_validate(raw)
    except ValidationError:
        return ("CONTRACT_INSTRUCTION_INVALID",)
    return verify_package(package, data, context.instructions)
