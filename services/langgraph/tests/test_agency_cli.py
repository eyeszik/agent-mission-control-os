from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.langgraph.agency.cli import (
    BriefError,
    ProjectBrief,
    build_plan,
    main,
    producing_roles,
    shortest_progress_path,
)
from services.langgraph.agency.kernel.models import EngagementStatus
from services.langgraph.agency.kernel.ontology import ArtifactType

APPROVED_FACTS = {
    "generation_mode": "PRIMARY",
    "approval_exists": True,
    "approval_resolved": True,
    "approval_decision": "approve",
    "brand_safety_passed": True,
}


def _brief(**overrides) -> ProjectBrief:
    payload = {
        "project_name": "Test Engagement",
        "target_artifacts": ["campaign_package"],
        "available_inputs": ["copy_variant", "design_brief", "creative_concept"],
        "facts": dict(APPROVED_FACTS),
    }
    payload.update(overrides)
    return ProjectBrief.model_validate(payload)


class TestBriefValidation:
    def test_rejects_an_artifact_type_the_ontology_does_not_define(self):
        # The superseded stub accepted free-text "deliverable_types" like this.
        with pytest.raises(BriefError, match="ui_component"):
            build_plan(_brief(target_artifacts=["ui_component"]))

    def test_rejects_an_unknown_target_phase(self):
        with pytest.raises(BriefError, match="target_phase"):
            build_plan(_brief(target_phase="shipped"))

    def test_rejects_unknown_brief_fields(self):
        with pytest.raises(Exception):
            ProjectBrief.model_validate(
                {"project_name": "x", "target_artifacts": ["brand_core"], "bogus": 1}
            )

    def test_requires_at_least_one_target_artifact(self):
        with pytest.raises(Exception):
            ProjectBrief.model_validate({"project_name": "x", "target_artifacts": []})


class TestProductionPlan:
    def test_resolves_each_artifact_to_its_producing_role_and_department(self):
        plan = build_plan(_brief(target_artifacts=["brand_core"], available_inputs=["positioning_statement"]))
        step = plan["production_plan"][0]
        assert step["role_id"] == "brand_architect"
        assert step["department"] == "brand"

    def test_reports_the_roles_evidence_floor_from_its_contract(self):
        plan = build_plan(
            _brief(
                target_artifacts=["brand_core"],
                available_inputs=["positioning_statement"],
                evidence_count=1,
            )
        )
        step = plan["production_plan"][0]
        assert step["min_evidence"] == 2
        assert step["evidence_satisfied"] is False
        assert plan["clear"] is False

    def test_evidence_floor_satisfied_when_the_brief_meets_it(self):
        plan = build_plan(
            _brief(
                target_artifacts=["brand_core"],
                available_inputs=["positioning_statement"],
                evidence_count=2,
            )
        )
        assert plan["production_plan"][0]["evidence_satisfied"] is True

    def test_reports_consumed_inputs_that_nothing_supplies(self):
        plan = build_plan(_brief(target_artifacts=["brand_core"], available_inputs=[]))
        assert "positioning_statement" in plan["production_plan"][0]["missing_inputs"]

    def test_an_input_produced_by_another_target_is_not_a_gap(self):
        plan = build_plan(
            _brief(
                target_artifacts=["positioning_statement", "brand_core"],
                available_inputs=["research_brief", "market_analysis"],
                evidence_count=3,
            )
        )
        brand_step = next(s for s in plan["production_plan"] if s["artifact_type"] == "brand_core")
        assert brand_step["missing_inputs"] == []

    def test_surfaces_external_side_effect_roles(self):
        plan = build_plan(_brief(target_artifacts=["media_plan"], available_inputs=["campaign_package"]))
        assert plan["production_plan"][0]["external_side_effect"] is True


class TestLifecycleGuards:
    def test_a_fully_approved_run_reaches_launched(self):
        plan = build_plan(_brief())
        assert plan["reached_phase"] == "launched"
        assert plan["blocked_at"] is None
        assert plan["clear"] is True

    def test_missing_human_approval_blocks_the_client_visible_transition(self):
        plan = build_plan(
            _brief(facts={"generation_mode": "PRIMARY", "brand_safety_passed": True})
        )
        assert plan["reached_phase"] == "launch_ready"
        codes = [f["code"] for f in plan["blocked_at"]["failures"]]
        assert "approval_missing" in codes

    def test_degraded_provenance_blocks_release(self):
        facts = dict(APPROVED_FACTS, generation_mode="FALLBACK_DEGRADED")
        plan = build_plan(_brief(facts=facts))
        codes = [f["code"] for f in plan["blocked_at"]["failures"]]
        assert "degraded_release_block" in codes

    def test_failed_brand_safety_blocks_release(self):
        facts = dict(APPROVED_FACTS, brand_safety_passed=False)
        plan = build_plan(_brief(facts=facts))
        codes = [f["code"] for f in plan["blocked_at"]["failures"]]
        assert "brand_safety_failed" in codes

    def test_external_side_effect_requires_spend_authorization(self):
        plan = build_plan(
            _brief(
                target_artifacts=["media_plan"],
                available_inputs=["campaign_package"],
                facts=dict(APPROVED_FACTS),
            )
        )
        codes = [f["code"] for f in plan["blocked_at"]["failures"]]
        assert "spend_unauthorized" in codes

    def test_authorized_spend_clears_the_external_side_effect_guard(self):
        plan = build_plan(
            _brief(
                target_artifacts=["media_plan"],
                available_inputs=["campaign_package"],
                facts=dict(APPROVED_FACTS, spend_authorized=True),
            )
        )
        assert plan["reached_phase"] == "launched"

    def test_a_rejected_approval_is_not_an_approval(self):
        facts = dict(APPROVED_FACTS, approval_decision="reject")
        plan = build_plan(_brief(facts=facts))
        codes = [f["code"] for f in plan["blocked_at"]["failures"]]
        assert "approval_not_approved" in codes


