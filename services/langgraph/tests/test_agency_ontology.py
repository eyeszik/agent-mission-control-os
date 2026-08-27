"""graph-validation-run — E2E simulation across the N1-N4 ontology layers.

These tests are the validation gate for the ontology compile. They assert three
classes of property:

1. **Structural** — every declared state, role, and merge pair resolves.
2. **Behavioral** — a full engagement lifecycle reaches release only through
   legal, guarded transitions.
3. **Zero state-loss** — concurrent cross-department revision preserves both
   branches' history, and serialization round-trips without dropping anything.
"""

import json

import pytest

from services.langgraph.agency.kernel import (
    ROLE_REGISTRY,
    ArtifactRegistry,
    ArtifactStatus,
    ArtifactType,
    Capability,
    Department,
    EngagementStatus,
    MergeResolution,
    OntologyError,
    RoleContractError,
    TransitionContext,
    TransitionError,
    WorkstreamStatus,
    assert_department_owns,
    assert_evidence_sufficient,
    assert_role_may_produce,
    assert_transition,
    can_transition,
    get_role,
    lifecycle_snapshot,
    ontology_snapshot,
    owning_department,
    role_snapshot,
    transition_blockers,
    validate_matrices,
    validate_merge_matrix,
    validate_registry,
)


# ---------------------------------------------------------------------------
# Structural integrity
# ---------------------------------------------------------------------------

def test_lifecycle_matrices_are_structurally_complete():
    assert validate_matrices() == []


def test_role_registry_is_consistent_with_department_ontology():
    assert validate_registry() == []


def test_merge_matrix_covers_every_status_pair():
    assert validate_merge_matrix() == []
    assert len(list(ArtifactStatus)) ** 2 == 64


def test_every_artifact_type_has_exactly_one_owning_department():
    owners = {artifact_type: owning_department(artifact_type) for artifact_type in ArtifactType}
    assert len(owners) == len(list(ArtifactType))
    assert all(isinstance(owner, Department) for owner in owners.values())


COMPILER_ARTIFACTS = {
    "brand_core": "brand",
    "brand_guidelines_doc": "brand",
    "design_token_set": "design",
    "design_system_spec": "design",
    "website_lockup_spec": "design",
    "asset_prompt_set": "creative",
    "business_model_spec": "strategy",
    "offer_definition": "strategy",
    "app_build_spec": "engineering",
    "automation_spec": "engineering",
    "knowledge_capsule": "research",
}


@pytest.mark.parametrize("artifact_type,department", sorted(COMPILER_ARTIFACTS.items()))
def test_compiler_artifact_is_owned_by_its_declared_department(artifact_type, department):
    assert owning_department(artifact_type) is Department(department)
    assert_department_owns(department, artifact_type)


@pytest.mark.parametrize("artifact_type,department", sorted(COMPILER_ARTIFACTS.items()))
def test_compiler_artifact_has_exactly_one_producing_role(artifact_type, department):
    from services.langgraph.agency.kernel import roles_for_department

    producers = [
        role.role_id
        for role in roles_for_department(department)
        if ArtifactType(artifact_type) in role.produces
    ]
    assert len(producers) == 1, f"{artifact_type} has producers {producers}"


def test_brand_core_carries_a_real_evidence_floor():
    """brand_core is the root of every rendering; it may not be invented."""
    contract = get_role("brand_architect")
    assert ArtifactType.brand_core in contract.produces
    assert contract.min_evidence >= 2
    with pytest.raises(RoleContractError):
        assert_evidence_sufficient("brand_architect", 1)


def test_design_compile_chain_is_owned_end_to_end():
    """brand_core → tokens → system → lockup must not cross a department."""
    design_lead = get_role("design_lead")
    for step in (
        ArtifactType.design_token_set,
        ArtifactType.design_system_spec,
        ArtifactType.website_lockup_spec,
    ):
        assert step in design_lead.produces
    # The chain's input is authored elsewhere and must be consumed, not re-derived.
    assert ArtifactType.brand_core in design_lead.consumes


def test_automation_only_work_needs_no_brand_artifact():
    """Profile E: an automation is producible without touching brand."""
    implementation_lead = get_role("implementation_lead")
    assert ArtifactType.automation_spec in implementation_lead.produces
    brand_owned = {
        artifact_type
        for artifact_type in ArtifactType
        if owning_department(artifact_type) is Department.brand
    }
    assert not (implementation_lead.produces & brand_owned)
    assert not (implementation_lead.consumes & brand_owned)


