"""Pinned data-only browser adapters, frame encoding and independent media readback."""
from __future__ import annotations
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import tempfile

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.visual.renderers import _env, _isolated
from .contracts import RenderEngineId, VerificationReport

ROOT=Path(__file__).resolve().parents[4]
BROWSER=ROOT/'packages/creative-renderer/dist/browser'
RUNNER=ROOT/'packages/creative-renderer/browser-runner.cjs'
ENGINES={RenderEngineId.P5:'p5-p2d/v1',RenderEngineId.PIXI:'pixi-webgl/v1',RenderEngineId.THREE:'r3f-orthographic/v1',RenderEngineId.REMOTION:'remotion-player-frames/v1',RenderEngineId.MOTION_CANVAS:'motion-canvas-2d/v1'}
MIMES={'png':'image/png','mp4':'video/mp4','webm':'video/webm','svg':'image/svg+xml'}
MAX_OUTPUT=16_000_000

@lru_cache(maxsize=32)
def _file_hash(path, size, modified):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def digest(path):
    stat=path.stat()
    return _file_hash(str(path),stat.st_size,stat.st_mtime_ns)

def fingerprint():
    try:
        manifest=json.loads((BROWSER/'manifest.json').read_text())
        for name in manifest['files']:
            if Path(name).name!=name: raise ValueError('UNSAFE_BUNDLE_MANIFEST')
        files={name:digest(BROWSER/name) for name in manifest['files']}
        files['manifest.json']=digest(BROWSER/'manifest.json')
        files['browser-runner.cjs']=digest(RUNNER)
        files['media.py']=digest(Path(__file__))
        files['contracts.py']=digest(Path(__file__).with_name('contracts.py'))
        # Actual runtime bytes participate; host paths and timestamps do not.
        command=['node','-e',"const {chromium}=require('./apps/web/node_modules/@playwright/test');process.stdout.write(chromium.executablePath())"]
        executable=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=5).stdout
        files['chromium']=digest(Path(executable))
        for tool in ('ffmpeg','ffprobe'):
            executable=shutil.which(tool)
            if not executable: return None
            files[tool]=digest(Path(executable))
        return canonical_hash(files)
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):
        return None

@lru_cache(maxsize=8)
def _encoders(runtime_hash):
    if not runtime_hash:return ''
    return subprocess.run(['ffmpeg','-v','error','-encoders'],capture_output=True,text=True,timeout=5,env=_env()).stdout

def profile_blockers(request):
    reasons=[]
    if request.engine not in ENGINES: reasons.append('BROWSER_ADAPTER_UNAVAILABLE')
    if request.output_format not in {'png','mp4','webm'}:reasons.append('UNSUPPORTED_ENGINE_OUTPUT_PAIR')
    if request.clock.total_frames>120 or request.dimensions.width*request.dimensions.height*request.clock.total_frames>64_000_000:
        reasons.append('MEDIA_RESOURCE_BUDGET_EXCEEDED')
    if request.output_format in {'mp4','webm'} and (request.dimensions.width%2 or request.dimensions.height%2):
        reasons.append('VIDEO_REQUIRES_EVEN_DIMENSIONS')
    runtime_hash=fingerprint()
    if not runtime_hash:reasons.append('MEDIA_RUNTIME_UNAVAILABLE')
    codec='libx264' if request.output_format=='mp4' else 'libvpx-vp9' if request.output_format=='webm' else None
    if codec and codec not in _encoders(runtime_hash):reasons.append('ENCODER_UNAVAILABLE')
    import importlib.util
    if importlib.util.find_spec('PIL') is None:reasons.append('PNG_VERIFIER_UNAVAILABLE')
    return reasons

