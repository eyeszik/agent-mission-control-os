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
            "generation_provenance": [],
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
