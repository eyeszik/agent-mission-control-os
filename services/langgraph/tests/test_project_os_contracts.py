"""Project OS contracts: vocabulary integrity, SQL parity, and the Zod fixture.

``packages/shared/tests/fixtures/project-os.json`` is generated from the real
Pydantic models below. This test fails if the checked-in fixture drifts from
what the models emit, and the shared vitest suite parses the same file with
the strict Zod twins, so together they prove backend/frontend parity.
Regenerate with: ``AMC_REGENERATE_FIXTURES=1 pytest tests/test_project_os_contracts.py``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from services.langgraph.agency.project_os import models as m
from services.langgraph.agency.project_os.vocabulary import (
    CONTENT_TRANSITIONS,
    MEMORY_AUTHORITY_ORDER,
    MEMORY_SCOPE_AUTHORITIES,
    PROJECT_TRANSITIONS,
    PUBLICATION_TRANSITIONS,
    ContentKind,
    ContentState,
    MemoryScope,
    PublicationState,
    CONTENT_KIND_ARTIFACT,
)
from services.langgraph.agency.kernel.ontology import ARTIFACT_TYPE_OWNER, ArtifactType

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/shared/tests/fixtures/project-os.json"
SQLITE = ROOT / "services/langgraph/persistence/sqlite_db.py"
POSTGRES = ROOT / "supabase/migrations/20261001_amc_project_os_v1.sql"
H = "a" * 64
T = "2026-10-01T00:00:00+00:00"


def build_fixture() -> dict:
    metric = m.ObservedMetric(value=0.42, unit="ratio", sample_size=120, evidence_ref="bench:2026-09", status="OBSERVED")
    unknown = m.ObservedMetric(unit="usd", status="UNKNOWN")
    samples = {
        "ProjectWorkspaceV2": m.ProjectWorkspaceV2(project_id="p1", tenant_id="t1", slug="acme-launch", display_name="Acme Launch",
                                                   lifecycle_state="ACTIVE", brand_name="Acme", manifest_hash=H, created_by="u1", created_at=T, updated_at=T),
        "ProjectManifest": m.ProjectManifest(project_id="p1", tenant_id="t1", slug="acme-launch", display_name="Acme Launch", lifecycle_state="ACTIVE",
                                             folders=("00_admin", "04_brand"), system_folders=("runs",), memory_namespace="memory://t1/p1",
                                             artifact_index_ref="db://a", source_registry_ref="db://s", rights_registry_ref="db://r"),
        "ProjectSnapshot": m.ProjectSnapshot(project_id="p1", tenant_id="t1", lifecycle_state="ACTIVE", run_ids=("r1",), open_approval_count=1,
                                             stale_artifact_count=0, snapshot_hash=H,
                                             artifact_heads=(m.ArtifactHead(artifact_id="a1", artifact_type="brand_core", version=2, version_ref="a1:v2", status="draft", content_hash=H),)),
        "ProjectEvent": m.ProjectEvent(event_id="e1", tenant_id="t1", project_id="p1", sequence=1, event_type="PROJECT_CREATED", actor="u1",
                                       subject_ref="project:p1", payload={"slug": "acme-launch"}, created_at=T),
        "StorageObject": m.StorageObject(object_id="o1", tenant_id="t1", project_id="p1", backend="LOCAL", storage_uri=f"local://t1/p1/{H}",
                                         content_hash=H, byte_size=12, mime_type="text/plain", status="PRESENT", created_at=T, verified_at=T),
        "ArtifactMetadataV2": m.ArtifactMetadataV2(artifact_id="a1", project_id="p1", artifact_key="hero-ig", artifact_type="media_asset",
                                                   owner_department="creative", media_type="image", mime_type="image/png", channel="instagram",
                                                   dimensions="1080x1350", version=1, version_ref="a1:v1", master_artifact_id="a0", variant_of="a0",
                                                   prompt_refs=("prm-1",), dependency_refs=("a0",), content_hash=H, status="draft", approval_state="pending"),
        "ArtifactVersionRecord": m.ArtifactVersionRecord(artifact_id="a1", version=2, version_ref="a1:v2", content_hash=H, change_kind="restore",
                                                         restored_from_version=1, created_by="u1", created_at=T),
        "ArtifactDiff": m.ArtifactDiff(artifact_id="a1", from_version_ref="a1:v1", to_version_ref="a1:v2", content_changed=True, location_changed=True,
                                       fingerprint_changed=True, metadata_changes={"channel": {"from": None, "to": "x"}}, text_diff=("-a", "+b")),
        "AssetRights": m.AssetRights(rights_id="r1", tenant_id="t1", project_id="p1", artifact_id="a1", license="stock", status="active", created_at=T, expires_at=T),
        "ConversationThread": m.ConversationThread(thread_id="th1", tenant_id="t1", project_id="p1", title="Launch", status="open", created_by="u1", created_at=T, updated_at=T),
        "ConversationMessage": m.ConversationMessage(message_id="m1", thread_id="th1", tenant_id="t1", project_id="p1", author="u1", role="user",
                                                     activity_type="ARTIFACT_CREATED", body="Here it is",
                                                     artifact_refs=(m.MessageArtifactRef(artifact_id="a1", version_ref="a1:v1", relation="created"),), created_at=T),
        "ContentAtom": m.ContentAtom(atom_id="at1", tenant_id="t1", project_id="p1", title="Fresh roast", version=1, content_hash=H, created_at=T,
                                     claims=(m.Claim(claim_id="c1", text="Roasted within 48h", evidence_refs=("ev:log",), verification="VERIFIED"),)),
        "ContentVariantSpec": m.ContentVariantSpec(kind="carousel", channel="instagram", title="Fresh roast — carousel", sections=("cover_slide", "claim:c1", "cta_slide"),
                                                   claim_refs=("c1",), constraints=("<=10 slides",), atom_id="at1", atom_version=1),
        "ContentItem": m.ContentItem(content_item_id="ci1", tenant_id="t1", project_id="p1", atom_id="at1", artifact_id="a1", kind="social_post", channel="linkedin",
                                     title="Post", state="SCHEDULED", version=1, claim_refs=("c1",), approved_version=1, approval_ref="content-approval:ci1:v1:u2",
                                     created_by="u1", created_at=T, updated_at=T),
        "Calendar": m.Calendar(calendar_id="cal1", tenant_id="t1", project_id="p1", name="Editorial", created_at=T),
        "ScheduleSlot": m.ScheduleSlot(slot_id="s1", calendar_id="cal1", tenant_id="t1", project_id="p1", channel="linkedin", scheduled_for=T, state="open", created_at=T),
        "ScheduledJob": m.ScheduledJob(job_id="j1", tenant_id="t1", project_id="p1", content_item_id="ci1", job_kind="PUBLISH", due_at=T, status="BLOCKED",
                                       idempotency_key="publish:ci1:v1", block_reasons=("RIGHTS_EXPIRED",), payload={"version": 1}, attempts=0, created_at=T, updated_at=T),
        "ScheduleCadence": m.ScheduleCadence(channel="linkedin", kind="social_post", posts_per_week=3),
        "PublicationAttempt": m.PublicationAttempt(attempt_id="pa1", tenant_id="t1", project_id="p1", job_id="j1", content_item_id="ci1", provider="dry-run",
                                                   mode="DRY_RUN", state="VERIFIED", request_hash=H, idempotency_key="k", external_ref="dryrun:x",
                                                   readback={"request_hash": H}, created_at=T, updated_at=T),
        "PublicationReceipt": m.PublicationReceipt(receipt_id="rc1", attempt_id="pa1", tenant_id="t1", project_id="p1", kind="observation",
                                                   payload={"matches": True}, receipt_hash=H, created_at=T),
        "MemoryRecord": m.MemoryRecord(memory_id="mem1", tenant_id="t1", project_id="p1", scope="M1_BRAND_CANON", authority="BRAND_CANON", subject_key="brand.tagline",
                                       body={"value": "x"}, source_refs=("a1:v3",), status="ACTIVE", content_hash=H, created_by="u1", created_at=T),
        "KnowledgeCapsuleMeta": m.KnowledgeCapsuleMeta(item_id="k1", tenant_id="t1", project_id="p1", domain="search", source_uri="https://example.org",
                                                       rights_class="OPEN_LICENSE", stage="REVIEW", status="AWAITING_REVIEW", evidence_score=0.7,
                                                       claims=(m.KnowledgeClaim(text="claim", corroborating_sources=("https://b",)),), content_hash=H,
                                                       created_at=T, updated_at=T),
        "ProviderCapabilityProfile": m.ProviderCapabilityProfile(profile_id="pr1", tenant_id="t1", provider="freevideoforge", model="local", task="short_video",
                                                                 formats=("mp4",), locality="local", cost_per_unit=unknown, latency_p95_ms=unknown,
                                                                 acceptance_rate=metric, failure_rate=unknown, mode="DRY_RUN", created_at=T),
        "GrowthExperiment": m.GrowthExperiment(experiment_id="x1", tenant_id="t1", project_id="p1", hypothesis="h", target_metric="ctr", segment="all",
                                               intervention="i", sample_requirement=1000, status="CONCLUDED", observed_result={"lift": 0.1},
                                               decision="INCONCLUSIVE", created_at=T, updated_at=T),
        "BrandDriftReport": m.BrandDriftReport(project_id="p1", tenant_id="t1", refresh_candidates=("a1",), not_evaluated=("logo_misuse",), report_hash=H,
                                               findings=(m.BrandDriftFinding(category="colors", severity="warning", artifact_id="a1", detail="off palette", evidence=("#ff0000",)),)),
        "ReproducibilityRecord": m.ReproducibilityRecord(subject_ref="freevideoforge:r1", source_hashes=(H,), schema_version="1.0.0", provider="freevideoforge",
                                                         seed=7, environment_signature=H, execution_args_hash=H, output_hash=H, guarantee="SEEDED_BEST_EFFORT"),
    }
    return {name: model.model_dump(mode="json") for name, model in samples.items()}


def test_fixture_matches_the_pydantic_models():
    generated = json.dumps(build_fixture(), indent=2, sort_keys=True) + "\n"
    if os.environ.get("AMC_REGENERATE_FIXTURES"):
        FIXTURE.write_text(generated, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == generated, "regenerate packages/shared/tests/fixtures/project-os.json"


def test_transition_tables_are_closed():
    for transitions, states in ((CONTENT_TRANSITIONS, ContentState), (PUBLICATION_TRANSITIONS, PublicationState)):
        values = {state.value for state in states}
        assert set(transitions) == values
        assert all(set(targets) <= values for targets in transitions.values())
    assert all(set(t) <= set(PROJECT_TRANSITIONS) for t in PROJECT_TRANSITIONS.values())
    assert CONTENT_TRANSITIONS["ARCHIVED"] == ()


def test_memory_scopes_only_allow_known_authorities():
    assert set(MEMORY_SCOPE_AUTHORITIES) == {scope.value for scope in MemoryScope}
    assert all(set(allowed) <= set(MEMORY_AUTHORITY_ORDER) for allowed in MEMORY_SCOPE_AUTHORITIES.values())
    assert MEMORY_SCOPE_AUTHORITIES["M1_BRAND_CANON"] == ("BRAND_CANON",)
    assert "BRAND_CANON" not in MEMORY_SCOPE_AUTHORITIES["M3_CONVERSATION"]


def test_content_kinds_map_to_owned_n1_types():
    assert set(CONTENT_KIND_ARTIFACT) == {kind.value for kind in ContentKind}
    for artifact_type, department in CONTENT_KIND_ARTIFACT.values():
        assert ARTIFACT_TYPE_OWNER[ArtifactType(artifact_type)].value == department


def _check_values(sql: str, column: str) -> set[str]:
    sets = [set(re.findall(r"'([^']+)'", body)) for body in re.findall(rf"\b{column}\s+(?:text|TEXT)[^,]*?\bin\s*\(([^)]*)\)", sql, re.IGNORECASE)]
    assert sets, f"no CHECK constraint found for {column}"
    return set().union(*sets)


def test_sql_check_constraints_match_the_vocabulary_on_both_backends():
    sqlite_sql = SQLITE.read_text()
    postgres_sql = POSTGRES.read_text()
    for sql in (sqlite_sql, postgres_sql):
        assert _check_values(sql, "lifecycle_state") == set(PROJECT_TRANSITIONS)
        assert {"IDEA", "PUBLISHED", "ARCHIVED"} <= _check_values(sql, "state")
        assert set(MEMORY_AUTHORITY_ORDER) <= _check_values(sql, "authority")
        assert {scope.value for scope in MemoryScope} <= _check_values(sql, "scope")
    sqlite_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sqlite_sql))
    postgres_tables = set(re.findall(r"create table if not exists amc\.(\w+)", postgres_sql))
    assert postgres_tables <= sqlite_tables, f"tables missing from SQLite: {postgres_tables - sqlite_tables}"
