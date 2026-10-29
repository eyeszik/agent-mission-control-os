"""Run one authenticated remote render; no database or object-store access.

Use an existing narrowly project-scoped service principal token, supplied in an
operator-selected environment variable. TLS is mandatory except loopback tests.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,os
from pathlib import Path
from urllib.parse import urlparse,quote
from urllib.request import Request,build_opener,HTTPRedirectHandler
from .contracts import RenderSpecification
from . import media,runtime

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        raise ValueError('CONTROL_PLANE_REDIRECT_REFUSED')

def execute(base_url,project,job_id,token,output,completion=None,tenant=None):
    parsed=urlparse(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('INVALID_CONTROL_PLANE_URL')
    if parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1','::1'}):raise ValueError('HTTPS_REQUIRED')
    if not token:raise ValueError('WORKER_TOKEN_REQUIRED')
    endpoint=base_url.rstrip('/')+'/foundry/projects/'+quote(project,safe='')+'/renders/'+quote(job_id,safe='')
    def post(suffix,payload):
        request=Request(endpoint+suffix,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',**({'X-AMC-Tenant':tenant} if tenant else {})},method='POST')
        with build_opener(NoRedirect()).open(request,timeout=30) as response:
            if response.geturl()!=endpoint+suffix:raise ValueError('CONTROL_PLANE_REDIRECT_REFUSED')
            return json.loads(response.read(1_000_000))
    if completion:
        path=Path(completion)
        if path.stat().st_size>22_000_000:raise ValueError('RECEIPT_TOO_LARGE')
        return post('/complete',json.loads(path.read_text()))
    claim=post('/claim',{})
    if not claim['job']:return claim['recovered']
    envelope=claim['job'];spec=RenderSpecification.model_validate(envelope['spec'])
    if spec.spec_hash!=envelope['spec_hash'] or spec.project_id!=project:raise ValueError('DISPATCH_HASH_OR_SCOPE_MISMATCH')
    if any(getattr(spec,k)!=v for k,v in runtime.fingerprint().items()):raise ValueError('WORKER_RUNTIME_MISMATCH')
    if spec.request.engine in media.ENGINES:
        if spec.media_runtime_hash!=media.fingerprint():raise ValueError('WORKER_MEDIA_RUNTIME_MISMATCH')
        if spec.request.engine.value=='remotion' and not spec.license_decision_hash:raise ValueError('LICENSE_APPROVAL_REQUIRED')
        data=media.render(spec.request)
    else:data=runtime.render(spec)
    output=Path(output);output.mkdir(parents=True,exist_ok=True,mode=0o700)
    (output/'candidate.bin').write_bytes(data)
    payload={'fencing_token':envelope['fencing_token'],'content_hash':hashlib.sha256(data).hexdigest(),'data_base64':base64.b64encode(data).decode()}
    # Preserve a receipt for an idempotent same-worker retry after lost ACK.
    (output/'completion.json').write_text(json.dumps(payload))
    for name in ('candidate.bin','completion.json'): (output/name).chmod(0o600)
    result=post('/complete',payload)
    (output/'result.json').write_text(json.dumps(result,indent=2));(output/'result.json').chmod(0o600)
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--project',required=True);parser.add_argument('--job',required=True);parser.add_argument('--out',required=True);parser.add_argument('--token-env',default='AMC_RENDER_WORKER_TOKEN');parser.add_argument('--completion');parser.add_argument('--tenant')
    args=parser.parse_args()
    try:
        result=execute(args.url,args.project,args.job,os.environ.get(args.token_env,''),args.out,args.completion,args.tenant)
        print(json.dumps({'job_id':result['job_id'],'workflow_status':result['workflow_status'],'artifact_status':result['artifact_status']}))
    except Exception as exc:raise SystemExit('REMOTE_WORKER_FAILED:'+type(exc).__name__) from None

if __name__=='__main__':main()
