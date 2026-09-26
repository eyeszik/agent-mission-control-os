from uuid import uuid4


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _agency_result(subject: str) -> dict:
    return {
        "agency": {
            "campaign_package": {
                "brief": {"brand_name": subject},
                "strategy": {"positioning_statement": f"{subject} positioning"},
                "copy_variants": [],
                "concepts": [],
            },
            "qa_report": {"brand_safety_passed": True},
            "generation_provenance": [
                {
                    "task": "copywriting",
                    "mode": "PROVIDER_SUCCESS",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "schema_version": "agency-json-v1",
                    "prompt_version": "agency-v1",
                    "prompt_hash": "a" * 64,
                    "attempts": 1,
                    "started_at": "2026-08-25T00:00:00+00:00",
                    "completed_at": "2026-08-25T00:00:01+00:00",
                    "fallback_used": False,
                    "error_class": None,
                }
            ],
            "degraded": False,
        }
    }


def test_run_result_commit_creates_then_revises_protected_artifact_automatically():
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.approvals import bind_approval_subject, create_approval_request, get_approval
    from services.langgraph.persistence.lineage import list_project_lineage_remediations
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()

    run_id = _id("run")
    tenant_id = "tenant_1"
    project_id = "proj_1"
    artifact_id = f"art-protected-{run_id}"

    create_run_record(run_id, tenant_id, project_id, "branding_marketing_agency", "running", {})
    approval = create_approval_request(
        run_id,
        tenant_id,
        project_id,
        "review generated campaign package",
        0.8,
    )

    initial = update_run_status(run_id, "needs_approval", _agency_result("Northwind"))
    assert initial is not None

    artifact = get_artifact(artifact_id)
    assert artifact is not None
    assert artifact["version"] == 1
    assert artifact["content_hash"]

    bind_approval_subject(
        approval["approval_id"],
        subject_hash=artifact["content_hash"],
        subject_ref=artifact_id,
        subject_version_ref=f"{artifact_id}:v1",
    )

    updated = update_run_status(run_id, "needs_approval", _agency_result("Contoso"))
    assert updated is not None

    revised = get_artifact(artifact_id)
    assert revised is not None
    assert revised["version"] == 2
    assert revised["content_hash"] != artifact["content_hash"]

    stale = get_approval(approval["approval_id"])
    assert stale is not None
    assert stale["status"] == "stale"
    assert stale["stale_reason"].startswith("artifact_version_changed:")

    queue = list_project_lineage_remediations(project_id, tenant_id)
    assert queue
    assert queue[0]["run_id"] == run_id
    assert queue[0]["artifact_id"] == artifact_id
    assert queue[0]["status"] == "OPEN"


def test_run_result_commit_opens_and_discharges_invalidation_obligations():
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.app.runtime_support import trust_kernel
    from services.langgraph.persistence.invalidation import discharge_run_obligations, open_demanded_obligations
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()

    run_id = _id("run-obligation")
    trust_kernel().bind_project(tenant_id="tenant_1", project_id="proj_1")
    create_run_record(run_id, "tenant_1", "proj_1", "branding_marketing_agency", "running", {})
    update_run_status(run_id, "needs_approval", _agency_result("Northwind"))

    updated = _agency_result("Contoso")
    updated["agency"]["generation_provenance"][0]["prompt_hash"] = "b" * 64
    updated["agency"]["generation_provenance"][0]["model"] = "gpt-5-mini"
    update_run_status(run_id, "needs_approval", updated)

    open_rows = open_demanded_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    assert {row["event_class"] for row in open_rows} >= {"SPEC_CHANGE", "MODEL_PARAM_CHANGE", "TOOL_RESULT_CHANGE"}

    discharged = discharge_run_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    assert discharged
    assert all(item["state"] == "DISCHARGED_RECOMPUTE" for item in discharged)


def test_run_result_commit_persists_hook_gap_for_unsourced_classes_and_blocks_compile():
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.persistence.invalidation import latest_branch_obligations, open_demanded_obligations, run_compile_gate
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()

    run_id = _id("run-hook-gap")
    project_id = _id("proj-hook-gap")
    create_run_record(run_id, "tenant_1", project_id, "branding_marketing_agency", "running", {})
    update_run_status(
        run_id,
        "needs_approval",
        {
            "agency": {
                "campaign_package": {"brief": {"brand_name": "Northwind"}},
                "qa_report": {"brand_safety_passed": True},
                "generation_provenance": [],
                "degraded": False,
            }
        },
    )

    open_rows = open_demanded_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    by_class = {row["event_class"]: row for row in open_rows}
    latest = latest_branch_obligations(run_id, f"art-protected-{run_id}")
    # Memory/window gaps are retained as explicit evidence but are not demanded
    # by the current branding pipeline because it has no such dependencies.
    assert latest["MEMORY_WRITE"]["state"] == "HOOK_GAP"
    assert not latest["MEMORY_WRITE"]["demanded"]
    assert latest["CLOCK_WINDOW_ADVANCE"]["state"] == "HOOK_GAP"
    assert not latest["CLOCK_WINDOW_ADVANCE"]["demanded"]
    assert latest["ACL_SECRET_CHANGE"]["state"] in {"HOOK_GAP", "DISCHARGED_RECOMPUTE"}
    # Missing generation provenance remains a demanded release blocker.
    assert by_class["SPEC_CHANGE"]["state"] == "HOOK_GAP"
    assert by_class["MODEL_PARAM_CHANGE"]["state"] == "HOOK_GAP"
    assert by_class["SCHEMA_CHANGE"]["state"] == "HOOK_GAP"

    gate = run_compile_gate(run_id)
    assert gate["compile_blocked"] is True
    assert any(item["state"] == "HOOK_GAP" for item in gate["open_obligations"])