def test_no_role_may_produce_a_compiler_artifact_it_does_not_own():
    for artifact_type, department in COMPILER_ARTIFACTS.items():
        for role_id in ROLE_REGISTRY:
            contract = get_role(role_id)
            if contract.department is not Department(department):
                assert ArtifactType(artifact_type) not in contract.produces
                with pytest.raises(RoleContractError):
                    assert_role_may_produce(role_id, artifact_type)


def test_unknown_vocabulary_fails_closed():
    with pytest.raises(OntologyError):
        assert_department_owns("marketing", "copy_variant")
    with pytest.raises(OntologyError):
        assert_department_owns("copy", "not_a_real_artifact")
    with pytest.raises(RoleContractError):
        get_role("chief_vibes_officer")


# ---------------------------------------------------------------------------
# Lifecycle behavior
# ---------------------------------------------------------------------------

def _clean_context(**overrides) -> TransitionContext:
    base = {
        "generation_mode": "PROVIDER_SUCCESS",
        "approval_exists": True,
        "approval_decision": "approve",
        "approval_resolved": True,
        "brand_safety_passed": True,
    }
    base.update(overrides)
    return TransitionContext(**base)


def test_engagement_walks_the_canonical_phase_graph_to_launch():
    path = [
        EngagementStatus.intake,
        EngagementStatus.discovery,
        EngagementStatus.research,
        EngagementStatus.strategy,
        EngagementStatus.brand,
        EngagementStatus.product,
        EngagementStatus.build,
        EngagementStatus.launch_ready,
        EngagementStatus.launched,
        EngagementStatus.growth,
        EngagementStatus.complete,
    ]
    context = _clean_context()
    for current, target in zip(path, path[1:]):
        assert_transition("engagement", current, target, context)


def test_skipping_a_phase_is_rejected():
    with pytest.raises(TransitionError):
        assert_transition("engagement", EngagementStatus.intake, EngagementStatus.launched, _clean_context())


def test_degraded_generation_blocks_every_client_visible_transition():
    degraded = _clean_context(generation_mode="FALLBACK_DEGRADED")

    for entity, current, target in (
        ("engagement", EngagementStatus.launch_ready, EngagementStatus.launched),
        ("workstream", WorkstreamStatus.approved, WorkstreamStatus.released),
        ("artifact", ArtifactStatus.approved, ArtifactStatus.release_eligible),
    ):
        blockers = transition_blockers(entity, current, target, degraded)
        assert any("FALLBACK_DEGRADED" in blocker for blocker in blockers), (entity, blockers)
        assert not can_transition(entity, current, target, degraded)


def test_unresolved_or_rejected_approval_blocks_release():
    unresolved = _clean_context(approval_resolved=False, approval_decision=None)
    assert "human approval is unresolved" in transition_blockers(
        "workstream", WorkstreamStatus.approved, WorkstreamStatus.released, unresolved
    )

    rejected = _clean_context(approval_decision="reject")
    blockers = transition_blockers(
        "workstream", WorkstreamStatus.approved, WorkstreamStatus.released, rejected
    )
    assert any("not 'approve'" in blocker for blocker in blockers)


def test_failed_brand_safety_blocks_release():
    unsafe = _clean_context(brand_safety_passed=False)
    assert "brand safety review has not passed" in transition_blockers(
        "artifact", ArtifactStatus.approved, ArtifactStatus.release_eligible, unsafe
    )


def test_external_side_effect_requires_explicit_authorization():
    unauthorized = _clean_context(external_side_effect=True, spend_authorized=False)
    blockers = transition_blockers(
        "workstream", WorkstreamStatus.approved, WorkstreamStatus.released, unauthorized
    )
    assert any("authorization" in blocker for blocker in blockers)

    authorized = _clean_context(external_side_effect=True, spend_authorized=True)
    assert can_transition("workstream", WorkstreamStatus.approved, WorkstreamStatus.released, authorized)


def test_unmet_hard_dependencies_block_dependency_gated_transitions():
    blocked = _clean_context(unmet_hard_dependencies=("positioning_statement",))
    assert any(
        "unmet hard dependencies" in blocker
        for blocker in transition_blockers("workstream", WorkstreamStatus.ready, WorkstreamStatus.executing, blocked)
    )


