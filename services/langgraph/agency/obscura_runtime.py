"""Local runtime configuration, not identity, authority, or an execution permit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = ROOT / '.amc/obscura-runtime.json'
_CACHE_LOCK = threading.Lock()
_CACHE: tuple[tuple[str, ...], float, dict] | None = None


class RuntimeProfile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal['amc-obscura-runtime/v1'] = 'amc-obscura-runtime/v1'
    enabled: bool = True
    public_enabled: bool = False
    binary_dir: str = Field(min_length=1, max_length=4096)
    runtime_image: str = Field(pattern=r'^sha256:[a-f0-9]{64}$')
    https_proxy: str | None = Field(default=None, max_length=2048)
    ssl_cert_file: str | None = Field(default=None, max_length=4096)

    @field_validator('https_proxy')
    @classmethod
    def safe_proxy(cls, value):
        if value is None: return None
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise ValueError('Invalid proxy') from None
        if (parsed.scheme != 'http' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in {'', '/'} or parsed.query
                or parsed.fragment or (port is not None and not 1 <= port <= 65535)):
            raise ValueError('Proxy must not contain credentials or URL data')
        return value

    def environment(self) -> dict[str, str]:
        return {'AMC_OBSCURA_ENABLED': '1' if self.enabled else '0',
                'AMC_OBSCURA_PUBLIC_ENABLED': '1' if self.public_enabled else '0',
                'AMC_OBSCURA_BINARY_DIR': self.binary_dir,
                'AMC_OBSCURA_RUNTIME_IMAGE': self.runtime_image,
                **({'AMC_OBSCURA_HTTPS_PROXY': self.https_proxy} if self.https_proxy else {}),
                **({'SSL_CERT_FILE': self.ssl_cert_file} if self.ssl_cert_file else {})}


def load_profile(path: Path) -> RuntimeProfile:
    if path.is_symlink(): raise ValueError('PROFILE_SYMLINK_REFUSED')
    with path.open('rb') as stream: raw = stream.read(8193)
    if len(raw) > 8192: raise ValueError('PROFILE_SIZE_LIMIT')
    return RuntimeProfile.model_validate_json(raw)


def save_profile(path: Path, profile: RuntimeProfile, *, replace: bool = False) -> None:
    if path.is_symlink() or (path.exists() and not replace):
        raise ValueError('PROFILE_EXISTS_OR_SYMLINK')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(profile.model_dump_json(indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Exclusive creation also protects against a concurrent writer.
            os.link(temporary, path)
            temporary.unlink()
        assert load_profile(path) == profile
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def apply_profile(path: Path) -> None:
    # Explicit process environment wins, including an emergency disable flag.
    for key, value in load_profile(path).environment().items():
        os.environ.setdefault(key, value)



def resource_limits_status() -> dict:
    """Fail closed when rootless Docker cannot enforce the requested limits."""
    try:
        command = subprocess.run(['docker','info','--format',
            '{{json .}}'],
            capture_output=True,text=True,timeout=3,
            env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'})
        if command.returncode != 0:
            return {'supported':False,'reason':'DOCKER_UNAVAILABLE'}
        capabilities = json.loads(command.stdout)
        supported = all(capabilities.get(key) is True for key in ('MemoryLimit','SwapLimit','PidsLimit','CpuCfsQuota','CpuCfsPeriod')) and capabilities.get('CgroupDriver') in {'systemd','cgroupfs'}
        return {'supported':supported,'reason':None if supported else 'RESOURCE_LIMITS_UNAVAILABLE'}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'supported':False,'reason':'DOCKER_CAPABILITIES_UNAVAILABLE'}


def runtime_status(*, refresh: bool = False) -> dict:
    """Cheap prerequisites with a five-second Docker metadata cache, not approval.

    Dispatch still checks binary bytes and runs the bounded container; a cached
    capability check can never bypass those execution-time safeguards.
    """
    global _CACHE
    checked = datetime.now(timezone.utc).isoformat()
    def result(ready, reason):
        return {'ready': ready, 'reasons': [] if ready else [reason], 'checked_at': checked}
    if os.environ.get('AMC_OBSCURA_ENABLED') != '1': return result(False, 'OBSCURA_DISABLED')
    directory = os.environ.get('AMC_OBSCURA_BINARY_DIR', '')
    image = os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE', '')
    if not directory or any(not (Path(directory)/name).is_file() or (Path(directory)/name).is_symlink()
                            for name in ('obscura', 'obscura-worker')):
        return result(False, 'BINARY_DIRECTORY_UNAVAILABLE')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image): return result(False, 'INVALID_RUNTIME_IMAGE')
    if not shutil.which('docker') or not shutil.which('prlimit'): return result(False, 'LOCAL_TOOL_UNAVAILABLE')
    try:
        fingerprints = tuple(str((Path(directory)/name).stat().st_mtime_ns) + ':' + str((Path(directory)/name).stat().st_size)
                             for name in ('obscura', 'obscura-worker'))
    except OSError:
        return result(False, 'BINARY_DIRECTORY_UNAVAILABLE')
    key = (directory, image, *fingerprints)
    with _CACHE_LOCK:
        if not refresh and _CACHE and _CACHE[0] == key and time.monotonic() < _CACHE[1]:
            return dict(_CACHE[2])
        def remember(value):
            global _CACHE
            _CACHE = (key, time.monotonic()+5, value)
            return dict(value)
        try:
            limits = resource_limits_status()
            if not limits['supported']:
                return remember(result(False, limits['reason']))
            import hashlib
            from services.langgraph.agency.obscura_worker import DIGESTS
            for name, expected in DIGESTS.items():
                with (Path(directory)/name).open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        return remember(result(False, 'BINARY_INTEGRITY'))
            command = subprocess.run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'],
                capture_output=True, text=True, timeout=3,
                env={'PATH':'/usr/local/bin:/usr/bin:/bin', 'LANG':'C.UTF-8'})
            status = result(command.returncode == 0 and command.stdout.strip() == image, 'RUNTIME_IMAGE_UNAVAILABLE')
        except (OSError, subprocess.SubprocessError):
            status = result(False, 'DOCKER_UNAVAILABLE')
        return remember(status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    configure = sub.add_parser('configure')
    configure.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    configure.add_argument('--binary-dir', required=True, type=Path)
    configure.add_argument('--image', required=True)
    configure.add_argument('--public', action='store_true')
    configure.add_argument('--proxy')
    configure.add_argument('--ssl-cert-file', type=Path)
    configure.add_argument('--replace', action='store_true')
    doctor = sub.add_parser('doctor')
    doctor.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    doctor.add_argument('--probe', action='store_true')
    launch = sub.add_parser('launch')
    launch.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    launch.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            profile = RuntimeProfile(binary_dir=str(args.binary_dir.resolve(strict=True)),
                                     runtime_image=args.image, public_enabled=args.public, https_proxy=args.proxy,
                                     ssl_cert_file=str(args.ssl_cert_file.resolve(strict=True)) if args.ssl_cert_file else None)
            save_profile(args.profile, profile, replace=args.replace)
            print(json.dumps({'status':'PROFILE_SAVED','profile':str(args.profile)}))
            return 0
        apply_profile(args.profile)
        status = runtime_status(refresh=True)
        if args.command == 'doctor':
            if args.probe and status['ready']:
                from services.langgraph.agency.obscura_worker import extract
                text = extract('<h1>AMC runtime probe</h1>', Path(os.environ['AMC_OBSCURA_BINARY_DIR']))
                if 'AMC runtime probe' not in text: raise RuntimeError('PROBE_OUTPUT_MISMATCH')
                status['probe'] = 'PASS'
            print(json.dumps(status))
            return 0 if status['ready'] else 1
        if os.environ.get('AMC_OBSCURA_ENABLED') == '1' and not status['ready']:
            print(json.dumps({**status,'message':'Obscura dispatch is blocked; independent API services remain available'}), file=sys.stderr)
        argv = args.args[1:] if args.args[:1] == ['--'] else args.args
        if argv[:3] != ['-m', 'uvicorn', 'services.langgraph.app.main:app']:
            raise ValueError('UNSUPPORTED_LAUNCH_TARGET')
        os.execv(sys.executable, [sys.executable, *argv])
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
        # Pydantic's default errors echo supplied values. Do not expose those.
        print(json.dumps({'ready':False,'reasons':['PROFILE_OR_RUNTIME_VALIDATION_FAILED']}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
