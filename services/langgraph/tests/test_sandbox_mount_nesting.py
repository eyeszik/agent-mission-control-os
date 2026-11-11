"""ASI05: a nested bind mount must never be prepared inside one already mounted read-only.

``sandbox.wrap`` builds a chroot out of explicit bind mounts. Each mount is
created with ``mkdir -p`` and, for a file, ``: > target``. If a narrower path is
mounted *after* a directory that already contains it, that write lands on the
read-only bind and fails with ``EACCES`` (``Read-only file system``), so the
whole sandbox never starts and the caller sees only its exit code.

This is the GitHub-runner arrangement, not a hypothetical: Playwright's bundled
browser is reachable as ``/usr/bin/chromium`` there, while ``/usr`` is one of
``_SYSTEM_DIRS`` and is already mounted. The redundant mount made every AVIC
render exit 2 with no test name attached to the cause. The first test pins the
old ordering failing, the second pins the new ordering working, and the third
pins that a genuinely separate path is still mounted rather than dropped.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from services.langgraph.agency.ucpo.sandbox import _dedupe_mounts, _mount, _SYSTEM_DIRS, probe_isolation, wrap

needs_sandbox = pytest.mark.skipif(
    not probe_isolation().available,
    reason=f"NOT_RUN: sandbox unavailable on this host ({'; '.join(probe_isolation().reasons)})",
)


def test_dedupe_drops_a_path_already_covered_by_a_system_directory():
    paths = [Path(p) for p in _SYSTEM_DIRS if Path(p).exists()]
    # /usr/local/bin is *under* /usr deliberately: a browser installed there is
    # covered by the /usr mount, which is the case that used to fail.
    paths += [Path("/usr/bin/chromium"), Path("/usr/local/bin/chromium"), Path("/opt/hostedtoolcache/browser")]
    kept = _dedupe_mounts(paths)

    assert Path("/usr/bin/chromium") not in kept, "mounted after /usr, which makes the mount fail"
    assert Path("/usr/local/bin/chromium") not in kept, "/usr/local/bin is inside /usr"
    assert Path("/opt/hostedtoolcache/browser") in kept, "outside every system directory, must stay"
    assert Path("/usr") in kept


def test_dedupe_is_order_sensitive_and_keeps_the_widest_mount_first():
    wide = Path("/usr")
    narrow = Path("/usr/bin/chromium")
    assert _dedupe_mounts([wide, narrow]) == [wide]
    # Narrow first then wide is the reverse dependency: the narrow one is
    # mounted while the parent directory is still writable, so both are kept.
    assert _dedupe_mounts([narrow, wide]) == [narrow, wide]


def test_dedupe_is_idempotent_and_preserves_distinct_siblings():
    paths = [Path("/usr"), Path("/bin"), Path("/usr/bin/env"), Path("/bin/sh")]
    once = _dedupe_mounts(paths)
    assert once == [Path("/usr"), Path("/bin")]
    assert _dedupe_mounts(once) == once


@needs_sandbox
def test_the_old_mount_order_really_fails_on_a_read_only_parent():
    """The defect this module exists for, demonstrated rather than described."""
    if not Path("/usr/bin/env").is_file():
        pytest.skip("NOT_RUN: /usr/bin/env is not a regular file on this host")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        root.mkdir()
        steps = ["mount --make-rprivate /", f"mount -t tmpfs -o size=8m,nosuid,nodev tmpfs {root}"]
        steps.append(_mount(Path("/usr"), root, readonly=True))
        steps.append(_mount(Path("/usr/bin/env"), root, readonly=True))
        proc = subprocess.run(["unshare", "-rmnpf", "sh", "-c", " && ".join(steps)],
                              capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stderr
    assert "Read-only file system" in proc.stderr, proc.stderr


@needs_sandbox
def test_a_browser_under_a_system_directory_runs_inside_the_sandbox():
    """The runner's arrangement end to end: a read-only mount nested in /usr."""
    iso = probe_isolation()
    assert iso.node, "a sandbox host must resolve an interpreter"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        cmd = wrap(["/bin/echo", "nested-mount-ok"], cwd=work, home=work, node=iso.node,
                   timeout_s=60, readonly_paths=(Path("/usr/bin/env"),))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # The command itself must have run: a mount failure exits non-zero with
        # the shell's own message instead of the program's output.
        assert proc.returncode == 0, proc.stderr[-600:]
        assert proc.stdout.strip() == "nested-mount-ok", proc.stdout
        assert "Read-only file system" not in proc.stderr, proc.stderr


def test_a_missing_mount_source_is_refused_before_anything_else_happens():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            _mount(Path(tmp) / "does-not-exist", Path(tmp), readonly=True)


def test_wrap_still_refuses_a_network_enabled_command():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            wrap(["/bin/true"], cwd=Path(tmp), home=Path(tmp), node=shutil.which("node") or "/bin/sh",
                 timeout_s=5, network=True)
