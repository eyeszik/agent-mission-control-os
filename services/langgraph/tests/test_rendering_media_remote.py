"""Fictional projects and non-commercial license evaluation; real byte verifiers."""
import base64,hashlib,io
from datetime import timedelta
import pytest
from fastapi import HTTPException
from services.langgraph.tests.test_rendering import scope,request
from services.langgraph.agency.rendering import media,runtime,service,remote,licenses
from services.langgraph.agency.rendering.contracts import RenderEngineId
from services.langgraph.persistence import durable_runs as store
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user,client,headers

CANDIDATE=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540"><rect width="960" height="540" fill="#ffffff"/><path d="M20 20L120 20L120 100L20 100Z" fill="#ece6da" stroke="#121212" stroke-width="1"/></svg>'

def output(data=CANDIDATE):return hashlib.sha256(data).hexdigest(),base64.b64encode(data).decode()

def needs_media():
    if not media.fingerprint():pytest.skip('MEDIA_RUNTIME_UNAVAILABLE: build renderer and install Chromium/FFmpeg')
    from services.langgraph.agency.execution_fabric.adapters.code_sandbox import network_namespace_available
    if not network_namespace_available():pytest.skip('NETWORK_ISOLATION_UNAVAILABLE')

def evaluation_license(principal,project):
    # Explicitly fictional project, actual pinned license, non-commercial engine evaluation.
    licenses.record(principal,project,True,'Non-commercial adapter evaluation under the pinned Free License',('package:remotion@4.0.539/LICENSE.md#free-license',))

@pytest.mark.parametrize('engine',list(media.ENGINES))
@pytest.mark.parametrize('format',['png','mp4','webm'])
def test_real_five_engine_media_profiles_read_back(scope,engine,format):
    needs_media()
    principal,project,_=scope
    if engine is RenderEngineId.REMOTION:evaluation_license(principal,project)
    req=request(engine=engine,output_format=format,dimensions={'width':64,'height':64},clock={'fps_numerator':24,'total_frames':1 if format=='png' else 3},**({} if format=='png' else {'motion':{'x':12,'y':0}}))
    spec=runtime.compile_spec(principal.tenant_id,project,req)
    assert not runtime.blockers(spec)
    data=runtime.render(spec)
    report=runtime.verify(data,spec)
    assert report.status=='PASSED',report
    assert report.content_hash==hashlib.sha256(data).hexdigest()
    if format!='png':assert 'FULL_FRAME_DECODE' in report.checks
    wrong=spec.model_copy(update={'request':req.model_copy(update={'dimensions':req.dimensions.model_copy(update={'width':66})})})
    assert runtime.verify(data,wrong).status=='FAILED'
    assert runtime.verify(b'fictional corrupt media',spec).status=='FAILED'

@pytest.mark.parametrize('engine',list(media.ENGINES))
def test_frame_clock_changes_real_pixels(scope,engine):
    needs_media()
    principal,project,_=scope
    req=request(engine=engine,output_format='mp4',dimensions={'width':64,'height':64},clock={'total_frames':3},motion={'x':12,'y':0})
    # Extract actual decoded first/last frames from encoded output, not producer claims.
    data=media.render(req)
    import tempfile,subprocess
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'video.mp4';path.write_bytes(data)
        proc=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=15)
        assert proc.returncode==0
        size=64*64*3
        assert len(proc.stdout)==size*3
        assert proc.stdout[:size]!=proc.stdout[-size:]


def test_license_missing_and_revoked_never_dispatch(scope):
    needs_media()
    principal,project,_=scope
    spec=runtime.compile_spec(principal.tenant_id,project,request(engine='remotion',output_format='png'))
    assert 'LICENSE_APPROVAL_REQUIRED' in runtime.blockers(spec)
    evaluation_license(principal,project)
    permitted=runtime.compile_spec(principal.tenant_id,project,spec.request)
    assert permitted.license_decision_hash
    assert permitted.spec_hash!=spec.spec_hash
    licenses.record(principal,project,False,'Fictional evaluation permission withdrawn',('fixture:permission-withdrawal',))
    assert 'LICENSE_APPROVAL_REQUIRED' in runtime.blockers(permitted)


