"""Trusted control-plane integration over existing durable jobs and Project OS."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.persistence import durable_runs as store
from services.langgraph.persistence.database import atomic_transaction, is_postgres, json_param, table
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.runs import create_run_record, get_run_record, update_run_status
from services.langgraph.security.auth import Principal
from .contracts import RenderRequest, RenderSpecification
from .runtime import blockers, compile_spec, render, verify

KIND = 'governed_creative_render'


def _now():
    return datetime.now(timezone.utc)


def _scope(principal: Principal, project: str):
    from services.langgraph.api.routes._project_common import authorize_project_access
    return authorize_project_access(principal, project)


def _principal(job):
    # This is a recorded requester, not a worker-provided authority object.
    return Principal(user_id=job['requested_by'], tenant_id=job['tenant_id'], role='operator',
                     allowed_project_ids=frozenset({job['project_id']}))


def _spec(job):
    spec = RenderSpecification.model_validate(job['spec']['render'])
    if spec.spec_hash != job['spec_hash'] or (spec.tenant_id, spec.project_id) != (job['tenant_id'], job['project_id']):
        raise ValueError('RENDER_SPEC_SCOPE_OR_HASH_MISMATCH')
    return spec


def _event(job, kind, payload=None):
    record_event(job['job_id'], job['tenant_id'], job['project_id'], 'rendering', kind, payload or {})


def _candidate(job, **changes):
    """Persist observations under the current fence, independently of acceptance."""
    with atomic_transaction() as db:
        _locked(db, job['job_id'])
        store._active_fence(db, job_id=job['job_id'], fencing_token=job['lease_token'], now=_now())
        # Read through the public decoder: SQLite JSON and PostgreSQL JSONB differ.
        result = dict(store.get_job(job['job_id']).get('result') or {})
        result.update(changes)
        db.execute(f"UPDATE {table('durable_jobs')} SET result = ? WHERE job_id = ? AND lease_token = ?",
                   (json_param(result), job['job_id'], job['lease_token']))
        return result


def submit(principal: Principal, project: str, request: RenderRequest, export_root: Path) -> dict:
    _scope(principal, project)
    _command_authority(principal)
    spec = compile_spec(principal.tenant_id, project, request)
    job_id = 'render-' + spec.spec_hash[:40]
    # The durable job itself is the transactional queue/intention record. No
    # second broker/outbox is claimed; an external broker remains unavailable.
    with atomic_transaction():
        job = store.create_job(tenant_id=principal.tenant_id, project_id=project, kind=KIND,
                               spec={'render': spec.model_dump(mode='json'), 'export_root': str(export_root)},
                               spec_hash=spec.spec_hash, requested_by=principal.user_id, due_at=_now(), job_id=job_id)
        if get_run_record(job_id) is None:
            create_run_record(job_id, principal.tenant_id, project, KIND, 'queued',
                              {'initiated_by': principal.user_id, 'spec_hash': spec.spec_hash}, enforce_limits=True)
            _event(job, 'RENDER_QUEUED', {'engine': request.engine.value, 'spec_hash': spec.spec_hash})
    return inspect(principal, project, job_id)


def inspect(principal, project, job_id):
    _scope(principal, project)
    job = store.get_job(job_id)
    if not job or job['kind'] != KIND or (job['tenant_id'], job['project_id']) != (principal.tenant_id, project):
        raise LookupError('render job not found')
    result = job.get('result') or {}
    verification = result.get('verification')
    approval = result.get('approval')
    release = artifact_release_verdict(simulated=False, verification_passed=bool(verification and verification['status'] == 'PASSED'),
        artifact_id=result.get('artifact_id'), verified_version=result.get('version'), verified_hash=result.get('content_hash'),
        approval_id=approval.get('approval_id') if approval else None, tenant_id=job['tenant_id'], project_id=project)
    from services.langgraph.persistence.approvals import get_approval
    current_approval = get_approval(approval['approval_id']) if approval else None
    approval_state = 'not_requested' if not current_approval else ('invalidated' if current_approval['status'] == 'stale' else current_approval.get('decision') if current_approval['status'] == 'resolved' else 'pending')
    approval_state = {'approve': 'approved', 'reject': 'rejected'}.get(approval_state, approval_state)
    if current_approval and current_approval.get('subject_version_ref') != str(result.get('version')):
        release = release.model_copy(update={'allowed': False, 'reasons': (*release.reasons, 'APPROVAL_VERSION_MISMATCH')})
    if current_approval and (current_approval.get('subject_type') != 'RENDER_ARTIFACT'
            or current_approval.get('subject_ref') != result.get('artifact_id')
            or current_approval.get('policy_version') != 'amc-render-release/v1'):
        release = release.model_copy(update={'allowed': False, 'reasons': (*release.reasons, 'APPROVAL_PURPOSE_MISMATCH')})
    # Historical verification is not proof that persisted bytes remain readable.
    # This GET observes bytes and authority; it never dispatches or writes state.
    if result.get('artifact_id') and verification and verification['status'] == 'PASSED':
        try:
            candidate = result.get('candidate')
            if not candidate:  # Compatibility with jobs persisted before candidate receipts.
                from services.langgraph.persistence.agency_kernel import get_artifact
                head = get_artifact(result['artifact_id'])
                candidate = {'storage_uri': head['content_location']}
            data = LocalStorageAdapter(Path(job['spec']['export_root'])).get_bytes(candidate['storage_uri'])
            measured = verify(data, _spec(job))
            if measured.status != 'PASSED' or measured.content_hash != result['content_hash']:
                raise ValueError('PERSISTED_OUTPUT_CHANGED')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            release = release.model_copy(update={'allowed': False, 'reasons': (*release.reasons, 'VERIFICATION_STALE: persisted output unavailable or changed')})
    if quarantined(job):
        release = release.model_copy(update={'allowed': False, 'reasons': (*release.reasons, 'ENGINE_QUARANTINED')})
    state = job['state']
    workflow = 'awaiting_approval' if state == RunState.WAITING_APPROVAL.value else ('cancelled' if state == RunState.STOPPED.value else
                'blocked' if state.startswith('BLOCKED_') or state in {'INCONCLUSIVE', 'DEAD_LETTER'} else 'executing' if job.get('lease_owner') else 'queued')
    if release.allowed and state == RunState.DORMANT.value:
        workflow = 'completed'
    elif approval_state == 'rejected':
        workflow = 'blocked'
    compute = result.get('compute_status')
    if compute is None:  # Preserve existing persisted jobs without inventing observations.
        compute = 'succeeded' if result.get('artifact_id') else ('cancelled' if state == 'STOPPED' else 'running' if job.get('lease_owner') else 'queued')
    if state == RunState.STOPPED.value and compute == 'running':
        compute = 'cancel_requested'  # Revoking acceptance does not prove process termination.
    artifact_state = 'pending_verification'
    if verification:
        artifact_state = {'PASSED': 'verified', 'FAILED': 'rejected', 'INCONCLUSIVE': 'pending_verification'}[verification['status']]
        if any(r.startswith('VERIFICATION_STALE') for r in release.reasons):
            artifact_state = 'stale'
    return {'job_id': job_id, 'run_id': (approval or {}).get('run_id') or job_id, 'spec_hash': job['spec_hash'], 'engine': job['spec']['render']['request']['engine'],
            'workflow_status': workflow, 'job_status': compute,
            'artifact_status': artifact_state,
            'approval_status': approval_state,
            'blockers': job.get('last_reasons') or [], 'artifact_id': result.get('artifact_id'), 'artifact_version': result.get('version'),
            'content_hash': result.get('content_hash'), 'approval_id': (approval or {}).get('approval_id'),
            'verification': verification, 'release': release.model_dump(mode='json'), 'external_effects': 'none'}


def _locked(db, job_id):
    row = db.execute(f"SELECT job_id FROM {table('durable_jobs')} WHERE job_id = ?" + (' FOR UPDATE' if is_postgres() else ''), (job_id,)).fetchone()
    if row is None:
        raise LookupError(job_id)


def cancel(principal, project, job_id):
    _command_authority(principal)
    inspect(principal, project, job_id)
    with atomic_transaction() as db:
        _policy_lock(db, store.get_job(job_id))
        _locked(db, job_id)
        job = store.get_job(job_id)
        if job['state'] == RunState.STOPPED.value:
            return inspect(principal, project, job_id)
        # Authorized cancellation revokes the active lease. A late render may
        # finish locally but its old fence cannot register an artifact.
        from services.langgraph.agency.durable.fsm import assert_transition
        assert_transition(job['state'], RunState.STOPPED)
        db.execute(f"UPDATE {table('durable_jobs')} SET state = ?, lease_token = lease_token + 1, version = version + 1, lease_owner = NULL, lease_expires_at = NULL, updated_at = ? WHERE job_id = ? AND version = ?",
                   (RunState.STOPPED.value, store.iso(_now()), job_id, job['version']))
        db.execute(f"INSERT INTO {table('durable_transitions')} (job_id,tenant_id,project_id,from_state,to_state,fencing_token,logical_tick,reason,observed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (job_id,job['tenant_id'],project,job['state'],RunState.STOPPED.value,job['lease_token']+1,job['logical_tick'],'authorized cancellation',store.iso(_now())))
        update_run_status(job_id, 'cancelled')
        _event(job, 'RENDER_CANCELLED', {'accepted_effects': 'none_after_fence_revocation'})
    return inspect(principal, project, job_id)


class RenderHandler:
    operation = 'creative.render'
    contract_version = 'amc-render/v1'
    retry_class = 'RETRY_SAFE'

    def target(self, job):
        return 'creative-' + job['spec_hash'][:32]

    def input_hash(self, job):
        return _spec(job).spec_hash

    def environment_fingerprint(self, job):
        from .runtime import fingerprint
        return canonical_hash(fingerprint())

    def precheck(self, job):
        from services.langgraph.persistence.projects import get_project_workspace
        workspace = get_project_workspace(job['project_id'])
        if not workspace or workspace.tenant_id != job['tenant_id'] or workspace.lifecycle_state.value == 'ARCHIVED':
            return RunState.BLOCKED_AUTHORITY, ['PROJECT_NOT_ADMISSIBLE']
        reasons = blockers(_spec(job))
        if quarantined(job):
            reasons.append('ENGINE_QUARANTINED')
        if reasons:
            update_run_status(job['job_id'], 'blocked')
            _event(job, 'RENDER_BLOCKED', {'reasons': reasons})
            return RunState.BLOCKED_ENVIRONMENT, reasons
        _event(job, 'RENDER_ADMITTED', {'spec_hash': job['spec_hash']})
        return None, []

    def pre_image(self, job):
        return {'spec_hash': job['spec_hash']}

    def dispatch(self, job):
        spec = _spec(job)
        _candidate(job, compute_status='running', verification=None)
        try:
            data = render(spec)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            _candidate(job, compute_status='failed', failure_code=type(exc).__name__)
            # The local renderer has no external effects; this is a known failure,
            # unlike an unknown remote dispatch outcome.
            return {'failed': True, 'reasons': ['LOCAL_RENDER_FAILED:' + type(exc).__name__]}
        _candidate(job, compute_status='succeeded')
        adapter = LocalStorageAdapter(Path(job['spec']['export_root']))
        obj = adapter.put_bytes(tenant_id=job['tenant_id'], project_id=job['project_id'], data=data)
        receipt = {'storage_uri': obj.storage_uri, 'content_hash': obj.content_hash, 'route': spec.request.engine.value}
        _candidate(job, candidate=receipt)
        return receipt

    def observe(self, job, dispatched):
        adapter = LocalStorageAdapter(Path(job['spec']['export_root']))
        data = adapter.get_bytes(dispatched['storage_uri'])
        report = verify(data, _spec(job))
        if report.content_hash != dispatched['content_hash']:
            raise ValueError('READBACK_HASH_MISMATCH')
        _candidate(job, verification=report.model_dump(mode='json'))
        return {**dispatched, 'verification': report.model_dump(mode='json')}

    def verify(self, job, observation):
        return observation['verification']

    def reconcile(self, job, intent):
        # An interrupted local render can be adopted only from persisted bytes.
        candidate = (job.get('result') or {}).get('candidate')
        if candidate:
            return 'ADOPT', self.observe(job, candidate)
        return 'REDO', None

    def on_commit(self, job, observation, verification):
        from services.langgraph.persistence.projects import create_project_artifact, project_artifact_id
        from services.langgraph.persistence.agency_kernel import get_artifact
        with atomic_transaction() as db:
            _policy_lock(db, job)
            _locked(db, job['job_id'])
            store._active_fence(db, job_id=job['job_id'], fencing_token=job['lease_token'], now=_now())
            if quarantined(job):
                raise PermissionError('ENGINE_QUARANTINED')
            adapter = LocalStorageAdapter(Path(job['spec']['export_root']))
            data = adapter.get_bytes(observation['storage_uri'])
            readback = verify(data, _spec(job))
            if readback.status != 'PASSED' or readback.content_hash != observation['content_hash']:
                raise ValueError('CANDIDATE_VERIFICATION_CHANGED')
            aid = project_artifact_id(job['project_id'], self.target(job))
            head = get_artifact(aid)
            if head is None:
                meta = create_project_artifact(tenant_id=job['tenant_id'], project_id=job['project_id'], actor=job['requested_by'],
                    artifact_key=self.target(job), artifact_type='media_asset', adapter=adapter,
                    content_hash=readback.content_hash, storage_uri=observation['storage_uri'],
                    v2={'mime_type': 'image/svg+xml', 'media_type': 'image'})
                version = meta.version
            else:
                if head['content_hash'] != readback.content_hash:
                    raise ValueError('EXISTING_ARTIFACT_CONFLICT')
                version = int(head['version'])
            approval = open_artifact_approval(_principal(job), tenant_id=job['tenant_id'], project_id=job['project_id'],
                mission_id=job['job_id'], contract_hash=job['spec_hash'], artifact_id=aid, version=version,
                content_hash=readback.content_hash, run_pipeline=KIND, policy_version='amc-render-release/v1',
                subject_type='RENDER_ARTIFACT', reason='Rendered output requires independent human review before release')
            result = {'compute_status': 'succeeded', 'candidate': {k: observation[k] for k in ('storage_uri', 'content_hash', 'route')},
                      'artifact_id': aid, 'version': version, 'content_hash': readback.content_hash,
                      'verification': readback.model_dump(mode='json'), 'approval': approval}
            db.execute(f"UPDATE {table('durable_jobs')} SET result = ? WHERE job_id = ? AND lease_token = ?", (json_param(result), job['job_id'], job['lease_token']))
            update_run_status(job['job_id'], 'needs_approval')
            _event(job, 'RENDER_VERIFIED', {'artifact_id': aid, 'artifact_version': version, 'content_hash': readback.content_hash})
            return RunState.WAITING_APPROVAL, result


def quarantined(job) -> bool:
    from services.langgraph.persistence.project_knowledge import list_memory
    from services.langgraph.agency.project_os.memory import resolve
    key = 'render.quarantine.' + job['spec']['render']['request']['engine']
    records = [r for r in list_memory(tenant_id=job['tenant_id'], project_id=job['project_id']) if r.subject_key == key]
    winner = resolve(records, now=_now())['winner']
    return bool(winner and winner.body.get('quarantined'))


def quarantine(principal, project, engine, enabled, reason):
    from services.langgraph.api.routes._project_common import require_approver
    from services.langgraph.persistence.project_knowledge import write_memory
    _scope(principal, project)
    require_approver(principal, 'Render quarantine')
    with atomic_transaction() as db:
        identity = {'tenant_id': principal.tenant_id, 'project_id': project,
                    'spec': {'render': {'request': {'engine': engine.value}}}}
        _policy_lock(db, identity)
        result = write_memory(tenant_id=principal.tenant_id, project_id=project, actor=principal.user_id,
            scope='M2_PROJECT', authority='APPROVED_PROJECT_DECISION', subject_key='render.quarantine.' + engine.value,
            body={'quarantined': enabled, 'reason': reason}, source_refs=('operator:render-quarantine',))
        if enabled:
            rows = db.execute(f"SELECT job_id FROM {table('durable_jobs')} WHERE tenant_id = ? AND project_id = ? AND kind = ? AND state != ? ORDER BY job_id LIMIT 200",
                              (principal.tenant_id, project, KIND, RunState.STOPPED.value)).fetchall()
            for row in rows:
                job = store.get_job(row['job_id'])
                if job['spec']['render']['request']['engine'] == engine.value:
                    cancel(principal, project, row['job_id'])
    return {'engine': engine.value, 'quarantined': enabled, 'memory_id': result['memory'].memory_id}


def _policy_lock(db, job):
    if is_postgres():
        key = 'amc-render-policy|' + job['tenant_id'] + '|' + job['project_id'] + '|' + job['spec']['render']['request']['engine']
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(?, 0))', (key,))


def resume(principal, project, job_id):
    _command_authority(principal)
    current = inspect(principal, project, job_id)
    with atomic_transaction() as db:
        _policy_lock(db, store.get_job(job_id))
        _locked(db, job_id)
        job = store.get_job(job_id)
        current = inspect(principal, project, job_id)
        if job['state'] != RunState.WAITING_APPROVAL.value:
            return current
        if current['approval_status'] == 'rejected':
            target, status = RunState.STOPPED, 'rejected'
        elif current['release']['allowed']:
            target, status = RunState.DORMANT, 'completed'
        else:
            raise ValueError('A current authoritative review decision is required')
        store.transition(job, target, fencing_token=job['lease_token'], now=_now(), reason='authoritative render review applied')
        update_run_status(job_id, status)
        _event(job, 'RENDER_REVIEW_APPLIED', {'release_eligible': current['release']['allowed'], 'external_effects': 'none'})
    return inspect(principal, project, job_id)


def _command_authority(principal):
    if principal.role.strip().lower() not in {'admin', 'operator', 'owner', 'approver'}:
        raise PermissionError('Render commands require an operator role')
