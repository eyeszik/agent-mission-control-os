"""ASI05: the code sandbox runs in a read-only root mount namespace. These tests run real processes."""

import subprocess
import sys
from pathlib import Path

import pytest

from services.langgraph.agency.execution_fabric.adapters import code_sandbox

needs_mount_ns = pytest.mark.skipif(not code_sandbox.mount_namespace_available(),
                                    reason="no user+mount namespace on this host")

REPO = Path(__file__).resolve().parents[3]


def _probe(script: str, cwd: Path) -> dict[str, str]:
    proc = subprocess.run(code_sandbox.isolated_argv([sys.executable, "-I", "-c", script]),
                          cwd=cwd, capture_output=True, text=True, timeout=60, env=dict(code_sandbox._ENV))
    assert proc.returncode == 0, proc.stderr[-600:]
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


@needs_mount_ns
def test_root_filesystem_is_read_only_inside_the_namespace(tmp_path):
    target_in_repo = REPO / "amc_sandbox_probe_should_not_exist.txt"
    script = f"""
import os, pathlib
def attempt(path):
    try:
        with open(path, 'w') as f:
            f.write('x')
        return 'WRITABLE'
    except OSError as exc:
        return 'BLOCKED:' + str(exc.errno)
print('scratch=' + attempt('probe-scratch.txt'))
print('tmp=' + attempt('/tmp/amc_sandbox_probe.txt'))
print('repo=' + attempt({str(target_in_repo)!r}))
print('home=' + attempt('/home/user/amc_sandbox_probe.txt'))
print('read=' + ('OK' if pathlib.Path({str(REPO / 'README.md')!r}).read_text()[:1] else 'EMPTY'))
"""
    result = _probe(script, tmp_path)
    assert result["scratch"].startswith("BLOCKED"), result
    assert result["tmp"].startswith("BLOCKED"), result
    assert result["repo"].startswith("BLOCKED"), result
    assert result["home"].startswith("BLOCKED"), result
    assert result["read"] == "OK", result
    assert not target_in_repo.exists()
    assert not Path("/tmp/amc_sandbox_probe.txt").exists()


@needs_mount_ns
def test_patch_validation_still_passes_inside_the_read_only_root():
    base = {"pkg/mod.py": "def f():\n    return 1\n"}
    patch = {"pkg/mod.py": "def f():\n    return 2\n"}
    result = code_sandbox.run_patch(base, patch, [["py_compile", "pkg/mod.py"]])
    assert result["passed"] is True
    assert result["isolation"]["root_mount"] == "READ_ONLY_IN_MOUNT_NAMESPACE"
    assert result["applied_to_repository"] is False


def test_patch_validation_refuses_when_no_mount_namespace_exists(monkeypatch):
    monkeypatch.setattr(code_sandbox, "mount_namespace_available", lambda: False)
    monkeypatch.setattr(code_sandbox, "network_namespace_available", lambda: True)
    with pytest.raises(code_sandbox.SandboxViolation) as exc:
        code_sandbox.run_patch({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"}, [["py_compile", "a.py"]])
    assert exc.value.code == "SANDBOX_UNAVAILABLE"
