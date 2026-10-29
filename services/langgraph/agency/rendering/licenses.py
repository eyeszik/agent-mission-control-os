"""Scoped operator license decisions. These do not approve an artifact release."""
from datetime import datetime,timezone
import hashlib,json
from services.langgraph.agency.project_os.memory import resolve
from .contracts import RenderEngineId
from .media import BROWSER

KEY='render.license.remotion'
def license_hash():
    try:
        manifest=json.loads((BROWSER/'manifest.json').read_text())
        return hashlib.sha256((BROWSER/manifest['packages']['remotion']['license_file']).read_bytes()).hexdigest()
    except (OSError,KeyError,ValueError):return None

def decision_hash(tenant,project):
    if not tenant or not project:return None
    from services.langgraph.persistence.project_knowledge import list_memory
    records=[r for r in list_memory(tenant_id=tenant,project_id=project) if r.subject_key==KEY and r.authority.value=='APPROVED_PROJECT_DECISION']
    winner=resolve(records,now=datetime.now(timezone.utc))['winner']
    if not winner:return None
    body=winner.body
    if not body.get('permitted') or body.get('license_hash')!=license_hash() or not body.get('evidence_refs'):return None
    return winner.content_hash

def record(principal,project,permitted,basis,evidence_refs):
    from services.langgraph.api.routes._project_common import authorize_project_access,require_approver
    from services.langgraph.persistence.project_knowledge import write_memory
    authorize_project_access(principal,project);require_approver(principal,'Render license decision')
    if not basis.strip() or any(not ref.strip() for ref in evidence_refs) or len(evidence_refs)!=len(set(evidence_refs)):
        raise ValueError('License decisions require a substantive basis and distinct nonblank evidence references')
    if not license_hash():raise ValueError('LICENSE_BYTES_UNAVAILABLE')
    from services.langgraph.persistence.database import atomic_transaction
    from .service import _policy_lock
    with atomic_transaction() as db:
        _policy_lock(db,{'tenant_id':principal.tenant_id,'project_id':project,'spec':{'render':{'request':{'engine':'remotion'}}}})
        return write_memory(tenant_id=principal.tenant_id,project_id=project,actor=principal.user_id,scope='M2_PROJECT',authority='APPROVED_PROJECT_DECISION',subject_key=KEY,body={'permitted':permitted,'basis':basis,'evidence_refs':list(evidence_refs),'license_hash':license_hash()},source_refs=tuple(evidence_refs))