def test_legacy_identity_omits_new_optional_fields(scope):
    from services.langgraph.agency.execution.canonical import canonical_hash
    principal,project,_=scope
    spec=runtime.compile_spec(principal.tenant_id,project,request())
    legacy=spec.model_dump(mode='json');legacy.pop('media_runtime_hash');legacy.pop('license_decision_hash');legacy['request'].pop('motion')
    assert spec.spec_hash==canonical_hash(legacy)

@pytest.fixture
def remote_job(scope,monkeypatch):
    principal,project,root=scope
    # Fictional producer output permits protocol tests without a browser/provider.
    monkeypatch.setattr(service,'blockers',lambda spec:[])
    job=service.submit(principal,project,request(),root)
    return principal,project,job['job_id']


def test_remote_completion_is_fenced_verified_and_idempotent(remote_job):
    principal,project,job_id=remote_job
    envelope=remote.claim(principal,project,job_id)['job']
    assert 'export_root' not in envelope['spec']
    assert 'requested_by' not in envelope['spec']
    digest,encoded=output()
    result=remote.complete(principal,project,job_id,envelope['fencing_token'],digest,encoded)
    assert result['job_status']=='succeeded'
    assert result['artifact_status']=='verified'
    assert result['approval_status']=='pending' and not result['release']['allowed']
    replay=remote.complete(principal,project,job_id,envelope['fencing_token'],digest,encoded)
    assert replay['artifact_id']==result['artifact_id']
    with pytest.raises(HTTPException) as error:
        d,e=output(CANDIDATE.replace(b'20 20',b'21 20'))
        remote.complete(principal,project,job_id,envelope['fencing_token'],d,e)
    assert error.value.status_code==409


def test_remote_wrong_worker_hash_scope_and_cancel_refused(remote_job):
    principal,project,job_id=remote_job
    envelope=remote.claim(principal,project,job_id)['job'];token=envelope['fencing_token']
    other=Principal(user_id='fixture-other-worker',tenant_id=principal.tenant_id,role='operator',allowed_project_ids=frozenset({project}))
    digest,encoded=output()
    with pytest.raises(HTTPException):remote.complete(other,project,job_id,token,digest,encoded)
    with pytest.raises(HTTPException):remote.complete(principal,project,job_id,token,'0'*64,encoded)
    assert service.inspect(principal,project,job_id)['artifact_id'] is None
    service.cancel(principal,project,job_id)
    with pytest.raises(HTTPException):remote.complete(principal,project,job_id,token,digest,encoded)
    assert service.inspect(principal,project,job_id)['artifact_id'] is None


def test_remote_bad_output_rejects_artifact_preserves_compute(remote_job):
    principal,project,job_id=remote_job
    token=remote.claim(principal,project,job_id)['job']['fencing_token']
    digest,encoded=output(b'fictional malformed SVG')
    result=remote.complete(principal,project,job_id,token,digest,encoded)
    assert result['job_status']=='succeeded' and result['artifact_status']=='rejected'
    assert not result['artifact_id'] and not result['release']['allowed']


def test_remote_expiry_takeover_blocks_old_worker(remote_job):
    from services.langgraph.persistence.database import atomic_transaction,table
    principal,project,job_id=remote_job
    old=remote.claim(principal,project,job_id)['job']['fencing_token']
    with atomic_transaction() as db:
        db.execute(f"UPDATE {table('durable_jobs')} SET lease_expires_at=? WHERE job_id=?",(store.iso(service._now()-timedelta(seconds=1)),job_id))
    with pytest.raises(HTTPException):remote.heartbeat(principal,project,job_id,old)
    new=remote.claim(principal,project,job_id)['job']['fencing_token']
    assert new>old
    digest,encoded=output()
    with pytest.raises(HTTPException):remote.complete(principal,project,job_id,old,digest,encoded)
    assert remote.complete(principal,project,job_id,new,digest,encoded)['artifact_status']=='verified'


