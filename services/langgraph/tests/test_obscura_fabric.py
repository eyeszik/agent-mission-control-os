import os
import pytest
from pathlib import Path
from services.langgraph.tests.test_execution_fabric import _ctx, _schedule
from services.langgraph.agency.compiled.backchain import DeliverableSpec
from services.langgraph.agency.execution_fabric.consumer import execute_mission
from services.langgraph.agency.execution_fabric.contracts import ExecutionState
from services.langgraph.agency.role_os import RoleOSRegistry
from services.langgraph.persistence.proofs import get_run_proof_bundle


def test_real_extraction_persists_canonical_proofs(tmp_path,monkeypatch):
    if not os.environ.get('TEST_OBSCURA_BIN') or not os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE'):
        pytest.skip('explicit verified binary and bounded local runtime required')
    monkeypatch.setenv('AMC_OBSCURA_ENABLED','1')
    monkeypatch.setenv('AMC_OBSCURA_BINARY_DIR',os.environ['TEST_OBSCURA_BIN'])
    ctx=_ctx(tmp_path)
    registry=RoleOSRegistry(Path(__file__).resolve().parents[3]/'runtime/role_os')
    deliverable=DeliverableSpec(id='research',requested_outcome='Extract supplied fixture',output_contract='research_brief',acceptance_criteria=('source identity',),domains=('BRAND',))
    from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
    from services.langgraph.agency.execution_fabric.schedule import from_compiled_agency_plan
    request=CompiledAgencyRequest(project_id=ctx.project_id,as_of='2026-11-17T00:00:00Z',deliverables=(deliverable,))
    schedule=from_compiled_agency_plan(compile_agency_plan(request,registry=registry))
    report=execute_mission(schedule,ctx,node_inputs={'work:research_brief':{'html':'<h1>Fictional fixture</h1>','source_ref':'fixture:test'}},skill_overrides={'work:research_brief':'obscura_extract'})
    assert report.cells['cell:research_brief'].state == ExecutionState.SUCCEEDED, report.model_dump()
    replay=execute_mission(schedule,ctx,node_inputs={'work:research_brief':{'html':'<h1>Fictional fixture</h1>','source_ref':'fixture:test'}},skill_overrides={'work:research_brief':'obscura_extract'})
    assert replay.cells['cell:research_brief'].replayed
    proof=get_run_proof_bundle(report.run_id)['summary']
    assert proof['dispatch_count']==proof['execution_count']==proof['observation_count']==1
