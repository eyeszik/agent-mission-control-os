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


def fingerprint() -> dict:
    node = shutil.which('node')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=5).stdout.strip() if node else ''
    return {'package_lock_hash': hashlib.sha256((ROOT / 'pnpm-lock.yaml').read_bytes()).hexdigest(),
            'worker_source_hash': canonical_hash({name: hashlib.sha256((WORKER.parent / name).read_bytes()).hexdigest() for name in ('worker.mjs', 'rough.cjs', 'LICENSE.roughjs')}) if all((WORKER.parent / name).is_file() for name in ('worker.mjs', 'rough.cjs', 'LICENSE.roughjs')) else '0' * 64,
            'runtime_version': version}


@lru_cache(maxsize=16)
def _probe_worker(source_hash: str, runtime_version: str) -> bool:
    if source_hash == '0' * 64 or not runtime_version:
        return False
    node = shutil.which('node')
    flag = '--permission' if int(runtime_version.lstrip('v').split('.')[0]) >= 23 else '--experimental-permission'
    payload = {'request': {'engine': 'rough_js', 'output_format': 'svg', 'seed': 42,
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


def inventory() -> list[dict]:
    fp = fingerprint()
    available = _probe_worker(fp['worker_source_hash'], fp['runtime_version'])
    return [{'engine': engine.value, 'adapter_version': ADAPTER_VERSION if engine is RenderEngineId.ROUGH else None,
             'available': available and engine is RenderEngineId.ROUGH,
             'profiles': ['svg:typed-primitives'] if available and engine is RenderEngineId.ROUGH else [],
             'blockers': ([] if available else ['WORKER_NOT_AVAILABLE']) if engine is RenderEngineId.ROUGH else ['ADAPTER_NOT_IMPLEMENTED'],
             'arbitrary_code': False, 'remote_storage': False, 'isolation_profile': 'typed-primitives/process-v1'}
            for engine in RenderEngineId]


def compile_spec(tenant: str, project: str, request: RenderRequest) -> RenderSpecification:
    return RenderSpecification(tenant_id=tenant, project_id=project, request=request,
                               adapter_version=ADAPTER_VERSION if request.engine is RenderEngineId.ROUGH else None, **fingerprint())


def blockers(spec: RenderSpecification) -> list[str]:
    cap = next(c for c in inventory() if c['engine'] == spec.request.engine.value)
    reasons = list(cap['blockers'])
    if spec.request.output_format != 'svg':
        reasons.append('OUTPUT_PROFILE_NOT_IMPLEMENTED')
    if (spec.request.engine is RenderEngineId.ROUGH and spec.adapter_version != ADAPTER_VERSION) or any(getattr(spec, k) != v for k, v in fingerprint().items()):
        reasons.append('RUNTIME_SPEC_STALE')
    return reasons


def render(spec: RenderSpecification) -> bytes:
    if reasons := blockers(spec):
        raise ValueError(','.join(reasons))
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
    findings: list[str] = []
    observed = hashlib.sha256(data).hexdigest()
    checks = ['SHA256_READBACK', 'BYTE_LIMIT', 'SVG_SCHEMA', 'SVG_ACTIVE_CONTENT', 'DIMENSIONS']
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
        for element in root.iter():
            if element.tag.split('}')[-1] not in allowed:
                findings.append('UNEXPECTED_SVG_ELEMENT')
            for color_key in ('fill', 'stroke'):
                if color_key in element.attrib and element.attrib[color_key] not in colors:
                    findings.append('SCENE_PALETTE_MISMATCH')
            for key, value in element.attrib.items():
                if key.lower().startswith('on') or 'href' in key.lower() or 'url(' in value.lower():
                    findings.append('SVG_ACTIVE_CONTENT')
        if not svg_safety(text).passed:
            findings.append('SVG_SAFETY_FAILED')
    except (ValueError, UnicodeError, ElementTree.ParseError):
        findings.append('SVG_INVALID')
    return VerificationReport(status='FAILED' if findings else 'PASSED', content_hash=observed,
                              byte_count=len(data), spec_hash=spec.spec_hash, checks=tuple(checks),
                              findings=tuple(sorted(set(findings))))