def test_authenticated_worker_routes_use_server_identity(remote_job,monkeypatch):
    principal,project,job_id=remote_job
    as_user(monkeypatch,principal.user_id,tenant=principal.tenant_id,projects=project)
    endpoint=f'/foundry/projects/{project}/renders/{job_id}'
    response=client.post(endpoint+'/claim',json={})
    assert response.status_code==200,response.text
    token=response.json()['job']['fencing_token']
    assert client.post(endpoint+'/heartbeat',json={'fencing_token':token}).status_code==200
    digest,encoded=output()
    response=client.post(endpoint+'/complete',json={'fencing_token':token,'content_hash':digest,'data_base64':encoded})
    assert response.status_code==200,response.text
    as_user(monkeypatch,'fixture-outsider',tenant='fixture-other-tenant',projects='*')
    assert client.post(endpoint+'/complete',json={'fencing_token':token,'content_hash':digest,'data_base64':encoded}).status_code in (403,404)


def test_transport_refuses_insecure_and_credentialed_urls(tmp_path):
    from services.langgraph.agency.rendering.remote_worker import execute
    for url in ('http://example.com','https://user:password@example.com','https://example.com/?token=secret'):
        with pytest.raises(ValueError):execute(url,'fixture','fixture','fixture-token',tmp_path)


def test_worker_does_not_follow_redirect_with_authorization():
    from services.langgraph.agency.rendering.remote_worker import NoRedirect
    with pytest.raises(ValueError):
        NoRedirect().redirect_request(None,None,302,'redirect',{},'https://another.example')


def test_declared_resource_bounds_and_output_pairs():
    req=request(engine='p5_js',output_format='mp4',clock={'total_frames':121})
    assert 'MEDIA_RESOURCE_BUDGET_EXCEEDED' in media.profile_blockers(req)
    assert 'UNSUPPORTED_ENGINE_OUTPUT_PAIR' in media.profile_blockers(request(engine='p5_js',output_format='svg'))
    assert 'VIDEO_REQUIRES_EVEN_DIMENSIONS' in media.profile_blockers(request(engine='p5_js',output_format='mp4',dimensions={'width':65,'height':64}))


@pytest.mark.parametrize('engine',list(media.ENGINES))
@pytest.mark.parametrize('kind',['ellipse','line'])
def test_each_browser_adapter_supports_all_declared_primitives(scope,engine,kind):
    needs_media()
    principal,project,_=scope
    req=request(engine=engine,output_format='png',dimensions={'width':64,'height':64},scene={'primitives':[{'kind':kind,'x':20,'y':20,'width':30,'height':20,'stroke_width':3}]})
    spec=runtime.compile_spec(principal.tenant_id,project,req)
    assert runtime.verify(media.render(req),spec).status=='PASSED'


