"""Local-only scratch image build from verified release bytes and host libraries."""
import sys
import platform
import tempfile
import subprocess
from pathlib import Path
import shutil
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.langgraph.agency.obscura_artifact import verified_members

if __name__ == '__main__':
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('UNSUPPORTED_PLATFORM: Linux x64 runtime builder only')
    data = verified_members(Path(sys.argv[1]), 'obscura-x86_64-linux.tar.gz')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'rootfs'
        for dest in ['engine', 'lib/x86_64-linux-gnu', 'lib64']:
            (root / dest).mkdir(parents=True, exist_ok=True)
        for path in root.rglob('*'):
            if path.is_dir(): path.chmod(0o755)
        root.chmod(0o755)
        for name, content in data.items():
            p = root / 'engine' / name; p.write_bytes(content); p.chmod(0o555)
        for name in ['libgcc_s.so.1', 'libm.so.6', 'libc.so.6']:
            dst = root / 'lib/x86_64-linux-gnu' / name
            shutil.copyfile(Path('/lib/x86_64-linux-gnu') / name, dst); dst.chmod(0o444)
        dst = root / 'lib64/ld-linux-x86-64.so.2'
        shutil.copyfile('/lib64/ld-linux-x86-64.so.2', dst); dst.chmod(0o555)
        shutil.copyfile(Path(__file__).with_name('Dockerfile.obscura'), Path(tmp) / 'Dockerfile')
        subprocess.run(['docker','build','--network=none','--pull=false','-t','amc-obscura-runtime:local',tmp],check=True)