def test_multiple_independent_blockers_are_all_reported():
    """A caller fixing one gate must see the others still standing."""
    context = TransitionContext(
        generation_mode="FALLBACK_DEGRADED",
        approval_resolved=False,
        brand_safety_passed=False,
    )
    blockers = transition_blockers(
        "artifact", ArtifactStatus.approved, ArtifactStatus.release_eligible, context
    )
    assert len(blockers) >= 3


# ---------------------------------------------------------------------------
# Role contracts
# ---------------------------------------------------------------------------

def test_role_may_only_produce_its_declared_artifact_types():
    assert_role_may_produce("copywriter", ArtifactType.copy_variant)
    with pytest.raises(RoleContractError):
        assert_role_may_produce("copywriter", ArtifactType.media_plan)


def test_evidential_roles_enforce_their_evidence_floor():
    with pytest.raises(RoleContractError):
        assert_evidence_sufficient("market_researcher", 1)
    assert_evidence_sufficient("market_researcher", 3)
    # Generative roles carry no floor.
    assert_evidence_sufficient("creative_director", 0)


def test_roles_never_claim_capabilities_their_department_lacks():
    for entry in role_snapshot()["roles"]:
        department = Department(entry["department"])
        from services.langgraph.agency.kernel import department_definition

        departmental = {item.value for item in department_definition(department).capabilities}
        assert set(entry["capabilities"]) <= departmental, entry["role_id"]


def test_external_side_effect_roles_always_require_human_approval():
    for entry in role_snapshot()["roles"]:
        if entry["external_side_effect"]:
            assert entry["requires_human_approval"], entry["role_id"]


# ---------------------------------------------------------------------------
# Artifact registry: branching, merging, zero state-loss
# ---------------------------------------------------------------------------

def _seed_registry() -> ArtifactRegistry:
    registry = ArtifactRegistry("artifact-campaign-1")
    registry.commit(
        branch="main",
        status=ArtifactStatus.draft,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "v1"},
    )
    return registry


def test_registry_enforces_department_ownership_at_write_time():
    registry = _seed_registry()
    with pytest.raises(OntologyError):
        registry.commit(
            branch="main",
            status=ArtifactStatus.draft,
            artifact_type=ArtifactType.media_plan,
            owner_department=Department.growth,
            content={},
        )


def test_branch_cannot_open_before_main_has_a_version():
    from services.langgraph.agency.kernel import MergeError

    registry = ArtifactRegistry("artifact-empty")
    with pytest.raises(MergeError):
        registry.commit(
            branch="side",
            status=ArtifactStatus.draft,
            artifact_type=ArtifactType.copy_variant,
            owner_department=Department.copy,
            content={},
        )


def test_unadvanced_base_fast_forwards():
    registry = _seed_registry()
    registry.commit(
        branch="copy-revision",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "v2"},
    )
    outcome = registry.merge("copy-revision")
    assert outcome.resolution is MergeResolution.fast_forward
    assert outcome.requires_human is False
    assert outcome.winner is not None


def test_identical_content_is_a_no_op_merge():
    registry = _seed_registry()
    registry.commit(
        branch="dup",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "v1"},
    )
    outcome = registry.merge("dup")
    assert outcome.resolution is MergeResolution.fast_forward
    assert "identical" in outcome.reason


def test_divergent_release_state_escalates_instead_of_overwriting():
    registry = _seed_registry()
    registry.commit(
        branch="design-revision",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "design-edit"},
    )
    # Base advances to released while the branch was open.
    registry.commit(
        branch="main",
        status=ArtifactStatus.released,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "shipped"},
    )
    outcome = registry.merge("design-revision")
    assert outcome.resolution is MergeResolution.escalate
    assert outcome.requires_human is True
    assert outcome.winner is None


def test_degraded_branch_never_auto_merges():
    registry = _seed_registry()
    registry.commit(
        branch="main",
        status=ArtifactStatus.approved,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "approved"},
    )
    registry.commit(
        branch="degraded-retry",
        status=ArtifactStatus.draft,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "fallback"},
        generation_mode="FALLBACK_DEGRADED",
    )
    outcome = registry.merge("degraded-retry")
    assert outcome.resolution is MergeResolution.escalate
    assert "FALLBACK_DEGRADED" in outcome.reason


