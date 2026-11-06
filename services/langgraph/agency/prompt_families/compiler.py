"""Prompt-family compiler: family spec -> instances -> existing prompt compiler.

Series engine (source spec §11):

1. freeze invariants;
2. select a variation combination deterministically;
3. write the concept thesis before any styling;
4. compare with the ConceptLedger and repair duplicates, highest-level
   variable first, at most three passes;
5. compile every accepted instance through ``compile_prompt_packages`` so the
   claim, evidence, exact-text and firewall gates apply unchanged;
6. record accepted and rejected signatures in a new ledger value.

There is no generation step: the terminal state is ``PROMPT_PACKAGE_READY``.
"""

from __future__ import annotations

from services.langgraph.agency.prompt_compiler import (
    AssetRequirement,
    CompilerState,
    PromptCompilerRequest,
    SeriesBinding,
    compile_prompt_packages,
    stable_hash,
)

from . import ledger as concept_ledger
from .models import (
    AXIS_PRIORITY,
    ArtworkBackground,
    LedgerStatus,
    ProductionMedium,
    PromptFamilyEvaluation,
    PromptFamilyInstance,
    PromptFamilyRequest,
    PromptFamilyResult,
    PromptFamilySpec,
    VariationAxis,
    UNKNOWN,
)
from .roles import functional_roles_for

GENERATION_FIREWALL = "PROMPT_PACKAGE_READY"


def family_hash(spec: PromptFamilySpec) -> str:
    return stable_hash(spec)


def _initial_variation(spec: PromptFamilySpec, index: int) -> dict[str, str]:
    """Instance ``index`` takes option ``index`` on every axis (cycled).

    Axes with different option counts therefore drift apart naturally, and the
    choice is a pure function of the spec.
    """
    return {
        axis.value: spec.variation_axes[axis][index % len(spec.variation_axes[axis])]
        for axis in AXIS_PRIORITY
        if axis in spec.variation_axes
    }


def _concept_thesis(spec: PromptFamilySpec, variation: dict[str, str]) -> str:
    metaphor = variation.get(VariationAxis.concept_metaphor.value)
    anchor = None
    if spec.campaign is not None:
        anchor = spec.campaign.verbal_thesis or spec.campaign.promise
    core = anchor or spec.business_objective
    return f"{metaphor} — {core}" if metaphor else core


def plan_instances(spec: PromptFamilySpec, prior: list) -> list[PromptFamilyInstance]:
    accepted = [entry.signature for entry in prior]
    instances: list[PromptFamilyInstance] = []
    for index in range(spec.instance_count):
        variation = _initial_variation(spec, index)
        variation, repairs = concept_ledger.repair_variation(variation, spec.variation_axes, accepted)
        signature = concept_ledger.concept_signature(variation)
        status = LedgerStatus.accepted
        if concept_ledger.duplicate_reason(signature, accepted) is not None:
            status = LedgerStatus.rejected_duplicate
            repairs.append("repair budget exhausted: concept still repeats an accepted concept")
        else:
            accepted.append(signature)
        instances.append(
            PromptFamilyInstance(
                family_id=spec.family_id,
                instance_id=f"{spec.family_id}.{index + 1:02d}",
                concept_thesis=_concept_thesis(spec, variation),
                variation=variation,
                signature=signature,
                status=status,
                repairs=repairs,
            )
        )
    return instances


def _production_lines(spec: PromptFamilySpec) -> tuple[list[str], list[str], list[str]]:
    """Return (content, quality, negative) lines for the production target."""
    target = spec.production
    content: list[str] = []
    quality = [
        f"EDITABLE_MASTER: {target.editable_master}",
        "PRODUCTION_EXPORT: compiled separately from the editable master for the stated medium.",
    ]
    negative: list[str] = []
    for field in target.unknown_vendor_fields():
        quality.append(f"Vendor specification {field}={UNKNOWN}: confirm with the printer or vendor before production.")
    if target.medium is ProductionMedium.merch:
        content.append("Flat standalone artwork, independent of any product; clear silhouette and printable detail density.")
        if target.background is not ArtworkBackground.unspecified:
            content.append(f"Artwork background: {target.background.value}.")
        negative.append("No product mockup, garment, model or scene inside the artwork.")
    return content, quality, negative


