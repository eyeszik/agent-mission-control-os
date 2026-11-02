"""Solo-owner exception tests use fictional actors and mock transport only."""
from uuid import uuid4
import pytest
from services.langgraph.tests._project_os_support import as_user, client, new_project
from services.langgraph.tests.test_innovation_generation_api import install_fixture_invocation
from services.langgraph.persistence import durable_runs


@pytest.fixture
def solo(tmp_path, monkeypatch):
    tenant='solo-test-'+uuid4().hex[:12]
    monkeypatch.setenv('AMC_ENV','local')
    monkeypatch.setenv('AMC_AUTH_MODE','local')
    monkeypatch.setenv('AMC_INNOVATION_SOLO_OWNER_APPROVAL','1')
    monkeypatch.setenv('AMC_ALLOW_SELF_APPROVAL','0')
    monkeypatch.setenv('OLLAMA_NO_CLOUD','1')
    monkeypatch.setenv('AMC_INNOVATION_SOLO_OWNER_MODEL','fixture-only-model')
    monkeypatch.setenv('AMC_EXPORT_ROOT',str(tmp_path))
    monkeypatch.setenv('AMC_OBJECT_STORAGE_BACKEND','local')
    monkeypatch.setenv('AMC_LLM_PROVIDER','ollama')
    monkeypatch.setenv('AMC_OLLAMA_MODEL','fixture-only-model')
    monkeypatch.delenv('AMC_LLM_DISABLED_PROVIDERS',raising=False)
    monkeypatch.delenv('AMC_LLM_FALLBACK_PROVIDERS',raising=False)
    as_user(monkeypatch,'fictional-owner',tenant=tenant,role='owner')
    project=new_project('Fictional solo owner policy test')['project_id']
    source=f'/innovation/projects/{project}/runs'
    created=client.post(source,json={'objective':'Fictional local policy validation for tool sharing','provider':'live'},headers={'Idempotency-Key':uuid4().hex}).json()
    source+='/'+created['run']['run_id']
    base=source+'/generation'
    response=client.post(base,json={'expected_version':1})
    assert response.status_code==200,response.text
    return tenant,source,base,response.json()


def decide(stage):
    return client.post('/approvals/'+stage['approval']['approval_id']+'/decide',json={'decision':'approve'},headers={'Idempotency-Key':uuid4().hex})


def test_manual_owner_approval_then_mock_execution_is_scoped_and_replay_safe(solo,monkeypatch):
    _,_,base,stage=solo
    assert stage['approval']['policy_version']=='unbound-local-owner/v1'
    assert stage['approval']['status']=='pending'
    calls=[];install_fixture_invocation(monkeypatch,calls)
    assert client.post(base+'/tick',json={'expected_version':1}).json()['status']=='BLOCKED'
    assert calls==[]
    response=decide(stage);assert response.status_code==200,response.text
    result=client.post(base+'/tick',json={'expected_version':1})
    assert result.status_code==200,result.text
    assert result.json()['status']=='PARTIAL' and len(calls)==1
    client.post(base+'/tick',json={'expected_version':1});assert len(calls)==1
    assert durable_runs.list_intents(stage['job_id'])[0]['status']=='COMMITTED'


