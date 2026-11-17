"""Verify pinned release archives before installation; never executes page code."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[3] / 'docs/browser/obscura-release.json'
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024


def verified_members(archive: Path, asset_name: str) -> dict[str, bytes]:
    """Verify exact archive bytes and reject paths, links, extras and bombs.

    Returns bytes only: callers cannot accidentally extract outside a session.
    Asset identity must match the repository's recorded release, never a request
    supplied digest. Published digests establish identity, not publisher trust.
    """
    assets = json.loads(MANIFEST.read_text())['assets']
    matches = [a for a in assets if a['name'] == asset_name]
    if len(matches) != 1:
        raise ValueError('UNSUPPORTED_ASSET')
    with archive.open('rb') as stream:
        data = stream.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise ValueError('ARCHIVE_LIMIT')
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    if digest != matches[0]['digest']:
        raise ValueError('DIGEST_MISMATCH')
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
        total = 0
        for member in bundle:
            total += member.size
            if (member.name not in {'obscura', 'obscura-worker'} or
                    member.name in out or not member.isfile() or
                    member.size <= 0 or total > MAX_UNPACKED):
                raise ValueError('UNSAFE_ARCHIVE')
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError('INVALID_MEMBER')
            out[member.name] = source.read(member.size + 1)
            if len(out[member.name]) != member.size:
                raise ValueError('TRUNCATED_MEMBER')
    if set(out) != {'obscura', 'obscura-worker'}:
        raise ValueError('MISSING_MEMBER')
    return out


def install(archive: Path, destination: Path, asset_name: str = 'obscura-x86_64-linux.tar.gz') -> dict[str, str]:
    """Install verified bytes into a newly reserved directory; never replace paths."""
    import os
    import tempfile
    import shutil
    contents = verified_members(archive, asset_name)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('DESTINATION_EXISTS')
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='.obscura-install-', dir=destination.parent))
    try:
        for name, content in contents.items():
            path = scratch / name
            path.write_bytes(content)
            path.chmod(0o500)
        # Refuse any concurrent destination, including non-empty directories.
        # os.rename may replace an empty directory, so retain exclusive mkdir
        # ownership instead and install into that freshly reserved directory.
        destination.mkdir(mode=0o700)
        for name in contents:
            os.rename(scratch / name, destination / name)
    finally:
        shutil.rmtree(scratch)
    return {name:hashlib.sha256(value).hexdigest() for name,value in contents.items()}


if __name__ == '__main__':
    import sys
    import platform
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('UNSUPPORTED_PLATFORM: reviewed runtime is Linux x64 only')
    print(json.dumps(install(Path(sys.argv[1]), Path(sys.argv[2])), indent=2))