def build_requirements(spec: PromptFamilySpec, instances: list[PromptFamilyInstance]) -> list[AssetRequirement]:
    invariant_lines = spec.invariants.lines()
    production_content, production_quality, production_negative = _production_lines(spec)
    requirements: list[AssetRequirement] = []
    for instance in instances:
        if instance.status is not LedgerStatus.accepted:
            continue
        binding = SeriesBinding(
            family_id=spec.family_id,
            family_version=spec.version,
            instance_id=instance.instance_id,
            campaign_ref=spec.campaign.campaign_id if spec.campaign else None,
            concept_thesis=instance.concept_thesis,
            emotional_function=spec.emotional_function,
            signature_devices=list(spec.invariants.signature_devices),
            series_invariants=invariant_lines,
            variation=dict(instance.variation),
            concept_signature=instance.signature.signature_hash,
        )
        content = list(spec.content_requirements) + production_content
        if spec.campaign is not None and spec.campaign.cta:
            content.append(f"Campaign CTA: {spec.campaign.cta}")
        requirements.append(
            AssetRequirement(
                asset_id=instance.instance_id,
                family=spec.surface_family,
                asset_type=spec.asset_type,
                objective=f"{spec.business_objective} Concept: {instance.concept_thesis}",
                audience=spec.audience,
                channel=spec.channel,
                destination=spec.destination,
                business_reason=spec.niche,
                content_requirements=content,
                negative_constraints=list(spec.negative_constraints) + production_negative,
                quality_constraints=production_quality,
                production=spec.production.export,
                exact_text=list(spec.exact_text),
                references=list(spec.references),
                series=binding,
            )
        )
    return requirements


def evaluate(spec: PromptFamilySpec, instances: list[PromptFamilyInstance], compiler_result) -> PromptFamilyEvaluation:
    invariant_lines = spec.invariants.lines()
    packages = compiler_result.prompt_packages
    hard: list[str] = []
    invariants_held = all(
        package.prompt_ir.series is not None and package.prompt_ir.series.series_invariants == invariant_lines
        for package in packages
    )
    if not invariants_held:
        hard.append("brand-invariant break: an instance does not carry the frozen invariants")
    exact_ok = all(
        not any(issue.startswith("required text not preserved") for issue in package.validation.issues)
        for package in packages
    )
    if not exact_ok:
        hard.append("required-text corruption")
    accepted = [item for item in instances if item.status is LedgerStatus.accepted]
    signatures = [item.signature.signature_hash for item in accepted]
    if len(signatures) != len(set(signatures)):
        hard.append("duplicate concept signature among accepted instances")

    axes = list(spec.variation_axes)
    diffs: list[float] = []
    for left, right in zip(accepted, accepted[1:]):
        changed = sum(1 for axis in axes if left.variation.get(axis.value) != right.variation.get(axis.value))
        diffs.append(changed / len(axes))
    varied = round(sum(diffs) / len(diffs), 6) if diffs else 0.0
    notes = [
        "series_consistency and novelty_budget are advisory configuration, not probabilities.",
    ]
    if diffs and varied < spec.novelty_budget:
        notes.append("Consecutive instances vary fewer axes than the novelty budget suggests.")
    return PromptFamilyEvaluation(
        invariants_held=invariants_held,
        exact_text_preserved=exact_ok,
        accepted_instances=len(accepted),
        rejected_duplicates=sum(1 for item in instances if item.status is LedgerStatus.rejected_duplicate),
        repairs=sum(len(item.repairs) for item in instances),
        varied_axis_fraction=varied,
        novelty_budget=spec.novelty_budget,
        series_consistency=spec.series_consistency,
        hard_failures=hard,
        advisory_notes=notes,
    )


def compile_prompt_family(request: PromptFamilyRequest) -> PromptFamilyResult:
    spec = request.family
    prior = request.ledger.accepted()
    instances = plan_instances(spec, prior)
    requirements = build_requirements(spec, instances)

    compiler_request = PromptCompilerRequest(
        project_name=request.project_name,
        content=request.content,
        claims=request.claims,
        evidence=request.evidence,
        brand_core=request.brand_core,
        asset_requirements=requirements,
        providers=request.providers,
        computations=request.computations,
    )
    result = compile_prompt_packages(compiler_request)
    evaluation = evaluate(spec, instances, result)

    blocked: list[str] = []
    if not requirements:
        blocked.append("no accepted instance: every concept repeated the ledger")
    if result.final_state is not CompilerState.prompt_package_ready:
        blocked.append(f"prompt compiler terminal state {result.final_state.value}")
    blocked += evaluation.hard_failures

    return PromptFamilyResult(
        family_id=spec.family_id,
        family_version=spec.version,
        family_hash=family_hash(spec),
        instances=instances,
        ledger=concept_ledger.record(request.ledger, instances),
        compiler_result=result,
        evaluation=evaluation,
        responsible_functional_roles=functional_roles_for(spec.surface_family, spec.production.medium),
        hooks=list(request.hooks),
        paid_media=list(request.paid_media),
        terminal_state="BLOCKED" if blocked else GENERATION_FIREWALL,
        blocked_reasons=blocked,
    )


__all__ = [
    "build_requirements",
    "compile_prompt_family",
    "evaluate",
    "family_hash",
    "plan_instances",
]