def render(request):
    if reasons:=profile_blockers(request):raise ValueError(','.join(reasons))
    with tempfile.TemporaryDirectory(prefix='amc-render-') as tmp:
        root=Path(tmp);spec=root/'input.json'
        spec.write_text(json.dumps({'request':request.model_dump(mode='json'),'output':tmp}))
        command,isolated=_isolated(['node',str(RUNNER),str(spec)])
        if not isolated: raise ValueError('NETWORK_ISOLATION_UNAVAILABLE')
        extra={}
        import os
        if os.environ.get('PLAYWRIGHT_BROWSERS_PATH'): extra['PLAYWRIGHT_BROWSERS_PATH']=os.environ['PLAYWRIGHT_BROWSERS_PATH']
        result=subprocess.run(command,cwd=ROOT,env=_env(extra),capture_output=True,timeout=90)
        if result.returncode:raise RuntimeError('BROWSER_ADAPTER_FAILED:'+result.stderr.decode(errors='replace')[-500:])
        frames=sorted(root.glob('frame_*.png'))
        if len(frames)!=request.clock.total_frames:raise ValueError('FRAME_COUNT_MISMATCH')
        if request.output_format=='png': data=frames[0].read_bytes()
        else:
            output=root/('output.'+request.output_format)
            codec=['-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart'] if request.output_format=='mp4' else ['-c:v','libvpx-vp9','-pix_fmt','yuv420p']
            rate=f'{request.clock.fps_numerator}/{request.clock.fps_denominator}'
            command,isolated=_isolated([shutil.which('ffmpeg'),'-nostdin','-y','-v','error','-framerate',rate,'-i',str(root/'frame_%04d.png'),'-frames:v',str(request.clock.total_frames),*codec,'-threads','2',str(output)])
            if not isolated:raise ValueError('NETWORK_ISOLATION_UNAVAILABLE')
            result=subprocess.run(command,env=_env(),capture_output=True,timeout=90)
            if result.returncode:raise RuntimeError('ENCODE_FAILED')
            if output.stat().st_size>MAX_OUTPUT:raise ValueError('OUTPUT_SIZE_LIMIT')
            data=output.read_bytes()
        if len(data)>MAX_OUTPUT:raise ValueError('OUTPUT_SIZE_LIMIT')
        return data

def container_matches(data, format):
    """Recognize this encoder profile before handing bytes to a native probe."""
    if format=='mp4':
        if len(data)<20 or data[4:8]!=b'ftyp':return False
        size=int.from_bytes(data[:4],'big')
        if size<20 or size>4096 or size>len(data):return False
        brands={data[8:12],*(data[i:i+4] for i in range(16,size,4))}
        return bool(brands & {b'isom',b'iso2',b'iso6',b'mp41',b'mp42',b'avc1'})
    if not data.startswith(b'\x1aE\xdf\xa3'):return False
    def vint(offset, identifier=False):
        if offset>=len(data) or not data[offset]:raise ValueError('INVALID_EBML')
        length=1
        while not data[offset] & (0x80>>(length-1)):
            length+=1
            if length>8:raise ValueError('INVALID_EBML')
        if offset+length>len(data):raise ValueError('INVALID_EBML')
        value=int.from_bytes(data[offset:offset+length],'big')
        if not identifier:value &= (1<<(length*7))-1
        return value,offset+length
    try:
        size,offset=vint(4);end=offset+size
        if end>min(len(data),4096):return False
        while offset<end:
            key,offset=vint(offset,True);size,offset=vint(offset)
            if offset+size>end:return False
            value=data[offset:offset+size];offset+=size
            if key==0x4282:return value==b'webm'
    except ValueError:return False
    return False

def observed_hash(data):return hashlib.sha256(data).hexdigest()