@pytest.mark.parametrize('key,value',[('AMC_INNOVATION_SOLO_OWNER_APPROVAL','0'),('AMC_ENV','production'),('AMC_AUTH_MODE','supabase'),('AMC_LLM_PROVIDER','openai'),('OLLAMA_NO_CLOUD','0'),('AMC_INNOVATION_SOLO_OWNER_MODEL','different-model')])
def test_exception_fails_closed_when_policy_or_provider_changes(solo,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    # Call trusted authority directly when auth-mode changes would reject HTTP first.
    from services.langgraph.security.approval_authority import assert_may_decide_approval
    from services.langgraph.security.auth import Principal
    from services.langgraph.persistence.runs import get_run_record
    from fastapi import HTTPException
    stage=solo[3];approval=stage['approval'];run=get_run_record(approval['run_id'])
    principal=Principal(user_id='fictional-owner',tenant_id=solo[0],role='owner',allowed_project_ids=frozenset({'*'}))
    with pytest.raises(HTTPException) as exc:assert_may_decide_approval(principal,run,'approve',approval)
    assert exc.value.status_code==403


@pytest.mark.parametrize('role',['admin','operator'])
def test_non_owner_cannot_borrow_owner_policy(solo,monkeypatch,role):
    as_user(monkeypatch,'fictional-owner',tenant=solo[0],role=role)
    assert decide(solo[3]).status_code==403


def test_changed_source_cannot_be_approved(solo):
    assert client.post(solo[1]+'/control',json={'expected_version':1,'action':'pause'}).status_code==200
    assert decide(solo[3]).status_code==403


def test_wrong_purpose_and_stale_plan_are_not_exceptions(solo):
    from services.langgraph.security.local_generation_approval import permits_owner
    from services.langgraph.persistence.runs import get_run_record
    from services.langgraph.security.auth import Principal
    stage=solo[3];approval=stage['approval'];run=get_run_record(approval['run_id'])
    principal=Principal(user_id='fictional-owner',tenant_id=solo[0],role='owner',allowed_project_ids=frozenset({'*'}))
    assert permits_owner(principal,run,approval)
    for altered in ({**approval,'subject_type':'CREATIVE_ARTIFACT'},{**approval,'subject_version_ref':'999'},{**approval,'subject_hash':'0'*64},{**approval,'tenant_id':'foreign'}):
        assert not permits_owner(principal,run,altered)


def test_enabling_new_policy_does_not_rewrite_old_approval(solo,monkeypatch):
    monkeypatch.setenv('AMC_INNOVATION_SOLO_OWNER_APPROVAL','0')
    project=solo[3]['approval']['project_id']
    created=client.post(f'/innovation/projects/{project}/runs',json={'objective':'Fictional old independent approval remains strict','provider':'live'},headers={'Idempotency-Key':uuid4().hex}).json()
    base=f"/innovation/projects/{project}/runs/{created['run']['run_id']}/generation"
    stage=client.post(base,json={'expected_version':1}).json()
    assert stage['approval']['policy_version']=='unbound-generation/v1'
    monkeypatch.setenv('AMC_INNOVATION_SOLO_OWNER_APPROVAL','1')
    assert decide(stage).status_code==403


def test_revocation_after_approval_prevents_dispatch(solo,monkeypatch):
    assert decide(solo[3]).status_code==200
    calls=[];install_fixture_invocation(monkeypatch,calls)
    monkeypatch.setenv('AMC_INNOVATION_SOLO_OWNER_APPROVAL','0')
    result=client.post(solo[2]+'/tick',json={'expected_version':1})
    assert result.status_code==200 and result.json()['status']=='BLOCKED' and calls==[]
    assert 'SOLO_OWNER_POLICY_NOT_SATISFIED' in result.json()['reasons']


def test_generation_approval_does_not_allow_artifact_release(solo):
    assert decide(solo[3]).status_code==200
    from services.langgraph.agency.intake.release import artifact_release_verdict
    stage=solo[3]
    verdict=artifact_release_verdict(simulated=False,verification_passed=True,artifact_id=stage['artifact_id'],verified_version=stage['version'],verified_hash=stage['content_hash'],approval_id=stage['approval']['approval_id'],tenant_id=solo[0],project_id=stage['approval']['project_id'])
    assert not verdict.allowed and 'SEPARATION_OF_DUTIES' in verdict.reasons


@pytest.mark.parametrize('change',[{'max_calls':2},{'max_cost_usd':1},{'timeout_seconds':300},{'max_output_tokens':9000}])
def test_expanded_budgets_cannot_be_admitted_as_solo_plans(solo,change):
    from pydantic import ValidationError
    from services.langgraph.agency.innovation.generation import GenerationSpec
    with pytest.raises(ValidationError):GenerationSpec.model_validate({**solo[3]['spec'],**change})


def test_unrelated_anchor_run_cannot_use_the_exception(solo):
    from services.langgraph.security.local_generation_approval import permits_owner
    from services.langgraph.persistence.runs import get_run_record
    from services.langgraph.security.auth import Principal
    stage=solo[3];approval=stage['approval'];run=get_run_record(approval['run_id'])
    principal=Principal(user_id='fictional-owner',tenant_id=solo[0],role='owner',allowed_project_ids=frozenset({'*'}))
    assert not permits_owner(principal,{**run,'pipeline':'publication'},approval)
    assert not permits_owner(principal,{**run,'metadata':{**run['metadata'],'artifact_hash':'0'*64}},approval)
