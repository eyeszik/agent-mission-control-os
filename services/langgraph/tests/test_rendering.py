"""Fictional render requests exercise real persistence and refusal boundaries."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.durable.ticks import run_tick
from services.langgraph.agency.rendering.contracts import RenderRequest
from services.langgraph.agency.rendering import runtime, service
from services.langgraph.persistence.database import atomic_transaction
from services.langgraph.persistence import durable_runs as store
from services.langgraph.persistence.projects import create_project_workspace, list_project_artifacts
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import client, headers, as_user


def request(**changes):
    return RenderRequest.model_validate({'workflow_id': 'fixture-workflow', 'task_id': 'fixture-task',
        'brief': 'Fictional geometric study for automated validation',
        'scene': {'primitives': [{'kind': 'rectangle', 'x': 20, 'y': 20, 'width': 100, 'height': 80}]}, **changes})


@pytest.fixture
def scope(tmp_path):
    tenant, project = 'fixture-render-' + uuid4().hex, 'prj-' + uuid4().hex[:12]
    create_project_workspace(tenant_id=tenant, project_id=project, actor='fixture-author', display_name='Fictional Render Fixture',
                             slug=project, export_root=tmp_path)
    return Principal(user_id='fixture-author', tenant_id=tenant, role='admin', allowed_project_ids=frozenset({project})), project, tmp_path


def test_hash_binds_every_render_input_and_scope(scope):
    principal, project, _ = scope
    base = runtime.compile_spec(principal.tenant_id, project, request())
    for change in ({'dimensions': {'width': 800, 'height': 600}}, {'task_id': 'fixture-other'}, {'scene_revision': 2}, {'seed': 12},
                   {'clock': {'fps_numerator': 24, 'fps_denominator': 1, 'total_frames': 1}}):
        assert runtime.compile_spec(principal.tenant_id, project, request(**change)).spec_hash != base.spec_hash
    assert runtime.compile_spec('fixture-other-tenant', project, request()).spec_hash != base.spec_hash
    assert runtime.compile_spec(principal.tenant_id, 'fixture-other-project', request()).spec_hash != base.spec_hash
    assert runtime.compile_spec(principal.tenant_id, project, request()).spec_hash == base.spec_hash


@pytest.mark.parametrize('change', [ {'brief': '          '}, {'fencing_token': 2}, {'tenant_id': 'injected'},
    {'dimensions': {'width': -1, 'height': 10}}, {'output_format': 'svg', 'clock': {'total_frames': 20}},
    {'scene': {'primitives': [{'kind': 'rectangle', 'x': float('nan'), 'y': 0, 'width': 20, 'height': 20}]}},
    {'scene': {'primitives': [{'kind': 'script', 'x': 0, 'y': 0, 'width': 20, 'height': 20}]}},
    {'scene': {'primitives': [{'kind': 'rectangle', 'x': 0, 'y': 0, 'width': 20, 'height': 20, 'fill': 'url(https://evil.invalid)'}]}}])
def test_invalid_scene_or_client_authority_is_refused(change):
    with pytest.raises(ValidationError):
        request(**change)


def test_atomic_scope_rolls_back_composed_existing_apis(scope):
    principal, project, _ = scope
    job_id = 'fixture-rollback-' + uuid4().hex
    with pytest.raises(RuntimeError, match='fixture rollback'):
        with atomic_transaction():
            store.create_job(tenant_id=principal.tenant_id, project_id=project, kind='fixture', spec={}, spec_hash='0'*64,
                              requested_by=principal.user_id, due_at=datetime.now(timezone.utc), job_id=job_id)
            assert store.get_job(job_id) is not None
            raise RuntimeError('fixture rollback')
    assert store.get_job(job_id) is None


def test_missing_engine_stays_blocked_and_does_not_create_artifact(scope):
    principal, project, root = scope
    submitted = service.submit(principal, project, request(engine='remotion'), root)
    report = run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=submitted['job_id'])
    assert report.final_state == 'BLOCKED_ENVIRONMENT'
    assert 'ADAPTER_NOT_IMPLEMENTED' in report.reasons
    assert not list_project_artifacts(project)


def test_real_worker_stores_verifies_and_waits_for_separate_approval(scope):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: build @amc/creative-renderer before real worker test')
    principal, project, root = scope
    submitted = service.submit(principal, project, request(), root)
    report = run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=submitted['job_id'])
    assert report.final_state == 'WAITING_APPROVAL', report.reasons
    result = service.inspect(principal, project, submitted['job_id'])
    assert result['job_status'] == 'succeeded'
    assert result['artifact_status'] == 'verified'
    assert result['approval_status'] == 'pending'
    assert not result['release']['allowed']
    same = service.submit(principal, project, request(), root)
    assert same['job_id'] == submitted['job_id']
    assert len(list_project_artifacts(project)) == 1


def test_cancel_revokes_fence_and_read_does_not_execute(scope):
    principal, project, root = scope
    submitted = service.submit(principal, project, request(), root)
    job, _ = store.claim_due_job(worker_id='fixture-worker', now=datetime.now(timezone.utc), lease_seconds=60, job_id=submitted['job_id'])
    assert service.inspect(principal, project, job['job_id'])['artifact_id'] is None
    service.cancel(principal, project, job['job_id'])
    with pytest.raises(store.StaleFence):
        store.transition(job, RunState.PRECHECK, fencing_token=job['lease_token'], now=datetime.now(timezone.utc))
    assert service.inspect(principal, project, job['job_id'])['workflow_status'] == 'cancelled'
    assert not list_project_artifacts(project)


def test_readback_rejects_active_content_and_wrong_dimensions(scope):
    principal, project, _ = scope
    spec = runtime.compile_spec(principal.tenant_id, project, request())
    for data in (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>',
                 b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540"><script>alert(1)</script></svg>'):
        report = runtime.verify(data, spec)
        assert report.status == 'FAILED'
        assert report.content_hash == hashlib.sha256(data).hexdigest()


def test_authenticated_api_replays_and_get_is_observational(scope, monkeypatch):
    principal, project, root = scope
    as_user(monkeypatch, principal.user_id, tenant=principal.tenant_id, projects=project)
    monkeypatch.setenv('AMC_EXPORT_ROOT', str(root))
    endpoint = f'/foundry/projects/{project}/renders'
    key = headers()
    first = client.post(endpoint, json=request().model_dump(mode='json'), headers=key)
    assert first.status_code == 202, first.text
    assert client.post(endpoint, json=request().model_dump(mode='json'), headers=key).json() == first.json()
    assert client.post(endpoint, json=request(seed=123).model_dump(mode='json'), headers=key).status_code == 409
    job = first.json()['job_id']
    before = store.get_job(job)['lease_token']
    assert client.get(f'{endpoint}/{job}').status_code == 200
    assert store.get_job(job)['lease_token'] == before
    as_user(monkeypatch, 'fixture-outsider', tenant='fixture-other-tenant', projects='*')
    assert client.get(f'{endpoint}/{job}').status_code in (403,404)


def test_quarantine_is_authorized_cancels_work_and_preserves_records(scope):
    from fastapi import HTTPException
    from services.langgraph.agency.rendering.contracts import RenderEngineId
    principal, project, root = scope
    queued = service.submit(principal, project, request(), root)
    unprivileged = Principal(user_id='fixture-reader', tenant_id=principal.tenant_id, role='viewer', allowed_project_ids=frozenset({project}))
    with pytest.raises(HTTPException):
        service.quarantine(unprivileged, project, RenderEngineId.ROUGH, True, 'Fixture incident response')
    result = service.quarantine(principal, project, RenderEngineId.ROUGH, True, 'Fixture incident response')
    assert result['quarantined']
    assert service.inspect(principal, project, queued['job_id'])['workflow_status'] == 'cancelled'
    assert store.get_job(queued['job_id']) is not None
    # A different logical task cannot escape the same project quarantine.
    next_job = service.submit(principal, project, request(task_id='fixture-next'), root)
    report = run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=next_job['job_id'])
    assert 'ENGINE_QUARANTINED' in report.reasons


def test_fence_revoked_after_worker_output_prevents_artifact_registration(scope):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    principal, project, root = scope
    job = service.submit(principal, project, request(), root)
    def crash_boundary(point):
        if point == 'before_commit':
            service.cancel(principal, project, job['job_id'])
    with pytest.raises(store.StaleFence):
        run_tick(worker_id='fixture-worker', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'], hook=crash_boundary)
    assert not list_project_artifacts(project)


def test_human_rejection_never_releases_or_dispatches_again(scope, monkeypatch):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    principal, project, root = scope
    job = service.submit(principal, project, request(), root)
    run_tick(worker_id='fixture-worker', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    result = service.inspect(principal, project, job['job_id'])
    as_user(monkeypatch, 'fixture-independent-reviewer', tenant=principal.tenant_id, projects=project)
    response = client.post(f"/approvals/{result['approval_id']}/decide", json={'decision':'reject'}, headers=headers())
    assert response.status_code == 200, response.text
    final = service.resume(principal, project, job['job_id'])
    assert final['approval_status'] == 'rejected' and not final['release']['allowed']
    again = run_tick(worker_id='fixture-worker', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    assert not again.dispatched


def test_reader_cannot_dispatch_or_cancel(scope):
    principal, project, root = scope
    viewer = Principal(user_id='fixture-viewer', tenant_id=principal.tenant_id, role='viewer', allowed_project_ids=frozenset({project}))
    with pytest.raises(PermissionError):
        service.submit(viewer, project, request(), root)
    job = service.submit(principal, project, request(), root)
    assert service.inspect(viewer, project, job['job_id'])['job_id'] == job['job_id']
    with pytest.raises(PermissionError):
        service.cancel(viewer, project, job['job_id'])