def test_archived_base_is_terminal_under_every_incoming_status():
    from services.langgraph.agency.kernel import MERGE_MATRIX

    for incoming in ArtifactStatus:
        assert MERGE_MATRIX[(ArtifactStatus.archived, incoming)] is MergeResolution.keep_base


def test_concurrent_cross_department_revision_loses_no_history():
    """Zero state-loss: every committed version survives a contested merge."""
    registry = _seed_registry()
    registry.commit(
        branch="copy-revision",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "copy-edit"},
    )
    registry.commit(
        branch="design-revision",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "design-edit"},
    )
    registry.commit(
        branch="main",
        status=ArtifactStatus.approved,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "v2"},
    )

    registry.merge("copy-revision")
    registry.merge("design-revision")

    # Merging resolves precedence; it never deletes a committed version.
    assert len(registry.all_versions()) == 4
    assert set(registry.branches()) == {"main", "copy-revision", "design-revision"}
    assert [version.version for version in registry.lineage("main")] == [1, 4]
    assert len(registry.lineage("copy-revision")) == 1
    assert len(registry.lineage("design-revision")) == 1


def test_registry_serialization_round_trips_without_loss():
    registry = _seed_registry()
    registry.commit(
        branch="copy-revision",
        status=ArtifactStatus.validating,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"headline": "v2"},
        assumptions=["audience unchanged"],
        metadata={"reviewer": "quality"},
    )
    encoded = json.dumps(registry.serialize())
    restored = ArtifactRegistry.deserialize(json.loads(encoded))

    assert restored.serialize() == registry.serialize()
    assert [item.version for item in restored.all_versions()] == [
        item.version for item in registry.all_versions()
    ]
    assert restored.head("copy-revision").assumptions == ("audience unchanged",)


def test_registry_rejects_a_foreign_serialization_version():
    from services.langgraph.agency.kernel import MergeError

    payload = _seed_registry().serialize()
    payload["registry_version"] = "amc-agency-registry/n4-v0"
    with pytest.raises(MergeError):
        ArtifactRegistry.deserialize(payload)


# ---------------------------------------------------------------------------
# End-to-end: one engagement across all four layers
# ---------------------------------------------------------------------------

def test_end_to_end_engagement_reaches_release_only_through_guarded_transitions():
    registry = ArtifactRegistry("artifact-e2e")
    engagement_state = EngagementStatus.intake
    context = _clean_context()

    # N3 dispatch: research role produces a research brief backed by evidence.
    research = get_role("market_researcher")
    assert_evidence_sufficient(research.role_id, research.min_evidence)
    assert_role_may_produce(research.role_id, ArtifactType.research_brief)

    for target in (EngagementStatus.discovery, EngagementStatus.research):
        assert_transition("engagement", engagement_state, target, context)
        engagement_state = target

    # N4: the growth department drafts the campaign package.
    registry.commit(
        branch="main",
        status=ArtifactStatus.draft,
        artifact_type=ArtifactType.campaign_package,
        owner_department=Department.growth,
        content={"stage": "draft"},
        generation_mode="PROVIDER_SUCCESS",
    )

    # N2: the artifact cannot jump straight to released.
    with pytest.raises(TransitionError):
        assert_transition("artifact", ArtifactStatus.draft, ArtifactStatus.released, context)

    for artifact_target in (
        ArtifactStatus.validating,
        ArtifactStatus.approved,
        ArtifactStatus.release_eligible,
        ArtifactStatus.released,
    ):
        current = registry.head("main").status
        assert_transition("artifact", current, artifact_target, context)
        registry.commit(
            branch="main",
            status=artifact_target,
            artifact_type=ArtifactType.campaign_package,
            owner_department=Department.growth,
            content={"stage": artifact_target.value},
            generation_mode="PROVIDER_SUCCESS",
        )

    assert registry.head("main").status is ArtifactStatus.released
    # Full lineage retained: draft + four transitions.
    assert len(registry.lineage("main")) == 5


def test_snapshots_are_json_serializable_for_contract_checks():
    for snapshot in (ontology_snapshot(), lifecycle_snapshot(), role_snapshot()):
        assert json.loads(json.dumps(snapshot)) == snapshot
