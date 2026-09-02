"""N3 — skill orchestrator contracts for specialized agent roles.

A role is the executable unit the orchestrator dispatches. Where N1 says what a
*department* is accountable for, N3 says what a *role inside it* may actually
do: which capabilities it exercises, which artifact types it may produce, what
evidence it must carry, and whether its output can leave the agency without a
human in the loop.

The authority fields are the point of the module. ``requires_human_approval``
and ``external_side_effect`` are declared per role and consumed by the
lifecycle guards, so "can this role publish?" is answered by the contract
rather than by whatever the role's prompt happens to say about itself.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from services.langgraph.agency.kernel.ontology import (
    ArtifactType,
    Capability,
    Department,
    OntologyError,
    assert_department_owns,
)

ROLE_CONTRACT_VERSION = "amc-agency-roles/n3-v1"


class RoleContract(BaseModel):
    """The execution contract for one specialized agent role."""

    role_id: str
    department: Department
    mandate: str
    capabilities: frozenset[Capability]
    produces: frozenset[ArtifactType]
    # Artifact types this role must be able to read to do its job. Used by the
    # orchestrator to refuse dispatch when an upstream input is missing.
    consumes: frozenset[ArtifactType] = Field(default_factory=frozenset)
    # Minimum evidence items backing any claim this role asserts. Zero means the
    # role is generative rather than evidential.
    min_evidence: int = Field(default=0, ge=0)
    # Whether this role's output requires an explicit human decision before it
    # can enter a client-visible state.
    requires_human_approval: bool = True
    # Whether executing this role can cause an effect outside the agency
    # (publishing, spending). Escrowed authority, never implicit.
    external_side_effect: bool = False

    model_config = {"frozen": True}

    @field_validator("role_id")
    @classmethod
    def _role_id_is_slug(cls, value: str) -> str:
        if not value or not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"role_id must be a non-empty slug, got '{value}'")
        return value


def _contract(
    role_id: str,
    department: Department,
    mandate: str,
    capabilities: tuple[Capability, ...],
    produces: tuple[ArtifactType, ...],
    *,
    consumes: tuple[ArtifactType, ...] = (),
    min_evidence: int = 0,
    requires_human_approval: bool = True,
    external_side_effect: bool = False,
) -> RoleContract:
    return RoleContract(
        role_id=role_id,
        department=department,
        mandate=mandate,
        capabilities=frozenset(capabilities),
        produces=frozenset(produces),
        consumes=frozenset(consumes),
        min_evidence=min_evidence,
        requires_human_approval=requires_human_approval,
        external_side_effect=external_side_effect,
    )


ROLE_REGISTRY: dict[str, RoleContract] = {
    contract.role_id: contract
    for contract in (
        _contract(
            "market_researcher",
            Department.research,
            "Collect and synthesize external evidence about the category and audience.",
            (Capability.research_synthesis,),
            (
                ArtifactType.research_brief,
                ArtifactType.market_analysis,
                ArtifactType.knowledge_capsule,
            ),
            min_evidence=3,
        ),
        _contract(
            "brand_strategist",
            Department.strategy,
            "Derive a defensible position from research evidence.",
            (Capability.positioning,),
            (
                ArtifactType.positioning_statement,
                ArtifactType.business_model_spec,
                ArtifactType.offer_definition,
            ),
            consumes=(ArtifactType.research_brief, ArtifactType.market_analysis),
            min_evidence=2,
        ),
        _contract(
            "brand_architect",
            Department.brand,
            "Build the brand platform, naming, and identity system.",
            (Capability.naming, Capability.identity_system),
            (
                ArtifactType.brand_platform,
                ArtifactType.naming_candidate,
                ArtifactType.identity_guidelines,
                ArtifactType.brand_core,
                ArtifactType.brand_guidelines_doc,
            ),
            consumes=(ArtifactType.positioning_statement,),
            # brand_core is the canonical source object for every downstream brand render,
            # so one source is not an evidence-backed floor.
            min_evidence=2,
        ),
        _contract(
            "creative_director",
            Department.creative,
            "Generate distinct campaign concepts from the brand platform.",
            (Capability.concepting, Capability.art_direction),
            (ArtifactType.creative_concept, ArtifactType.asset_prompt_set),
            consumes=(
                ArtifactType.brand_platform,
                ArtifactType.positioning_statement,
                ArtifactType.brand_core,
            ),
        ),
        _contract(
            "copywriter",
            Department.copy,
            "Write channel-ready language for approved concepts.",
            (Capability.copywriting,),
            (ArtifactType.copy_variant,),
            consumes=(ArtifactType.creative_concept, ArtifactType.brand_platform),
        ),
        _contract(
            "design_lead",
            Department.design,
            "Specify visual execution for approved concepts.",
            (Capability.art_direction,),
            (
                ArtifactType.design_brief,
                ArtifactType.design_token_set,
                ArtifactType.design_system_spec,
                ArtifactType.website_lockup_spec,
            ),
            consumes=(
                ArtifactType.creative_concept,
                ArtifactType.identity_guidelines,
                ArtifactType.brand_core,
            ),
        ),
        _contract(
            "product_manager",
            Department.product,
            "Define the offer and its acceptance criteria.",
            (Capability.product_definition,),
            (ArtifactType.product_spec,),
            consumes=(ArtifactType.positioning_statement,),
            min_evidence=1,
        ),
        _contract(
            "implementation_lead",
            Department.engineering,
            "Plan technical delivery of the product specification.",
            (Capability.implementation,),
            (
                ArtifactType.implementation_plan,
                ArtifactType.app_build_spec,
                ArtifactType.automation_spec,
            ),
            consumes=(ArtifactType.product_spec, ArtifactType.design_system_spec),
        ),
        _contract(
            "growth_lead",
            Department.growth,
            "Assemble the campaign package from approved components.",
            (Capability.campaign_planning,),
            (ArtifactType.campaign_package,),
            consumes=(ArtifactType.copy_variant, ArtifactType.design_brief, ArtifactType.creative_concept),
        ),
        _contract(
            "media_planner",
            Department.media,
            "Plan paid distribution. Spend requires escrowed authorization.",
            (Capability.media_planning,),
            (ArtifactType.media_plan,),
            consumes=(ArtifactType.campaign_package,),
            external_side_effect=True,
        ),
        _contract(
            "analytics_lead",
            Department.analytics,
            "Define measurement against a verified data source.",
            (Capability.measurement,),
            (ArtifactType.measurement_plan,),
            consumes=(ArtifactType.campaign_package,),
            min_evidence=1,
        ),
        _contract(
            "brand_safety_reviewer",
            Department.quality,
            "Adjudicate brand safety and evidence sufficiency before release.",
            (Capability.brand_safety_review,),
            (ArtifactType.qa_report,),
            consumes=(ArtifactType.campaign_package, ArtifactType.copy_variant),
            # The reviewer's own report is an input to the human gate rather
            # than client-facing output, so it does not itself need approval.
            requires_human_approval=False,
        ),
        _contract(
            "release_manager",
            Department.operations,
            "Execute release mechanics once every gate has cleared.",
            (Capability.release_management,),
            (ArtifactType.release_record,),
            consumes=(ArtifactType.campaign_package, ArtifactType.qa_report),
            external_side_effect=True,
        ),
    )
}


class RoleContractError(ValueError):
    """Raised when a role is dispatched outside its declared contract."""


def get_role(role_id: str) -> RoleContract:
    try:
        return ROLE_REGISTRY[role_id]
    except KeyError as exc:
        raise RoleContractError(
            f"Unknown role '{role_id}'. Known roles: " + ", ".join(sorted(ROLE_REGISTRY))
        ) from exc


def roles_for_department(department: str | Department) -> list[RoleContract]:
    resolved = Department(department) if not isinstance(department, Department) else department
    return sorted(
        (contract for contract in ROLE_REGISTRY.values() if contract.department is resolved),
        key=lambda contract: contract.role_id,
    )


def assert_role_may_produce(role_id: str, artifact_type: str | ArtifactType) -> None:
    """Fail closed when a role emits an artifact type outside its contract."""
    contract = get_role(role_id)
    resolved = ArtifactType(artifact_type) if not isinstance(artifact_type, ArtifactType) else artifact_type
    if resolved not in contract.produces:
        raise RoleContractError(
            f"Role '{role_id}' may not produce artifact type '{resolved.value}'; "
            f"declared outputs: {', '.join(sorted(item.value for item in contract.produces))}"
        )


def assert_evidence_sufficient(role_id: str, evidence_count: int) -> None:
    contract = get_role(role_id)
    if evidence_count < contract.min_evidence:
        raise RoleContractError(
            f"Role '{role_id}' requires at least {contract.min_evidence} evidence item(s), "
            f"got {evidence_count}"
        )


def validate_registry() -> list[str]:
    """Structural self-check across N1 and N3.

    Returns every problem rather than raising, so the validation gate can report
    a complete picture in one run.
    """
    problems: list[str] = []
    for role_id, contract in sorted(ROLE_REGISTRY.items()):
        for artifact_type in sorted(contract.produces, key=lambda item: item.value):
            try:
                assert_department_owns(contract.department, artifact_type)
            except OntologyError as exc:
                problems.append(f"role '{role_id}': {exc}")

        declared = set(contract.capabilities)
        from services.langgraph.agency.kernel.ontology import department_definition

        departmental = set(department_definition(contract.department).capabilities)
        for capability in sorted(declared - departmental, key=lambda item: item.value):
            problems.append(
                f"role '{role_id}' claims capability '{capability.value}' that department "
                f"'{contract.department.value}' does not hold"
            )

        if contract.external_side_effect and not contract.requires_human_approval:
            problems.append(
                f"role '{role_id}' can cause an external side effect but does not require human approval"
            )

    # Every artifact type in the ontology should be producible by some role,
    # otherwise the pipeline declares an output nothing can create.
    produced = {item for contract in ROLE_REGISTRY.values() for item in contract.produces}
    for artifact_type in sorted(set(ArtifactType) - produced, key=lambda item: item.value):
        problems.append(f"artifact type '{artifact_type.value}' has no producing role")

    # Every consumed type must be producible, or the orchestrator can deadlock.
    for role_id, contract in sorted(ROLE_REGISTRY.items()):
        for artifact_type in sorted(contract.consumes - produced, key=lambda item: item.value):
            problems.append(
                f"role '{role_id}' consumes '{artifact_type.value}', which no role produces"
            )

    return problems


def role_snapshot() -> dict[str, Any]:
    return {
        "role_contract_version": ROLE_CONTRACT_VERSION,
        "roles": [
            {
                "role_id": contract.role_id,
                "department": contract.department.value,
                "mandate": contract.mandate,
                "capabilities": sorted(item.value for item in contract.capabilities),
                "produces": sorted(item.value for item in contract.produces),
                "consumes": sorted(item.value for item in contract.consumes),
                "min_evidence": contract.min_evidence,
                "requires_human_approval": contract.requires_human_approval,
                "external_side_effect": contract.external_side_effect,
            }
            for contract in sorted(ROLE_REGISTRY.values(), key=lambda item: item.role_id)
        ],
    }
