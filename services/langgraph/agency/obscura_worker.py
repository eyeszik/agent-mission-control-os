"""Cgroup-bounded networkless container worker; no page-derived authority."""
from __future__ import annotations
import hashlib
import fcntl
import re
import uuid
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from threading import Event

DIGESTS = {
    'obscura': '547f9d8a60048983f0e45c310f160d1239575af062af28e4f6755e361f8abcbf',
    'obscura-worker': '6956274a7e517666386493962866f95a39ace2f71d864ad2e3bac7640145c311',
}


@contextmanager
def slot():
    root = Path(tempfile.gettempdir()) / f'amc-obscura-slots-{os.getuid()}'
    root.mkdir(mode=0o700, exist_ok=True)
    for i in range(2):
        handle = (root / str(i)).open('a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            continue
        try:
            yield
        finally:
            handle.close()
        return
    raise RuntimeError('CONCURRENCY_LIMIT')


def extract(html: str, binary_dir: Path, *, format: str = 'markdown', cancel: Event | None = None) -> str:
    with slot():
        return _extract(html, binary_dir, format=format, cancel=cancel)


def _extract(html: str, binary_dir: Path, *, format: str = 'markdown', cancel: Event | None = None) -> str:
    """Only supplied HTML; no browser network, downloads or caller JS command.

    Linux x64 development path with a locally built immutable runtime image.
    Redirect/subresource fetching is deliberately unavailable inside the worker.
    """
    if cancel is not None and cancel.is_set():
        raise RuntimeError('CANCELLED')
    if format not in {'markdown', 'html', 'text'}:
        raise ValueError('UNSUPPORTED_FORMAT')
    if len(html.encode()) > 262144:
        raise ValueError('INPUT_LIMIT')
    binary_dir = binary_dir.resolve(strict=True)
    for name, digest in DIGESTS.items():
        path = binary_dir / name
        if path.is_symlink():
            raise ValueError('BINARY_INTEGRITY')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('BINARY_INTEGRITY')
    image = os.environ.get('AMC_OBSCURA_RUNTIME_IMAGE', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
        raise RuntimeError('BLOCKED_RUNTIME_IMAGE')
    with tempfile.TemporaryDirectory(prefix='amc-obscura-') as tmp:
        Path(tmp).chmod(0o700)
        page = Path(tmp) / 'page.html'
        page.write_text(html, encoding='utf-8')
        page.chmod(0o444)
        out, err = Path(tmp) / 'out', Path(tmp) / 'err'
        name = 'amc-obscura-' + uuid.uuid4().hex
        command = ['prlimit', '--fsize=1048576', '--cpu=20', '--nofile=128', '--core=0',
                   'docker', 'run', '--rm', '--pull=never', '--name', name,
                   '--network=none', '--read-only', '--user=65534:65534',
                   '--cap-drop=ALL', '--security-opt=no-new-privileges',
                   '--memory=512m', '--memory-swap=512m', '--pids-limit=64', '--cpus=1',
                   '--ulimit', 'nofile=128:128', '--ulimit', 'core=0:0',
                   '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
                   '--mount', f'type=bind,src={page},dst=/input.html,readonly',
                   '--env', 'HOME=/tmp', '--env', 'LANG=C.UTF-8',
                   '--entrypoint=/engine/obscura', image, 'fetch',
                   'file:///input.html', '--dump', format, '--timeout', '5']
        with out.open('wb') as stdout, err.open('wb') as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=tmp,
                env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}, start_new_session=True)
            try:
                deadline = time.monotonic() + 15
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise RuntimeError('CANCELLED')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('WORKER_TIMEOUT')
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                # Kill descendants even when the parent exits or times out.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10,
                    env={'PATH': '/usr/local/bin:/usr/bin:/bin'})
        if process.returncode:
            raise RuntimeError('BLOCKED_WORKER')
        return out.read_text(encoding='utf-8')
