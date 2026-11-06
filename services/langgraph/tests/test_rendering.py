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
    assert 'LICENSE_APPROVAL_REQUIRED' in report.reasons
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


def test_worker_identity_binds_dependency_bytes_and_license(tmp_path, monkeypatch):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    import shutil
    for name in runtime.BUNDLE_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime.WORKER.parent / name, tmp_path / name)
    monkeypatch.setattr(runtime, 'WORKER', tmp_path / 'worker.mjs')
    initial = runtime.fingerprint()['worker_source_hash']
    with (tmp_path / 'rough.cjs').open('a') as file:
        file.write('\n// fixture dependency byte change\n')
    assert runtime.fingerprint()['worker_source_hash'] != initial
    (tmp_path / 'LICENSE.roughjs').unlink()
    assert runtime.fingerprint()['worker_source_hash'] == '0' * 64


@pytest.mark.parametrize('engine', ['paper_js', 'svg_js', 'rough_js'])
@pytest.mark.parametrize('kind', ['rectangle', 'ellipse', 'line'])
def test_real_still_profiles_reach_verified_output(scope, engine, kind):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    principal, project, root = scope
    scene = {'primitives': [{'kind': kind, 'x': 20, 'y': 20, 'width': 100, 'height': 80}]}
    job = service.submit(principal, project, request(engine=engine, scene=scene), root)
    tick = run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    assert tick.final_state == 'WAITING_APPROVAL', tick.reasons
    observed = service.inspect(principal, project, job['job_id'])
    assert observed['job_status'] == 'succeeded'
    assert observed['artifact_status'] == 'verified'
    assert observed['approval_status'] == 'pending'
    assert not observed['release']['allowed']


def test_rejected_output_preserves_real_compute_success(scope, monkeypatch):
    principal, project, root = scope
    # Fictional defective renderer exercises real storage and independent verification.
    monkeypatch.setattr(service, 'blockers', lambda spec: [])
    monkeypatch.setattr(service, 'render', lambda spec: b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
    job = service.submit(principal, project, request(), root)
    run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    observed = service.inspect(principal, project, job['job_id'])
    assert observed['job_status'] == 'succeeded'
    assert observed['artifact_status'] == 'rejected'
    assert observed['verification']['status'] == 'FAILED'
    assert not observed['release']['allowed']
    assert not list_project_artifacts(project)


def test_known_local_compute_failure_is_not_unknown_remote_success(scope, monkeypatch):
    principal, project, root = scope
    monkeypatch.setattr(service, 'blockers', lambda spec: [])
    def fail(spec):
        raise RuntimeError('fictional worker failure')
    monkeypatch.setattr(service, 'render', fail)
    job = service.submit(principal, project, request(), root)
    tick = run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    assert tick.final_state == 'RETRY_PENDING'
    observed = service.inspect(principal, project, job['job_id'])
    assert observed['job_status'] == 'failed'
    assert observed['verification'] is None
    assert not observed['release']['allowed']


def test_persisted_candidate_is_recovered_without_repeating_compute(scope, monkeypatch):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    principal, project, root = scope
    job = service.submit(principal, project, request(), root)
    def interrupted(point):
        if point == 'after_dispatch':
            raise RuntimeError('fictional lost driver after durable candidate receipt')
    with pytest.raises(RuntimeError):
        run_tick(worker_id='fixture-first', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'], hook=interrupted)
    def must_not_render(spec):
        raise AssertionError('recovery must independently read persisted output')
    monkeypatch.setattr(service, 'render', must_not_render)
    recovered = run_tick(worker_id='fixture-takeover', now=datetime.now(timezone.utc) + timedelta(seconds=901),
                         handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    assert recovered.adopted and not recovered.dispatched
    assert recovered.final_state == 'WAITING_APPROVAL'
    assert len(list_project_artifacts(project)) == 1


@pytest.mark.parametrize('attribute', ['style="fill:red"', 'transform="scale(0)"', 'opacity="0"', 'onload="alert(1)"'])
def test_svg_profile_refuses_unreviewed_rendering_attributes(scope, attribute):
    principal, project, _ = scope
    spec = runtime.compile_spec(principal.tenant_id, project, request())
    data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540"><path d="M0 0L1 1" {attribute}/></svg>'.encode()
    assert 'UNEXPECTED_SVG_ATTRIBUTE' in runtime.verify(data, spec).findings


def test_persisted_byte_corruption_invalidates_release_readiness(scope):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter
    principal, project, root = scope
    job = service.submit(principal, project, request(), root)
    run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    stored = store.get_job(job['job_id'])
    content_hash = stored['result']['content_hash']
    LocalStorageAdapter(root)._path(principal.tenant_id, project, content_hash).write_bytes(b'fictional corruption')
    observed = service.inspect(principal, project, job['job_id'])
    assert observed['job_status'] == 'succeeded'
    assert observed['artifact_status'] == 'stale'
    assert not observed['release']['allowed']


@pytest.mark.parametrize('field,value', [('subject_type', 'EXECUTION_PERMISSION'), ('subject_ref', 'fixture-other-artifact'), ('policy_version', 'render.execute/v1')])
def test_execution_or_other_subject_approval_cannot_authorize_artifact_release(scope, monkeypatch, field, value):
    if not runtime.WORKER.is_file():
        pytest.skip('NOT_RUN: renderer build required')
    from services.langgraph.persistence.database import table
    principal, project, root = scope
    job = service.submit(principal, project, request(), root)
    run_tick(worker_id='fixture-controller', handlers={service.KIND: service.RenderHandler()}, job_id=job['job_id'])
    result = service.inspect(principal, project, job['job_id'])
    as_user(monkeypatch, 'fixture-independent-reviewer', tenant=principal.tenant_id, projects=project)
    response = client.post(f"/approvals/{result['approval_id']}/decide", json={'decision': 'approve'}, headers=headers())
    assert response.status_code == 200, response.text
    assert service.inspect(principal, project, job['job_id'])['release']['allowed']
    # Explicit test-only alteration represents a decision for a different purpose/subject.
    assert field in {'subject_type', 'subject_ref', 'policy_version'}
    with atomic_transaction() as db:
        db.execute(f"UPDATE {table('approvals')} SET {field} = ? WHERE approval_id = ?", (value, result['approval_id']))
    observed = service.inspect(principal, project, job['job_id'])
    assert not observed['release']['allowed']
    assert 'APPROVAL_PURPOSE_MISMATCH' in observed['release']['reasons']
    with pytest.raises(ValueError):
        service.resume(principal, project, job['job_id'])