class TestPathfinding:
    def test_path_starts_at_intake_and_ends_at_the_target(self):
        path = shortest_progress_path(EngagementStatus.intake, EngagementStatus.launched)
        assert path[0] is EngagementStatus.intake
        assert path[-1] is EngagementStatus.launched

    def test_every_step_is_a_legal_kernel_edge(self):
        from services.langgraph.agency.kernel.lifecycle import ENGAGEMENT_TRANSITIONS

        path = shortest_progress_path(EngagementStatus.intake, EngagementStatus.complete)
        for current, nxt in zip(path, path[1:]):
            assert nxt in ENGAGEMENT_TRANSITIONS[current]

    def test_path_avoids_interrupt_states(self):
        path = shortest_progress_path(EngagementStatus.intake, EngagementStatus.launched)
        assert EngagementStatus.blocked not in path
        assert EngagementStatus.degraded not in path

    def test_same_start_and_target_is_a_single_node(self):
        assert shortest_progress_path(EngagementStatus.intake, EngagementStatus.intake) == [
            EngagementStatus.intake
        ]


class TestProducingRoles:
    def test_every_artifact_type_has_a_producing_role(self):
        # Mirrors the kernel's own invariant; the CLI depends on it holding.
        for artifact_type in ArtifactType:
            assert producing_roles(artifact_type), f"{artifact_type.value} has no producer"


class TestCommandLine:
    def _write(self, tmp_path, payload) -> str:
        path = tmp_path / "brief.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_plan_exits_zero_when_clear(self, tmp_path, capsys):
        brief = self._write(
            tmp_path,
            {
                "project_name": "Clear",
                "target_artifacts": ["campaign_package"],
                "available_inputs": ["copy_variant", "design_brief", "creative_concept"],
                "facts": dict(APPROVED_FACTS),
            },
        )
        assert main(["plan", "--input", brief]) == 0

    def test_plan_exits_nonzero_when_blocked(self, tmp_path, capsys):
        brief = self._write(
            tmp_path,
            {
                "project_name": "Blocked",
                "target_artifacts": ["campaign_package"],
                "available_inputs": ["copy_variant", "design_brief", "creative_concept"],
            },
        )
        assert main(["plan", "--input", brief]) == 1

    def test_plan_emits_valid_json_with_the_json_flag(self, tmp_path, capsys):
        brief = self._write(
            tmp_path,
            {
                "project_name": "JSON",
                "target_artifacts": ["campaign_package"],
                "available_inputs": ["copy_variant", "design_brief", "creative_concept"],
                "facts": dict(APPROVED_FACTS),
            },
        )
        main(["plan", "--input", brief, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["reached_phase"] == "launched"

    def test_a_missing_brief_exits_two_without_a_traceback(self, capsys):
        assert main(["plan", "--input", "/nonexistent/brief.json"]) == 2
        assert "not found" in capsys.readouterr().err

    def test_malformed_json_exits_two(self, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert main(["plan", "--input", str(path)]) == 2

    def test_validate_passes_against_the_live_kernel(self, capsys):
        assert main(["validate"]) == 0

    def test_roles_lists_contracts(self, capsys):
        assert main(["roles"]) == 0
        assert "brand_architect" in capsys.readouterr().out

    def test_roles_rejects_an_unknown_department(self, capsys):
        assert main(["roles", "--department", "nonexistent"]) == 1

    def test_the_repo_sample_brief_is_valid_and_clear(self, capsys):
        # The shipped example must stay runnable as the kernel evolves.
        # Resolved from __file__ so the test does not depend on the cwd pytest
        # happens to run from.
        sample = Path(__file__).resolve().parents[3] / "sample_brief.json"
        assert sample.is_file(), f"sample brief missing at {sample}"
        assert main(["plan", "--input", str(sample)]) == 0
