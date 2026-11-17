"""Opt-in, local-only, project-authorized offline Obscura extraction."""
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field
from services.langgraph.security.auth import Principal, get_principal
from services.langgraph.api.routes._project_common import authorize_project_access, storage_adapter
from services.langgraph.agency.execution_fabric.adapters.obscura import available, Input as ExtractionInput
from services.langgraph.agency.execution_fabric.contracts import ExecutionContext, FabricBudget, ExecutionState
from services.langgraph.agency.execution_fabric.consumer import execute_mission
from services.langgraph.agency.execution_fabric.schedule import from_compiled_agency_plan
from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
from services.langgraph.agency.compiled.backchain import DeliverableSpec
from services.langgraph.agency.role_os import RoleOSRegistry
from services.langgraph.persistence.proofs import get_run_proof_bundle
from services.langgraph.persistence.agency_kernel import get_artifact

router = APIRouter()
ROOT = Path(__file__).resolve().parents[4]


class BrowserCapabilities(BaseModel):
    provider: Literal['obscura']
    enabled: bool
    mode: Literal['SUPPLIED_HTML_ONLY', 'PUBLIC_HTTPS_EXTRACTION']
    public_browsing: bool
    max_input_bytes: int


class ExtractionResponse(BaseModel):
    run_id: str
    status: ExecutionState
    replayed: bool
    reasons: tuple[str, ...] = ()
    artifact_ref: str | None
    content: dict[str, Any] | None
    proof: dict[str, Any]


def enabled():
    return os.environ.get('AMC_ENV') == 'local' and available()


@router.get('/projects/{project_id}/capabilities', response_model=BrowserCapabilities)
def capabilities(project_id: str, principal: Principal = Depends(get_principal)):
    authorize_project_access(principal, project_id)
    public = enabled() and os.environ.get('AMC_OBSCURA_PUBLIC_ENABLED') == '1'
    return {'provider': 'obscura', 'enabled': enabled(), 'mode': 'PUBLIC_HTTPS_EXTRACTION' if public else 'SUPPLIED_HTML_ONLY',
            'public_browsing': public, 'max_input_bytes': 262144}


@router.post('/projects/{project_id}/extractions', response_model=ExtractionResponse)
def extract(project_id: str, req: ExtractionInput, principal: Principal = Depends(get_principal),
            idempotency_key: str | None = Header(default=None, alias='Idempotency-Key', min_length=1, max_length=128)):
    workspace = authorize_project_access(principal, project_id)
    if principal.role not in {'owner', 'admin', 'operator'}:
        raise HTTPException(403, 'Operator required')
    if not enabled():
        raise HTTPException(503, 'Obscura local extraction is disabled')
    if req.url and not idempotency_key:
        raise HTTPException(400, 'An Idempotency-Key is required for URL retrieval')
    if req.url and os.environ.get('AMC_OBSCURA_PUBLIC_ENABLED') != '1':
        raise HTTPException(503, 'Public HTTPS extraction is disabled')
    if req.html and len(req.html.encode()) > 262144:
        raise HTTPException(422, 'HTML exceeds byte limit')
    identity = hashlib.sha256(json.dumps({'inputs':req.model_dump(exclude_none=True), 'runtime_image':os.environ['AMC_OBSCURA_RUNTIME_IMAGE'], 'adapter':'obscura/v0.2.7', 'public':bool(req.url), 'retrieval_key':idempotency_key if req.url else None}, sort_keys=True).encode()).hexdigest()
    # Stable local plan epoch: no volatile constraints or upstream sources are
    # inferred from it. Actual execution times are recorded by canonical receipts.
    spec = DeliverableSpec(id='extraction', requested_outcome='Governed page extraction '+identity,
        output_contract='research_brief', acceptance_criteria=('Untrusted source and exact content hashes',), domains=('BRAND',))
    request = CompiledAgencyRequest(project_id=project_id, as_of='2026-11-17T00:00:00Z', deliverables=(spec,))
    schedule = from_compiled_agency_plan(compile_agency_plan(request,registry=RoleOSRegistry(ROOT/'runtime/role_os')))
    context = ExecutionContext.from_server(tenant_id=workspace.tenant_id,project_id=project_id,
        actor=principal.user_id,mode='LOCAL',export_root=ROOT,
        budget=FabricBudget(max_invocations=1,max_output_bytes=1048576,max_attempts_per_cell=1,max_tool_calls_per_node=1))
    adapter = storage_adapter()
    report = execute_mission(schedule,context,node_inputs={'work:research_brief':req.model_dump(exclude_none=True)},
        skill_overrides={'work:research_brief':'obscura_extract'},adapter=adapter)
    outcome = report.cells['cell:research_brief']
    content = None
    if outcome.artifact_ref:
        head = get_artifact(outcome.artifact_ref.rsplit(':v',1)[0])
        content = json.loads(adapter.get_bytes(head['content_location']))
    return {'run_id':report.run_id,'status':outcome.state.value,'replayed':outcome.replayed,'reasons':outcome.reasons,
            'artifact_ref':outcome.artifact_ref,'content':content,'proof':get_run_proof_bundle(report.run_id)['summary']}