def test_remote_client_renders_over_real_loopback_http(remote_job,tmp_path,monkeypatch):
    needs_media()
    import socket,threading,time,uvicorn
    from services.langgraph.agency.rendering.remote_worker import execute
    principal,project,job_id=remote_job
    as_user(monkeypatch,principal.user_id,tenant=principal.tenant_id,projects=project)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(client.app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        for _ in range(50):
            if server.started:break
            time.sleep(0.02)
        assert server.started
        result=execute(f'http://127.0.0.1:{port}',project,job_id,'fixture-local-auth-token',tmp_path)
        assert result['artifact_status']=='verified' and not result['release']['allowed']
        replay=execute(f'http://127.0.0.1:{port}',project,job_id,'fixture-local-auth-token',tmp_path,completion=tmp_path/'completion.json')
        assert replay['artifact_id']==result['artifact_id']
        assert (tmp_path/'candidate.bin').is_file()
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()


def test_license_revoked_after_render_cannot_register_artifact(scope):
    needs_media()
    from services.langgraph.agency.durable.ticks import run_tick
    from services.langgraph.persistence.projects import list_project_artifacts
    principal,project,root=scope
    evaluation_license(principal,project)
    job=service.submit(principal,project,request(engine='remotion',output_format='png',dimensions={'width':64,'height':64}),root)
    def revoke(point):
        if point=='before_commit':licenses.record(principal,project,False,'Fictional evaluation entitlement revoked before acceptance',('fixture:revoke-before-acceptance',))
    with pytest.raises(PermissionError,match='LICENSE_DECISION_STALE'):
        run_tick(worker_id='fixture-controller',handlers={service.KIND:service.RenderHandler()},job_id=job['job_id'],hook=revoke)
    assert not list_project_artifacts(project)


@pytest.mark.parametrize('refs',[('',),('fixture:same','fixture:same')])
def test_license_decisions_refuse_blank_or_duplicate_evidence(scope,refs):
    principal,project,_=scope
    with pytest.raises(ValueError):licenses.record(principal,project,True,'Fictional non-commercial evaluation',refs)


@pytest.mark.parametrize('format',['png','mp4','webm'])
def test_media_registration_and_authenticated_download_preserve_mime(scope,monkeypatch,format):
    needs_media()
    from services.langgraph.agency.durable.ticks import run_tick
    principal,project,root=scope
    monkeypatch.setenv('AMC_EXPORT_ROOT',str(root))
    req=request(engine='p5_js',output_format=format,dimensions={'width':64,'height':64},clock={'total_frames':1 if format=='png' else 3})
    job=service.submit(principal,project,req,root)
    report=run_tick(worker_id='fixture-controller',handlers={service.KIND:service.RenderHandler()},job_id=job['job_id'])
    assert report.final_state=='WAITING_APPROVAL',report.reasons
    result=service.inspect(principal,project,job['job_id'])
    assert result['artifact_status']=='verified' and not result['release']['allowed']
    as_user(monkeypatch,principal.user_id,tenant=principal.tenant_id,projects=project)
    response=client.get(f"/foundry/projects/{project}/artifacts/{result['artifact_id']}/content")
    assert response.status_code==200,response.text
    assert response.headers['content-type'].startswith(media.MIMES[format])
    assert hashlib.sha256(response.content).hexdigest()==result['content_hash']


def test_old_api_retry_identity_does_not_gain_an_omitted_motion_field(scope,monkeypatch):
    from services.langgraph.persistence.idempotency import reserve_idempotency,complete_idempotency,hash_payload
    principal,project,_=scope
    as_user(monkeypatch,principal.user_id,tenant=principal.tenant_id,projects=project)
    legacy=request().model_dump(mode='json');legacy.pop('motion')
    key='fixture-pre-motion-idempotency';scope_key=f'{principal.tenant_id}:{principal.user_id}:render:{project}'
    assert reserve_idempotency(scope_key,key,hash_payload(legacy))['state']=='new'
    receipt={'fixture':'previously committed receipt'}
    complete_idempotency(scope_key,key,receipt)
    response=client.post(f'/foundry/projects/{project}/renders',json=legacy,headers={'Idempotency-Key':key})
    assert response.status_code==202,response.text
    assert response.json()==receipt


def test_playlist_disguised_as_video_is_rejected_before_any_probe(scope,monkeypatch):
    principal,project,_=scope
    spec=runtime.compile_spec(principal.tenant_id,project,request(engine='p5_js',output_format='mp4',dimensions={'width':64,'height':64}))
    def no_probe(*args,**kwargs):raise AssertionError('Unrecognized input must not enter a media subprocess')
    monkeypatch.setattr(media.subprocess,'run',no_probe)
    report=media.verify(b'#EXTM3U\nhttps://example.invalid/stream.ts',spec)
    assert report.status=='FAILED' and 'CONTAINER_MAGIC_MISMATCH' in report.findings



def test_two_remote_claims_have_one_winner(remote_job):
    from concurrent.futures import ThreadPoolExecutor
    principal,project,job_id=remote_job
    def attempt():
        try:return remote.claim(principal,project,job_id)['job']['fencing_token']
        except HTTPException as error:
            assert error.status_code==409
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sum(result is not None for result in results)==1


def test_container_profile_distinguishes_webm_from_generic_matroska():
    # Minimal fictional EBML headers test identification only, never video verification.
    assert media.container_matches(b'\x1aE\xdf\xa3\x87\x42\x82\x84webm','webm')
    assert not media.container_matches(b'\x1aE\xdf\xa3\x8b\x42\x82\x88matroska','webm')
    assert not media.container_matches(b'\x1aE\xdf\xa3\xff','webm')
    assert not media.container_matches(b'\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  ','mp4')
