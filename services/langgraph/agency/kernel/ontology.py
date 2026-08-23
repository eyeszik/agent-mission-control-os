"""N1 — department ontology for the multi-department agency.

The kernel models carry ``department`` and ``owner_department`` as strings so
that persistence stays schema-stable. This module supplies the closed
vocabulary those strings must belong to, plus the capability and artifact-type
surface each department legitimately owns.

The ontology is deliberately *closed*. An open string vocabulary cannot answer
"is this department allowed to release this artifact?", which is the question
the lifecycle gates (N2) and the artifact registry (N4) need to evaluate.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

ONTOLOGY_VERSION = "amc-agency-ontology/n1-v1"


class Department(str, Enum):
    """Specialized organizational departments in the agency."""

    strategy = "strategy"
    research = "research"
    brand = "brand"
    creative = "creative"
    copy = "copy"
    design = "design"
    product = "product"
    engineering = "engineering"
    growth = "growth"
    media = "media"
    analytics = "analytics"
    quality = "quality"
    operations = "operations"


class Capability(str, Enum):
    """What a department is permitted to do, independent of who performs it."""

    research_synthesis = "research_synthesis"
    positioning = "positioning"
    naming = "naming"
    identity_system = "identity_system"
    concepting = "concepting"
    copywriting = "copywriting"
    art_direction = "art_direction"
    product_definition = "product_definition"
    implementation = "implementation"
    campaign_planning = "campaign_planning"
    media_planning = "media_planning"
    measurement = "measurement"
    brand_safety_review = "brand_safety_review"
    release_management = "release_management"


class ArtifactType(str, Enum):
    """Canonical artifact vocabulary produced across departments."""

    research_brief = "research_brief"
    market_analysis = "market_analysis"
    positioning_statement = "positioning_statement"
    brand_platform = "brand_platform"
    naming_candidate = "naming_candidate"
    identity_guidelines = "identity_guidelines"
    creative_concept = "creative_concept"
    copy_variant = "copy_variant"
    design_brief = "design_brief"
    campaign_package = "campaign_package"
    product_spec = "product_spec"
    implementation_plan = "implementation_plan"
    media_plan = "media_plan"
    measurement_plan = "measurement_plan"
    qa_report = "qa_report"
    release_record = "release_record"


class DepartmentDefinition(BaseModel):
    """The authoritative description of one department."""

    department: Department
    mandate: str
    capabilities: frozenset[Capability]
    owned_artifact_types: frozenset[ArtifactType]
    # Departments whose approval is required before this department's artifacts
    # can leave the agency. Empty means no cross-department sign-off is needed.
    release_reviewers: frozenset[Department] = Field(default_factory=frozenset)

    model_config = {"frozen": True}


def _definition(
    department: Department,
    mandate: str,
    capabilities: tuple[Capability, ...],
    owned: tuple[ArtifactType, ...],
    release_reviewers: tuple[Department, ...] = (),
) -> DepartmentDefinition:
    return DepartmentDefinition(
        department=department,
        mandate=mandate,
        capabilities=frozenset(capabilities),
        owned_artifact_types=frozenset(owned),
        release_reviewers=frozenset(release_reviewers),
    )


DEPARTMENT_REGISTRY: dict[Department, DepartmentDefinition] = {
    definition.department: definition
    for definition in (
        _definition(
            Department.research,
            "Gather and synthesize external evidence about market, audience, and category.",
            (Capability.research_synthesis, Capability.measurement),
            (ArtifactType.research_brief, ArtifactType.market_analysis),
        ),
        _definition(
            Department.strategy,
            "Convert evidence into a defensible market position and engagement plan.",
            (Capability.positioning, Capability.campaign_planning),
            (ArtifactType.positioning_statement,),
        ),
        _definition(
            Department.brand,
            "Own brand platform, naming, and identity coherence across every surface.",
            (Capability.naming, Capability.identity_system, Capability.positioning),
            (ArtifactType.brand_platform, ArtifactType.naming_candidate, ArtifactType.identity_guidelines),
            (Department.quality,),
        ),
        _definition(
            Department.creative,
            "Translate strategy into distinct campaign concepts.",
            (Capability.concepting, Capability.art_direction),
            (ArtifactType.creative_concept,),
            (Department.quality,),
        ),
        _definition(
            Department.copy,
            "Write channel-ready language consistent with the brand platform.",
            (Capability.copywriting,),
            (ArtifactType.copy_variant,),
            (Department.quality,),
        ),
        _definition(
            Department.design,
            "Specify and direct visual execution.",
            (Capability.art_direction, Capability.identity_system),
            (ArtifactType.design_brief,),
            (Department.quality,),
        ),
        _definition(
            Department.product,
            "Define what is being taken to market and its acceptance criteria.",
            (Capability.product_definition,),
            (ArtifactType.product_spec,),
        ),
        _definition(
            Department.engineering,
            "Plan and carry out technical implementation.",
            (Capability.implementation,),
            (ArtifactType.implementation_plan,),
        ),
        _definition(
            Department.growth,
            "Assemble campaigns and own the growth loop.",
            (Capability.campaign_planning, Capability.measurement),
            (ArtifactType.campaign_package,),
            (Department.quality,),
        ),
        _definition(
            Department.media,
            "Plan paid distribution. Spend authority is escrowed, never implicit.",
            (Capability.media_planning,),
            (ArtifactType.media_plan,),
            (Department.quality, Department.operations),
        ),
        _definition(
            Department.analytics,
            "Define measurement and report outcomes against a verified data source.",
            (Capability.measurement,),
            (ArtifactType.measurement_plan,),
        ),
        _definition(
            Department.quality,
            "Adjudicate brand safety and evidence sufficiency before release.",
            (Capability.brand_safety_review,),
            (ArtifactType.qa_report,),
        ),
        _definition(
            Department.operations,
            "Own release mechanics and external-side-effect authorization.",
            (Capability.release_management,),
            (ArtifactType.release_record,),
        ),
    )
}

# Reverse index: which department owns a given artifact type. Built once and
# validated for uniqueness so ownership can never be ambiguous at runtime.
ARTIFACT_TYPE_OWNER: dict[ArtifactType, Department] = {}
for _definition_entry in DEPARTMENT_REGISTRY.values():
    for _artifact_type in _definition_entry.owned_artifact_types:
        if _artifact_type in ARTIFACT_TYPE_OWNER:
            raise RuntimeError(
                f"Artifact type {_artifact_type.value} is owned by more than one department"
            )
        ARTIFACT_TYPE_OWNER[_artifact_type] = _definition_entry.department


class OntologyError(ValueError):
    """Raised when a value falls outside the closed agency vocabulary."""


def resolve_department(value: str | Department) -> Department:
    """Coerce a stored string into a Department, failing closed on unknowns."""
    if isinstance(value, Department):
        return value
    try:
        return Department(value)
    except ValueError as exc:
        raise OntologyError(
            f"Unknown department '{value}'. Known departments: "
            + ", ".join(sorted(item.value for item in Department))
        ) from exc


def resolve_artifact_type(value: str | ArtifactType) -> ArtifactType:
    if isinstance(value, ArtifactType):
        return value
    try:
        return ArtifactType(value)
    except ValueError as exc:
        raise OntologyError(
            f"Unknown artifact type '{value}'. Known artifact types: "
            + ", ".join(sorted(item.value for item in ArtifactType))
        ) from exc


def department_definition(value: str | Department) -> DepartmentDefinition:
    return DEPARTMENT_REGISTRY[resolve_department(value)]


def owning_department(artifact_type: str | ArtifactType) -> Department:
    return ARTIFACT_TYPE_OWNER[resolve_artifact_type(artifact_type)]


def assert_department_owns(department: str | Department, artifact_type: str | ArtifactType) -> None:
    """Fail closed when a department claims an artifact type it does not own."""
    resolved_department = resolve_department(department)
    resolved_type = resolve_artifact_type(artifact_type)
    owner = ARTIFACT_TYPE_OWNER[resolved_type]
    if owner is not resolved_department:
        raise OntologyError(
            f"Department '{resolved_department.value}' does not own artifact type "
            f"'{resolved_type.value}' (owned by '{owner.value}')"
        )


def has_capability(department: str | Department, capability: Capability) -> bool:
    return capability in department_definition(department).capabilities


def ontology_snapshot() -> dict[str, Any]:
    """Serializable view of the ontology, used by contract/parity checks."""
    return {
        "ontology_version": ONTOLOGY_VERSION,
        "departments": [
            {
                "department": definition.department.value,
                "mandate": definition.mandate,
                "capabilities": sorted(item.value for item in definition.capabilities),
                "owned_artifact_types": sorted(item.value for item in definition.owned_artifact_types),
                "release_reviewers": sorted(item.value for item in definition.release_reviewers),
            }
            for definition in sorted(DEPARTMENT_REGISTRY.values(), key=lambda item: item.department.value)
        ],
    }
