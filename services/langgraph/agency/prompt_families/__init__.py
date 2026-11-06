"""Reusable prompt families: series invariants, variation axes, concept ledger.

Composes the existing prompt compiler; terminal state is PROMPT_PACKAGE_READY.
See docs/brand-content-visual-prompt-os.md.
"""

from .capabilities import EXTERNAL_CAPABILITIES, external_capability_status
from .compiler import compile_prompt_family, family_hash, plan_instances
from .models import (
    EXECUTION_STATEMENT,
    FAMILY_ENGINE_VERSION,
    PAID_MEDIA_MUTATION_PRECONDITIONS,
    CampaignAnchor,
    ConceptLedger,
    ConceptSignature,
    HookCandidate,
    HookStatus,
    InvariantSet,
    PaidMediaCreativeSpec,
    PerformanceObservation,
    ProductionMedium,
    ProductionTarget,
    PromptFamilyRequest,
    PromptFamilyResult,
    PromptFamilySpec,
    VariationAxis,
)
from .roles import FUNCTIONAL_ROLE_BINDINGS, functional_roles_for, resolve_functional_roles

__all__ = [
    "EXECUTION_STATEMENT",
    "EXTERNAL_CAPABILITIES",
    "FAMILY_ENGINE_VERSION",
    "FUNCTIONAL_ROLE_BINDINGS",
    "PAID_MEDIA_MUTATION_PRECONDITIONS",
    "CampaignAnchor",
    "ConceptLedger",
    "ConceptSignature",
    "HookCandidate",
    "HookStatus",
    "InvariantSet",
    "PaidMediaCreativeSpec",
    "PerformanceObservation",
    "ProductionMedium",
    "ProductionTarget",
    "PromptFamilyRequest",
    "PromptFamilyResult",
    "PromptFamilySpec",
    "VariationAxis",
    "compile_prompt_family",
    "external_capability_status",
    "family_hash",
    "functional_roles_for",
    "plan_instances",
    "resolve_functional_roles",
]