def verify(data,spec):
    from services.langgraph.agency.visual.verify import verify_media
    import io
    from fractions import Fraction
    findings=[];checks=[];status='PASSED'
    request=spec.request;dimensions=request.dimensions
    if len(data)>MAX_OUTPUT:
        findings.append('OUTPUT_SIZE_LIMIT');status='FAILED'
    elif request.output_format=='png':
        try:
            from PIL import Image,ImageChops
        except ImportError:
            status='INCONCLUSIVE';findings.append('PNG_VERIFIER_UNAVAILABLE')
        else:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    if image.format!='PNG' or image.size!=(dimensions.width,dimensions.height):raise ValueError('PNG_DIMENSIONS_MISMATCH')
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.load();rgb=image.convert('RGB')
                    if not ImageChops.difference(rgb,Image.new('RGB',rgb.size,request.scene.background)).getbbox():raise ValueError('PNG_BLANK')
                    if len(rgb.getcolors(rgb.width*rgb.height) or [])<2:raise ValueError('PNG_FLAT')
                checks.extend(['PNG_MAGIC_CRC','FULL_PIXEL_DECODE','DIMENSIONS','NONBLANK'])
            except (ValueError,OSError,Image.DecompressionBombError):status='FAILED';findings.append('PNG_INVALID')
    else:
        magic=container_matches(data,request.output_format)
        if not magic:
            return VerificationReport(status='FAILED',content_hash=observed_hash(data),byte_count=len(data),spec_hash=spec.spec_hash,checks=('CONTAINER_MAGIC',),findings=('CONTAINER_MAGIC_MISMATCH',),verifier='amc-render-media/v1')
        if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
            status='INCONCLUSIVE';findings.append('VIDEO_VERIFIER_UNAVAILABLE')
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/('candidate.'+request.output_format);path.write_bytes(data)
                try:
                    command,isolated=_isolated(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-count_frames','-show_streams','-show_format','-of','json',str(path)])
                    if not isolated:
                        return VerificationReport(status='INCONCLUSIVE',content_hash=observed_hash(data),byte_count=len(data),spec_hash=spec.spec_hash,checks=(),findings=('VIDEO_VERIFIER_ISOLATION_UNAVAILABLE',),verifier='amc-render-media/v1')
                    probe=subprocess.run(command,capture_output=True,text=True,timeout=30,env=_env())
                    result=json.loads(probe.stdout);streams=result['streams']
                    video=[s for s in streams if s['codec_type']=='video']
                    expected_codec='h264' if request.output_format=='mp4' else 'vp9'
                    if len(streams)!=1 or len(video)!=1:raise ValueError('UNEXPECTED_STREAMS')
                    stream=video[0]
                    magic=container_matches(data,request.output_format)
                    if not magic or stream['codec_name']!=expected_codec:raise ValueError('CONTAINER_CODEC_MISMATCH')
                    if (stream['width'],stream['height'])!=(dimensions.width,dimensions.height):raise ValueError('DIMENSIONS_MISMATCH')
                    if Fraction(stream['avg_frame_rate'])!=Fraction(request.clock.fps_numerator,request.clock.fps_denominator):raise ValueError('FRAME_RATE_MISMATCH')
                    if int(stream['nb_read_frames'])!=request.clock.total_frames:raise ValueError('FRAME_COUNT_MISMATCH')
                    # Decode every frame, independently of encoder metadata.
                    decode_command,isolated=_isolated(['ffmpeg','-nostdin','-v','error','-xerror','-protocol_whitelist','file,pipe','-i',str(path),'-f','null','-'])
                    if not isolated:raise ValueError('VERIFIER_ISOLATION_CHANGED')
                    decoded=subprocess.run(decode_command,capture_output=True,timeout=30,env=_env())
                    if decoded.returncode:raise ValueError('VIDEO_DECODE_FAILED')
                    checks.extend(['CONTAINER','CODEC','DIMENSIONS','FRAME_RATE','FRAME_COUNT','FULL_FRAME_DECODE'])
                except (ValueError,KeyError,OSError,subprocess.TimeoutExpired):
                    status='FAILED';findings.append('VIDEO_INVALID')
    return VerificationReport(status=status,content_hash=hashlib.sha256(data).hexdigest(),byte_count=len(data),spec_hash=spec.spec_hash,checks=tuple(checks),findings=tuple(findings),verifier='amc-render-media/v1')
