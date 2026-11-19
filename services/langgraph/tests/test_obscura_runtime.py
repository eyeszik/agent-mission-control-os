import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from services.langgraph.agency import obscura_runtime as runtime


@pytest.fixture(autouse=True)
def isolate_environment():
    with patch.dict(os.environ):
        yield


def profile(**extra):
    return runtime.RuntimeProfile(binary_dir='/fixture/binaries',runtime_image='sha256:'+'a'*64,**extra)


def test_profile_is_private_and_preserves_identity(tmp_path,monkeypatch):
    path=tmp_path/'runtime.json'
    runtime.save_profile(path,profile(public_enabled=True))
    assert path.stat().st_mode & 0o777 == 0o600
    assert runtime.load_profile(path)==profile(public_enabled=True)
    monkeypatch.setenv('AMC_LOCAL_USER_ID','fixture-original-actor')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','0')
    runtime.apply_profile(path)
    assert os.environ['AMC_LOCAL_USER_ID']=='fixture-original-actor'
    assert os.environ['AMC_OBSCURA_ENABLED']=='0'
    with pytest.raises(ValueError,match='PROFILE_EXISTS'):
        runtime.save_profile(path,profile())


def test_profile_cannot_carry_authority_or_proxy_credentials():
    with pytest.raises(ValidationError): profile(tenant_id='forged')
    with pytest.raises(ValidationError): profile(https_proxy='http://actor:secret@proxy:80')


def test_load_refuses_symlink_and_oversized(tmp_path):
    target=tmp_path/'data';target.write_text('x'*8193)
    link=tmp_path/'link';link.symlink_to(target)
    with pytest.raises(ValueError,match='SYMLINK'):runtime.load_profile(link)
    with pytest.raises(ValueError,match='SIZE_LIMIT'):runtime.load_profile(target)


def test_disabled_does_not_probe(monkeypatch):
    monkeypatch.delenv('AMC_OBSCURA_ENABLED',raising=False)
    with patch.object(runtime.subprocess,'run',side_effect=AssertionError('must not probe')):
        assert runtime.runtime_status()['reasons']==['OBSCURA_DISABLED']


def test_readiness_detects_binary_tampering(tmp_path,monkeypatch):
    import hashlib
    from services.langgraph.agency import obscura_worker
    binaries={'obscura':b'fictional fixture','obscura-worker':b'fictional worker'}
    for name,data in binaries.items():(tmp_path/name).write_bytes(data)
    monkeypatch.setattr(obscura_worker,'DIGESTS',{k:hashlib.sha256(v).hexdigest() for k,v in binaries.items()})
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',str(tmp_path))
    monkeypatch.setenv('AMC_OBSCURA_RUNTIME_IMAGE','sha256:'+'a'*64)
    monkeypatch.setattr(runtime.shutil,'which',lambda name:'/fixture/'+name)
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout='sha256:'+'a'*64) if a[0][1]=='image' else SimpleNamespace(returncode=0,stdout=json.dumps({**dict.fromkeys(('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod'),True),'CgroupDriver':'systemd'})))
    assert runtime.runtime_status(refresh=True)['ready']
    (tmp_path/'obscura').write_bytes(b'changed')
    assert runtime.runtime_status()['reasons']==['BINARY_INTEGRITY']


def test_runtime_refuses_missing_image(tmp_path,monkeypatch):
    import hashlib
    from services.langgraph.agency import obscura_worker
    for name in ('obscura','obscura-worker'):(tmp_path/name).write_bytes(b'fixture')
    monkeypatch.setattr(obscura_worker,'DIGESTS',{name:hashlib.sha256(b'fixture').hexdigest() for name in ('obscura','obscura-worker')})
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1');monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',str(tmp_path));monkeypatch.setenv('AMC_OBSCURA_RUNTIME_IMAGE','sha256:'+'b'*64)
    monkeypatch.setattr(runtime.shutil,'which',lambda name:'/fixture/'+name)
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout='') if a[0][1]=='image' else SimpleNamespace(returncode=0,stdout=json.dumps({**dict.fromkeys(('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod'),True),'CgroupDriver':'systemd'})))
    assert runtime.runtime_status(refresh=True)['reasons']==['RUNTIME_IMAGE_UNAVAILABLE']


def test_cli_does_not_echo_invalid_values(tmp_path,monkeypatch,capsys):
    path=tmp_path/'invalid.json';path.write_text(json.dumps({'secret_field':'DO_NOT_ECHO_ME'}))
    monkeypatch.setattr('sys.argv',['runtime','doctor','--profile',str(path)])
    assert runtime.main()==1
    assert 'DO_NOT_ECHO_ME' not in capsys.readouterr().err


@pytest.mark.parametrize('unsupported', ['MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod'])
def test_unsupported_controller_is_not_ready(monkeypatch, unsupported):
    capabilities = {**dict.fromkeys(('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod'), True),'CgroupDriver':'systemd'}
    capabilities[unsupported] = False
    monkeypatch.setattr(runtime.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=json.dumps(capabilities)))
    assert runtime.resource_limits_status() == {'supported':False,'reason':'RESOURCE_LIMITS_UNAVAILABLE'}


def test_worker_refuses_unbounded_runtime_before_launch(monkeypatch):
    from services.langgraph.agency.obscura_worker import extract
    monkeypatch.setattr(runtime,'resource_limits_status',lambda:{'supported':False,'reason':'RESOURCE_LIMITS_UNAVAILABLE'})
    with patch('subprocess.Popen',side_effect=AssertionError('unbounded process must not launch')):
        with pytest.raises(RuntimeError,match='RESOURCE_LIMITS_UNAVAILABLE'):
            extract('<p>fixture</p>',Path('/absent'))


def test_blocked_optional_worker_does_not_disable_independent_api(tmp_path,monkeypatch):
    path=tmp_path/'profile.json';runtime.save_profile(path,profile())
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setattr(runtime,'runtime_status',lambda **kw:{'ready':False,'reasons':['RESOURCE_LIMITS_UNAVAILABLE']})
    monkeypatch.setattr('sys.argv',['runtime','launch','--profile',str(path),'--','-m','uvicorn','services.langgraph.app.main:app','--host','127.0.0.1'])
    observed=[]
    def exec_fixture(executable,args):
        observed.extend(args[1:]);raise SystemExit(0)
    monkeypatch.setattr(runtime.os,'execv',exec_fixture)
    with pytest.raises(SystemExit) as result:runtime.main()
    assert result.value.code==0
    assert observed[:3]==['-m','uvicorn','services.langgraph.app.main:app']
    assert os.environ['AMC_OBSCURA_ENABLED']=='1'  # availability remains an independent gate


def test_unavailable_metadata_probe_is_cached_without_relaunch(tmp_path,monkeypatch):
    for name in ('obscura','obscura-worker'):(tmp_path/name).write_bytes(b'fixture')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1');monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',str(tmp_path));monkeypatch.setenv('AMC_OBSCURA_RUNTIME_IMAGE','sha256:'+'d'*64)
    monkeypatch.setattr(runtime.shutil,'which',lambda name:'/fixture/'+name)
    calls=[]
    def unavailable():calls.append(1);return {'supported':False,'reason':'RESOURCE_LIMITS_UNAVAILABLE'}
    monkeypatch.setattr(runtime,'resource_limits_status',unavailable)
    assert not runtime.runtime_status(refresh=True)['ready']
    assert not runtime.runtime_status()['ready']
    assert len(calls)==1
