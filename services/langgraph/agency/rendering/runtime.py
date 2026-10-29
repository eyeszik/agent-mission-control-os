"""Bounded rendering runtime. Only validated typed primitives can execute.

No arbitrary JS/TSX/URLs, no browser network, no credentials in render workers.
The process profile is deliberately not advertised as an arbitrary-code sandbox.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
from xml.etree import ElementTree

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.verifiers import svg_safety
from .contracts import RenderEngineId, RenderRequest, RenderSpecification, VerificationReport

ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / 'packages/creative-renderer/dist/worker.mjs'
SOURCE = ROOT / 'packages/creative-renderer/worker.mjs'
ADAPTER_VERSION = 'rough-svg/v1'
ADAPTERS = {RenderEngineId.ROUGH: ADAPTER_VERSION, RenderEngineId.PAPER: 'paper-path-svg/v1',
            RenderEngineId.SVG: 'svg-path-array/v1'}
BUNDLE_FILES = ('worker.mjs', 'rough.cjs', 'LICENSE.roughjs', 'paper.cjs', 'LICENSE.paper',
                'node/self.js', 'node/extend.js', 'node/canvas.js', 'node/xml.js', 'node/package.json',
                'svg.cjs', 'LICENSE.svgjs')


def fingerprint() -> dict:
    node = shutil.which('node')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=5).stdout.strip() if node else ''
    return {'package_lock_hash': hashlib.sha256((ROOT / 'pnpm-lock.yaml').read_bytes()).hexdigest(),
            'worker_source_hash': canonical_hash({name: hashlib.sha256((WORKER.parent / name).read_bytes()).hexdigest() for name in BUNDLE_FILES}) if all((WORKER.parent / name).is_file() for name in BUNDLE_FILES) else '0' * 64,
            'runtime_version': version}


@lru_cache(maxsize=16)
def _probe_worker(source_hash: str, runtime_version: str, engine: str = 'rough_js') -> bool:
    if source_hash == '0' * 64 or not runtime_version:
        return False
    node = shutil.which('node')
    flag = '--permission' if int(runtime_version.lstrip('v').split('.')[0]) >= 23 else '--experimental-permission'
    payload = {'request': {'engine': engine, 'output_format': 'svg', 'seed': 42,
        'dimensions': {'width': 16, 'height': 16}, 'clock': {'total_frames': 1},
        'scene': {'background': '#ffffff', 'primitives': [{'kind': 'rectangle', 'x': 1, 'y': 1,
            'width': 8, 'height': 8, 'fill': '#ffffff', 'stroke': '#000000', 'stroke_width': 1}]}}}
    try:
        result = subprocess.run([node, flag, f'--allow-fs-read={WORKER.parent}', str(WORKER)],
            input=json.dumps(payload).encode(), capture_output=True, timeout=5,
            env={'PATH': str(Path(node).parent)}, close_fds=True)
        return result.returncode == 0 and b'<path ' in result.stdout and len(result.stdout) < 100000
    except (OSError, subprocess.TimeoutExpired):
        return False


def inventory(tenant_id=None, project_id=None) -> list[dict]:
    fp = fingerprint()
    available = {engine: _probe_worker(fp['worker_source_hash'], fp['runtime_version'], engine.value) for engine in ADAPTERS}
    from . import media
    from .licenses import decision_hash
    browser_hash=media.fingerprint()
    records=[]
    for engine in RenderEngineId:
        is_browser=engine in media.ENGINES
        licensed=engine is not RenderEngineId.REMOTION or bool(decision_hash(tenant_id,project_id))
        ok=_probe_media(engine.value,browser_hash) if is_browser and browser_hash and licensed else available.get(engine,False)
        reasons=[] if ok else ['WORKER_NOT_AVAILABLE']
        if is_browser and not browser_hash: reasons=['MEDIA_RUNTIME_UNAVAILABLE']
        if not licensed:
            reasons.append('LICENSE_APPROVAL_REQUIRED');ok=False
        profiles=['png:typed-primitives'] if is_browser else ['svg:typed-primitives']
        if is_browser and ok:
            encoders=media._encoders(browser_hash)
            if 'libx264' in encoders:profiles.append('mp4:h264')
            if 'libvpx-vp9' in encoders:profiles.append('webm:vp9')
        records.append({'engine':engine.value,'adapter_version':media.ENGINES.get(engine) or ADAPTERS.get(engine),
          'available':ok,'profiles':profiles if ok else [],
          'blockers':reasons,'arbitrary_code':False,'remote_storage':False,'isolation_profile':'typed-primitives/network-namespace-v1' if is_browser else 'typed-primitives/process-v1'})
    return records


@lru_cache(maxsize=32)
def _probe_media(engine, runtime_hash):
    from . import media
    request=RenderRequest(workflow_id='probe',task_id='probe',brief='Non-commercial adapter evaluation',engine=engine,output_format='png',dimensions={'width':64,'height':64},scene={'primitives':[{'kind':'rectangle','x':8,'y':8,'width':32,'height':32}]})
    try:
        data=media.render(request)
        return data.startswith(b'\x89PNG\r\n\x1a\n')
    except (ValueError,RuntimeError,OSError,subprocess.TimeoutExpired):
        return False


def compile_spec(tenant: str, project: str, request: RenderRequest) -> RenderSpecification:
    from . import media
    from .licenses import decision_hash
    extra={}
    if request.engine in media.ENGINES:
        extra={'isolation_profile':'typed-primitives/network-namespace-v1','media_runtime_hash':media.fingerprint(),'license_decision_hash':decision_hash(tenant,project) if request.engine is RenderEngineId.REMOTION else None}
    return RenderSpecification(tenant_id=tenant, project_id=project, request=request,
                               adapter_version=media.ENGINES.get(request.engine) or ADAPTERS.get(request.engine), **extra, **fingerprint())


def blockers(spec: RenderSpecification) -> list[str]:
    from . import media
    from .licenses import decision_hash
    if spec.request.engine in media.ENGINES:
        reasons=media.profile_blockers(spec.request)
        if spec.media_runtime_hash!=media.fingerprint():reasons.append('RUNTIME_SPEC_STALE')
        if spec.request.engine is RenderEngineId.REMOTION:
            if not spec.license_decision_hash or spec.license_decision_hash!=decision_hash(spec.tenant_id,spec.project_id):reasons.append('LICENSE_APPROVAL_REQUIRED')
    else:
        fp=fingerprint()
        reasons=[] if spec.request.engine in ADAPTERS and _probe_worker(fp['worker_source_hash'],fp['runtime_version'],spec.request.engine.value) else ['WORKER_NOT_AVAILABLE']
        if spec.request.output_format!='svg':reasons.append('OUTPUT_PROFILE_NOT_IMPLEMENTED')
    expected=media.ENGINES.get(spec.request.engine) or ADAPTERS.get(spec.request.engine)
    if spec.adapter_version!=expected or any(getattr(spec,k)!=v for k,v in fingerprint().items()):reasons.append('RUNTIME_SPEC_STALE')
    return reasons

def render(spec: RenderSpecification) -> bytes:
    if reasons := blockers(spec):
        raise ValueError(','.join(reasons))
    from . import media
    if spec.request.engine in media.ENGINES:return media.render(spec.request)
    node = shutil.which('node')
    # Node's permission model denies filesystem reads except the sealed worker,
    # child processes, native addons and workers. Input is a strict data schema.
    # No claim of OS-level network isolation or arbitrary-source execution.
    result = subprocess.run([node, '--permission' if int(spec.runtime_version.lstrip('v').split('.')[0]) >= 23 else '--experimental-permission', f'--allow-fs-read={WORKER.parent}',
                             '--max-old-space-size=128', str(WORKER)],
                            input=spec.model_dump_json().encode(), capture_output=True, timeout=15,
                            env={'PATH': str(Path(node).parent), 'LANG': 'C.UTF-8'}, close_fds=True)
    if result.returncode:
        raise RuntimeError('RENDER_WORKER_FAILED')
    if not result.stdout or len(result.stdout) > 2_000_000:
        raise ValueError('OUTPUT_SIZE_LIMIT')
    return result.stdout


def verify(data: bytes, spec: RenderSpecification) -> VerificationReport:
    from . import media
    if spec.request.engine in media.ENGINES and spec.request.output_format in {'png','mp4','webm'}:return media.verify(data,spec)
    findings: list[str] = []
    observed = hashlib.sha256(data).hexdigest()
    checks = ['SHA256_READBACK', 'BYTE_LIMIT', 'SVG_SCHEMA', 'SVG_ACTIVE_CONTENT', 'DIMENSIONS']
    if spec.request.output_format != 'svg' or spec.request.engine not in ADAPTERS:
        return VerificationReport(status='INCONCLUSIVE', content_hash=observed, byte_count=len(data),
                                  spec_hash=spec.spec_hash, checks=(), findings=('VERIFIER_PROFILE_UNAVAILABLE',))
    try:
        if len(data) > 2_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('UNSAFE_XML')
        text = data.decode('utf-8')
        root = ElementTree.fromstring(text)
        dims = spec.request.dimensions
        if root.tag != '{http://www.w3.org/2000/svg}svg' or root.attrib.get('viewBox') != f'0 0 {dims.width} {dims.height}':
            findings.append('SVG_DIMENSIONS_MISMATCH')
        colors = {spec.request.scene.background, 'none'} | {p.fill for p in spec.request.scene.primitives} | {p.stroke for p in spec.request.scene.primitives}
        allowed = {'svg', 'rect', 'path'}
        attributes = {'svg': {'viewBox', 'width', 'height'},
                      'rect': {'width', 'height', 'fill'},
                      'path': {'d', 'fill', 'stroke', 'stroke-width'}}
        paths = 0
        for element in root.iter():
            tag = element.tag.removeprefix('{http://www.w3.org/2000/svg}')
            if tag not in allowed:
                findings.append('UNEXPECTED_SVG_ELEMENT')
            if set(element.attrib) - attributes.get(tag, set()):
                findings.append('UNEXPECTED_SVG_ATTRIBUTE')
            if tag == 'path':
                paths += 1
                import re
                if not element.attrib.get('d') or not re.fullmatch(r'[MmLlHhVvCcSsQqTtAaZz0-9.,+\-\seE]+', element.attrib['d']):
                    findings.append('INVALID_PATH_DATA')
            for color_key in ('fill', 'stroke'):
                if color_key in element.attrib and element.attrib[color_key] not in colors:
                    findings.append('SCENE_PALETTE_MISMATCH')
            for key, value in element.attrib.items():
                if key.lower().startswith('on') or 'href' in key.lower() or 'url(' in value.lower():
                    findings.append('SVG_ACTIVE_CONTENT')
        if paths < len(spec.request.scene.primitives):
            findings.append('SCENE_PATHS_MISSING')
        if not svg_safety(text).passed:
            findings.append('SVG_SAFETY_FAILED')
    except (ValueError, UnicodeError, ElementTree.ParseError):
        findings.append('SVG_INVALID')
    return VerificationReport(status='FAILED' if findings else 'PASSED', content_hash=observed,
                              byte_count=len(data), spec_hash=spec.spec_hash, checks=tuple(checks),
                              findings=tuple(sorted(set(findings))))
