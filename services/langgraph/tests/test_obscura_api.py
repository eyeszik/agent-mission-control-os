import os
import pytest
from services.langgraph.tests._project_os_support import as_user, client, export_root, new_project


def test_disabled_and_tenant_boundary(monkeypatch, export_root):
    as_user(monkeypatch,'fixture-owner')
    project=new_project('Browser fixture')['project_id']
    path=f'/browser/projects/{project}'
    monkeypatch.delenv('AMC_OBSCURA_ENABLED',raising=False)
    assert client.get(path+'/capabilities').json()['enabled'] is False
    body={'html':'<h1>Fixture</h1>','source_ref':'fixture:test'}
    assert client.post(path+'/extractions',json=body).status_code == 503
    monkeypatch.setenv('AMC_AUTH_MODE','supabase')
    assert client.get(path+'/capabilities').status_code == 401
    assert client.post(path+'/extractions',json=body).status_code == 401
    monkeypatch.setenv('AMC_AUTH_MODE','local')
    as_user(monkeypatch,'other',tenant='other-tenant')
    assert client.get(path+'/capabilities').status_code in {403,404}
    assert client.post(path+'/extractions',json=body).status_code in {403,404}


def test_real_api_extraction_and_replay(monkeypatch, export_root):
    if not os.environ.get('TEST_OBSCURA_BIN') or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit verified local runtime required')
    as_user(monkeypatch,'fixture-owner')
    monkeypatch.setenv('AMC_ENV','local')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',os.environ['TEST_OBSCURA_BIN'])
    project=new_project('Browser execution fixture')['project_id']
    url=f'/browser/projects/{project}/extractions'
    body={'html':'<h1>Fictional extraction fixture</h1>','source_ref':'fixture:test'}
    response=client.post(url,json=body)
    assert response.status_code == 200,response.text
    result=response.json()
    assert result['status']=='SUCCEEDED',result
    assert 'Fictional extraction fixture' in result['content']['markdown']
    assert result['proof']['execution_count']==1
    replay=client.post(url,json=body).json()
    assert replay['replayed'] and replay['proof']['execution_count']==1
    assert client.post(url,json={**body,'tenant_id':'forged'}).status_code==422
    as_user(monkeypatch,'viewer',role='viewer')
    assert client.post(url,json=body).status_code==403
    monkeypatch.setenv('AMC_ENV','production')
    assert client.get(f'/browser/projects/{project}/capabilities').json()['enabled'] is False


def test_public_input_and_policy(monkeypatch, export_root):
    as_user(monkeypatch,'fixture-owner')
    project=new_project('URL policy fixture')['project_id']
    path=f'/browser/projects/{project}/extractions'
    monkeypatch.setenv('AMC_ENV','local')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_RUNTIME_IMAGE','sha256:'+'a'*64)
    monkeypatch.delenv('AMC_OBSCURA_PUBLIC_ENABLED',raising=False)
    body={'url':'https://example.com','source_ref':'fixture:public-policy'}
    assert client.post(path,json=body).status_code==400
    assert client.post(path,json=body,headers={'Idempotency-Key':'fixture'}).status_code==503
    for invalid in [ {'url':'file:///etc/passwd','source_ref':'fixture'}, {'url':'http://example.com','source_ref':'fixture'}, {'url':'https://example.com','html':'both','source_ref':'fixture'}, {'source_ref':'fixture'} ]:
        assert client.post(path,json=invalid).status_code==422


def test_live_public_retrieval_and_receipt(monkeypatch, export_root):
    if os.environ.get('TEST_OBSCURA_LIVE')!='1':
        pytest.skip('explicit authorized live public retrieval required')
    as_user(monkeypatch,'fixture-public-owner')
    monkeypatch.setenv('AMC_ENV','local')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_PUBLIC_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',os.environ['TEST_OBSCURA_BIN'])
    proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if proxy: monkeypatch.setenv('AMC_OBSCURA_HTTPS_PROXY',proxy)
    project=new_project('Live public page fixture')['project_id']
    body={'url':'https://example.com','source_ref':'https://example.com'}
    path=f'/browser/projects/{project}/extractions'
    response=client.post(path,json=body,headers={'Idempotency-Key':'live-fixture-once'})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['status']=='SUCCEEDED',result
    assert 'documentation examples' in result['content']['source_html']
    assert 'documentation examples' in result['content']['markdown']
    assert result['content']['source_status']=='RETRIEVED'
    assert result['content']['retrieval']['final_url']=='https://example.com'
    assert result['content']['retrieval']['retrieved_at']
    assert result['proof']['matched_observation_count']==1
    replay=client.post(path,json=body,headers={'Idempotency-Key':'live-fixture-once'}).json()
    assert replay['replayed'] and replay['proof']['execution_count']==1