def test_invalidation_snapshot_fold_survives_runtime_restart(monkeypatch, tmp_path):
    db_path = tmp_path / "restart.db"
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(db_path))

    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.app import runtime_support
    from services.langgraph.app.runtime_support import trust_kernel
    from services.langgraph.persistence.invalidation import project_snapshot_fold, project_snapshot_state
    from services.langgraph.persistence.approvals import bind_approval_subject, create_approval_request
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()

    run_id = _id("run-restart")
    tenant_id = "tenant_1"
    project_id = "proj_1"
    trust_kernel().bind_project(tenant_id=tenant_id, project_id=project_id)
    create_run_record(run_id, tenant_id, project_id, "branding_marketing_agency", "running", {})
    approval = create_approval_request(
        run_id,
        tenant_id,
        project_id,
        "review generated campaign package",
        0.8,
    )
    update_run_status(run_id, "needs_approval", _agency_result("Northwind"))
    bind_approval_subject(
        approval["approval_id"],
        subject_hash="a" * 64,
        subject_ref=f"art-protected-{run_id}",
        subject_version_ref=f"art-protected-{run_id}:v1",
    )

    revised = _agency_result("Contoso")
    revised["agency"]["generation_provenance"][0]["prompt_hash"] = "c" * 64
    update_run_status(run_id, "needs_approval", revised)

    before_state = project_snapshot_state(tenant_id=tenant_id, project_id=project_id, run_id=run_id)
    before = project_snapshot_fold(tenant_id=tenant_id, project_id=project_id, run_id=run_id)
    runtime_support.trust_kernel.cache_clear()
    runtime_support.runtime_queue.cache_clear()
    after_state = project_snapshot_state(tenant_id=tenant_id, project_id=project_id, run_id=run_id)
    after = project_snapshot_fold(tenant_id=tenant_id, project_id=project_id, run_id=run_id)

    assert before_state == after_state
    assert before_state["compile_blocked"] is True
    assert before_state["lineage_remediations"]
    assert before_state["stale_approvals"]
    assert before == after


def test_restart_restores_exact_hook_gap_state_without_global_invalidate(monkeypatch, tmp_path):
    db_path = tmp_path / "restart-hook-gap.db"
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(db_path))

    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.app import runtime_support
    from services.langgraph.persistence.invalidation import project_snapshot_fold, project_snapshot_state
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()

    affected_run_id = _id("run-restart-gap")
    unaffected_run_id = _id("run-restart-clean")
    create_run_record(affected_run_id, "tenant_1", "proj_1", "branding_marketing_agency", "running", {})
    create_run_record(unaffected_run_id, "tenant_1", "proj_1", "branding_marketing_agency", "running", {})

    update_run_status(
        affected_run_id,
        "needs_approval",
        {
            "agency": {
                "campaign_package": {"brief": {"brand_name": "Gap"}},
                "qa_report": {"brand_safety_passed": True},
                "generation_provenance": [],
                "degraded": False,
            }
        },
    )
    before_affected = project_snapshot_state(tenant_id="tenant_1", project_id="proj_1", run_id=affected_run_id)
    before_unaffected = project_snapshot_state(tenant_id="tenant_1", project_id="proj_1", run_id=unaffected_run_id)
    before_fold = project_snapshot_fold(tenant_id="tenant_1", project_id="proj_1", run_id=affected_run_id)

    runtime_support.trust_kernel.cache_clear()
    runtime_support.runtime_queue.cache_clear()

    after_affected = project_snapshot_state(tenant_id="tenant_1", project_id="proj_1", run_id=affected_run_id)
    after_unaffected = project_snapshot_state(tenant_id="tenant_1", project_id="proj_1", run_id=unaffected_run_id)
    after_fold = project_snapshot_fold(tenant_id="tenant_1", project_id="proj_1", run_id=affected_run_id)

    assert before_affected == after_affected
    assert before_unaffected == after_unaffected
    assert before_affected["compile_blocked"] is True
    assert before_unaffected["compile_blocked"] is False
    assert before_fold == after_fold


def test_run_compile_gate_blocks_on_open_lineage_remediation_without_stale_approval():
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.persistence.agency_kernel import create_artifact, create_engagement, record_artifact_revision
    from services.langgraph.persistence.invalidation import run_compile_gate
    from services.langgraph.persistence.runs import create_run_record

    sqlite_db.init_db()

    run_id = _id("run-lineage-gate")
    tenant_id = "tenant_1"
    project_id = "proj_1"
    engagement_id = f"eng-lineage-{run_id}"
    artifact_id = f"art-protected-{run_id}"

    create_run_record(run_id, tenant_id, project_id, "branding_marketing_agency", "needs_approval", {})
    create_engagement(
        engagement_id,
        tenant_id,
        project_id,
        "Protected runtime artifact lineage",
        "Canonical protected artifact for ambient lineage invalidation",
        status="active",
    )
    create_artifact(
        artifact_id,
        engagement_id,
        tenant_id,
        project_id,
        "campaign_package",
        "growth",
        status="approved",
        content_hash="a" * 64,
        metadata={"protected_run_id": run_id, "canonical_protected_artifact": True},
    )
    record_artifact_revision(artifact_id, content_hash="b" * 64)

    gate = run_compile_gate(run_id)
    assert gate["stale_approvals"] == []
    assert gate["lineage_remediations"]
    assert gate["compile_blocked"] is True
