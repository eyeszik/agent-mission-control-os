"""Authenticated pull-worker protocol; workers receive no DB or storage credentials.

The canonical durable job is the queue. Candidates are uploaded as bounded bytes,
never worker-chosen paths/URIs. Every acceptance uses the current scoped lease.
"""
from __future__ import annotations
import base64
import hashlib
from fastapi import HTTPException
from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.durable.ticks import idempotency_key
from services.langgraph.persistence import durable_runs as store
from services.langgraph.persistence.database import atomic_transaction
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from . import service
from .media import MAX_OUTPUT

LEASE_SECONDS=300

def _worker(principal):return 'render-remote:'+principal.user_id

def _key(job,handler):
    return idempotency_key(tenant=job['tenant_id'],project=job['project_id'],job=job['job_id'],logical_tick=job['logical_tick']+1,operation=handler.operation,target=handler.target(job),input_hash=handler.input_hash(job),contract_version=handler.contract_version)

def _active(principal,job,token):
    if job['lease_owner']!=_worker(principal) or job['lease_token']!=token:raise HTTPException(409,'WORKER_LEASE_MISMATCH')
    return job

def claim(principal,project,job_id):
    service._command_authority(principal);service.inspect(principal,project,job_id)
    handler=service.RenderHandler()
    with atomic_transaction() as db:
        service._policy_lock(db,store.get_job(job_id));service._locked(db,job_id)
        claimed=store.claim_due_job(worker_id=_worker(principal),now=service._now(),lease_seconds=LEASE_SECONDS,job_id=job_id)
        if not claimed:raise HTTPException(409,'JOB_NOT_CLAIMABLE')
        job,entered=claimed;token=job['lease_token']
        if entered is RunState.LEASED:job=store.transition(job,RunState.PRECHECK,fencing_token=token,now=service._now())
        blocked,reasons=handler.precheck(job)
        if blocked:raise HTTPException(409,{'code':'RENDER_NOT_ADMISSIBLE','reasons':reasons})
        key=_key(job,handler)
        if entered is RunState.LEASED:job=store.transition(job,RunState.READY,fencing_token=token,now=service._now())
        intent=store.get_intent(key)
        if not intent:
            if job['state']=='RECONCILING':job=store.transition(job,RunState.READY,fencing_token=token,now=service._now())
            store.reserve_intent(key=key,job=job,logical_tick=job['logical_tick']+1,operation=handler.operation,target=handler.target(job),input_hash=handler.input_hash(job),contract_version=handler.contract_version,retry_class=handler.retry_class,pre_image=handler.pre_image(job),fencing_token=token,now=service._now())
        elif intent['status'] in {'FAILED','ABANDONED'}:raise HTTPException(409,'INTENT_TERMINAL')
        if (job.get('result') or {}).get('candidate'):
            job=store.transition(job,RunState.OBSERVING,fencing_token=token,now=service._now())
            service._candidate(job,remote_worker=principal.user_id,remote_fence=token)
            observation=handler.observe(job,job['result']['candidate'])
            _finalize(job,handler,observation,key)
            return {'recovered':service.inspect(principal,project,job_id),'job':None}
        if job['state']=='RECONCILING':job=store.transition(job,RunState.READY,fencing_token=token,now=service._now())
        job=store.transition(job,RunState.RUNNING,fencing_token=token,now=service._now())
        service._candidate(job,compute_status='running',remote_worker=principal.user_id,remote_fence=token)
        return {'job':{'job_id':job_id,'fencing_token':token,'lease_expires_at':job['lease_expires_at'],'spec_hash':job['spec_hash'],'spec':job['spec']['render']},'recovered':None}

def heartbeat(principal,project,job_id,token):
    service._command_authority(principal);service.inspect(principal,project,job_id)
    _active(principal,store.get_job(job_id),token)
    try:job=store.renew_lease(job_id=job_id,worker_id=_worker(principal),fencing_token=token,now=service._now(),lease_seconds=LEASE_SECONDS)
    except store.StaleFence:raise HTTPException(409,'WORKER_LEASE_EXPIRED') from None
    return {'lease_expires_at':job['lease_expires_at'],'fencing_token':token}

def _finalize(job,handler,observation,key):
    token=job['lease_token'];job=store.transition(job,RunState.VERIFYING,fencing_token=token,now=service._now())
    verification=handler.verify(job,observation)
    if verification['status']!='PASSED':
        target=RunState.INCONCLUSIVE if verification['status']=='INCONCLUSIVE' else RunState.DEAD_LETTER
        store.transition(job,target,fencing_token=token,now=service._now(),lease_owner=None,lease_expires_at=None,last_reasons=['REMOTE_OUTPUT_'+verification['status']])
        return
    job=store.transition(job,RunState.COMMITTING,fencing_token=token,now=service._now())
    intent=store.get_intent(key)
    if intent['status'] in {'INTENT','UNCONFIRMED'}:
        store.commit_intent(key=key,job_id=job['job_id'],fencing_token=token,now=service._now(),receipt={'observation':observation,'verification':verification})
    target,result=handler.on_commit(job,observation,verification)
    store.transition(job,target,fencing_token=token,now=service._now(),lease_owner=None,lease_expires_at=None,logical_tick=job['logical_tick']+1,result=result,last_reasons=[])

def complete(principal,project,job_id,token,content_hash,data_base64):
    service._command_authority(principal);service.inspect(principal,project,job_id)
    try:data=base64.b64decode(data_base64,validate=True)
    except ValueError:raise HTTPException(422,'INVALID_BASE64') from None
    if not data or len(data)>MAX_OUTPUT:raise HTTPException(413,'OUTPUT_SIZE_LIMIT')
    observed=hashlib.sha256(data).hexdigest()
    if observed!=content_hash:raise HTTPException(409,'CONTENT_HASH_MISMATCH')
    handler=service.RenderHandler()
    with atomic_transaction() as db:
        service._policy_lock(db,store.get_job(job_id));service._locked(db,job_id)
        job=store.get_job(job_id);result=job.get('result') or {}
        if job['state'] in {'WAITING_APPROVAL','DORMANT','DEAD_LETTER','INCONCLUSIVE'}:
            if result.get('remote_worker')==principal.user_id and result.get('remote_fence')==token and result.get('candidate',{}).get('content_hash')==observed:
                return service.inspect(principal,project,job_id)
            raise HTTPException(409,'COMPLETION_CONFLICT')
        _active(principal,job,token)
        try:store._active_fence(db,job_id=job_id,fencing_token=token,now=service._now())
        except store.StaleFence:raise HTTPException(409,'WORKER_LEASE_EXPIRED') from None
        blocked,reasons=handler.precheck(job)
        if blocked:raise HTTPException(409,{'code':'RENDER_NOT_ADMISSIBLE','reasons':reasons})
        if job['state']!='RUNNING':raise HTTPException(409,'JOB_NOT_RUNNING')
        obj=LocalStorageAdapter(job['spec']['export_root']).put_bytes(tenant_id=job['tenant_id'],project_id=project,data=data)
        candidate={'storage_uri':obj.storage_uri,'content_hash':observed,'route':job['spec']['render']['request']['engine']}
        service._candidate(job,compute_status='succeeded',candidate=candidate)
        job=store.transition(job,RunState.OBSERVING,fencing_token=token,now=service._now())
        observation=handler.observe(job,candidate)
        _finalize(job,handler,observation,_key(job,handler))
    return service.inspect(principal,project,job_id)
