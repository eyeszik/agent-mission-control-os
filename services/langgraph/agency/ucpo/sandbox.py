"""Fail-closed isolation for UCPO's untrusted generated source.

A read-only repository and ``env -i`` are not a confidentiality boundary: the
old namespace left the host home and other projects readable. The build now
runs inside a new user, mount, PID and network namespace *and* a minimal
chroot. Only system runtime directories, the installed web dependencies and
explicitly named scratch/input paths are mounted; the rest of the repository,
home, host /tmp and host sockets are absent. Only the new PID namespace's /proc is mounted. Capabilities are dropped
and no-new-privileges is set before executing the command.

``probe_isolation`` actually tests this boundary, including a synthetic host
canary and a network connection. Any unsupported operation blocks execution.
This is not a general-purpose hostile multi-tenant container (there is no
seccomp/cgroup resource isolation); it is a restricted local build boundary.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_NODE_MODULES = REPO_ROOT / "apps" / "web" / "node_modules"
ROOT_NODE_MODULES = REPO_ROOT / "node_modules"
LIMITS = {"fsize_bytes": 256 * 1024 * 1024, "nofile": 4096, "nproc": 128, "core": 0}
_SYSTEM_DIRS = ("/usr", "/bin", "/lib", "/lib64", "/etc/fonts")
# /dev/shm is required, not optional: Chromium backs the print-to-PDF pipeline
# with shared memory, and Page.printToPDF fails with a bare "Printing failed"
# when there is none. The mount is a fresh tmpfs owned by this namespace, never
# the host's, so no other process can observe or tamper with the pages.
_DEVICES = ("/dev/null", "/dev/zero", "/dev/urandom", "/dev/shm")


@dataclass(frozen=True)
class Isolation:
    available: bool
    reasons: tuple[str, ...]
    facts: dict = field(default_factory=dict)
    node: Optional[str] = None

    def describe(self) -> dict:
        return {"available": self.available, "reasons": list(self.reasons), **self.facts}


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


# The helpers the sandbox exec chain needs. Each is resolved on the host at run time
# and required to exist inside the chroot; hardcoding one distribution's layout made
# the whole sandbox report "not found" on a runner that keeps chroot elsewhere.
_REQUIRED_TOOLS = ("chroot", "setpriv", "env", "prlimit", "timeout", "sh")


_SBIN_DIRS = ("/usr/sbin", "/sbin", "/usr/local/sbin")


def _resolve_tool(name: str) -> Optional[str]:
    """Locate a helper on PATH or in the sbin directories.

    chroot, prlimit and friends live in /usr/sbin on Debian-family hosts, which is not
    on PATH for an unprivileged user. Searching only PATH reported them missing and
    disabled the sandbox on a host that supports it.
    """
    found = _which(name)
    if found:
        return found
    for directory in _SBIN_DIRS:
        candidate = Path(directory) / name
        if candidate.is_file():
            return str(candidate)
    return None


def _tool(name: str, fallback: str) -> str:
    return _resolve_tool(name) or (fallback if Path(fallback).is_file() else fallback)


def _mount(path: Path, root: Path, *, readonly: bool) -> str:
    """Bind one exact path at its original absolute name, never its parent."""
    if not path.is_absolute() or not path.exists():
        raise ValueError(f"sandbox mount path is missing or not absolute: {path}")
    target = root / str(path).lstrip("/")
    src, dst = shlex.quote(str(path)), shlex.quote(str(target))
    prepare = f"mkdir -p {dst}" if path.is_dir() else f"mkdir -p {shlex.quote(str(target.parent))} && : > {dst}"
    mount = f"mount --bind {src} {dst}"
    remount = f" && mount -o remount,bind,ro,nosuid,nodev {dst}" if readonly else ""
    return f"{prepare} && {mount}{remount}"


def _dedupe_mounts(paths: list[Path]) -> list[Path]:
    """Drop a mount whose target already sits inside an earlier one.

    ``_mount`` creates the target with ``mkdir -p`` and then ``: > dst`` for a
    file, so mounting ``/usr/bin/chromium`` after ``/usr`` has been bound
    read-only writes into the read-only bind and fails with EACCES. That is not
    hypothetical: on GitHub's runners Playwright's bundled browser is reachable
    as ``/usr/bin/chromium``, and the redundant mount made every AVIC render
    exit 2. The browser is already inside ``/usr`` by then, so the mount adds
    nothing. Keep the first (widest) path; a narrower one that is genuinely
    outside every other mount is still mounted.
    """
    kept: list[Path] = []
    for path in paths:
        resolved = Path(path)
        if any(resolved == prior or resolved.is_relative_to(prior) for prior in kept):
            continue
        kept.append(resolved)
    return kept


def wrap(command: list[str], *, cwd: Path, home: Path, node: str, timeout_s: int, network: bool = False,
         extra_env: Optional[dict[str, str]] = None, readonly_paths: tuple[Path, ...] = (),
         writable_paths: tuple[Path, ...] = ()) -> list[str]:
    """Build an argv for one isolated process. Paths are provided by trusted UCPO code only."""
    if network:
        raise ValueError("UCPO does not allow network-enabled execution")
    cwd, home = Path(cwd).absolute(), Path(home).absolute()
    root = home / ".amc-sandbox-root"
    root.mkdir(parents=True, exist_ok=True)
    # Chromium prints to PDF through a private temp directory it must be able to
    # write. In this chroot the only writable paths are `home` and `cwd`, both
    # under the caller's scratch directory, so HOME alone is not enough: the
    # browser also honours TMPDIR for the print spool. Both are pointed at a
    # directory that exists inside the namespace and is created below; when it
    # did not, Page.printToPDF failed and the brand book silently had no PDF.
    # TMPDIR must be the in-namespace path, not the host path, because the
    # chroot sees only the bind-mounted tree.
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
           "NEXT_TELEMETRY_DISABLED": "1", "CI": "1", "LANG": "C.UTF-8", **(extra_env or {})}
    env.setdefault("XDG_CACHE_HOME", str(home / ".cache"))
    readonly = [Path(p) for p in _SYSTEM_DIRS if Path(p).exists()]
    # The interpreter is often installed outside the system directories -- GitHub's
    # runners put it under /opt/hostedtoolcache -- and the chroot only contains what is
    # bind-mounted here. Without this the interpreter a caller names is simply absent
    # inside the sandbox, every command exits 127, and the boundary probe reports
    # "network isolation not demonstrated" for a host that is in fact fine.
    # Mount it before the system directories so its parent is still writable.
    node_path = Path(node)
    if node_path.is_absolute() and node_path.is_file() and not any(
            node_path.is_relative_to(Path(system)) for system in _SYSTEM_DIRS):
        readonly.insert(0, node_path)
    readonly += [ROOT_NODE_MODULES, WEB_NODE_MODULES, *readonly_paths]
    readonly = _dedupe_mounts(readonly)
    writable = list(dict.fromkeys((cwd, home, *writable_paths)))
    steps = ["mount --make-rprivate /", f"mount -t tmpfs -o size=32m,nosuid,nodev tmpfs {shlex.quote(str(root))}"]
    steps += [_mount(Path(p), root, readonly=True) for p in readonly]
    # Only these explicit, caller-owned directories are writable. No host /tmp or home is mounted.
    steps += [_mount(Path(p), root, readonly=False) for p in writable]
    # /dev/shm may not exist on a minimal host; create the mount point so the
    # tmpfs can be mounted at the canonical path the browser looks for.
    if Path("/dev/shm").exists():
        steps.append(f"mkdir -p {shlex.quote(str(root / 'dev/shm'))} && mount -t tmpfs -o nosuid,nodev,size=256m tmpfs {shlex.quote(str(root / 'dev/shm'))}")
    steps += [_mount(Path(p), root, readonly=False) for p in _DEVICES
              if p != "/dev/shm" and Path(p).exists()]
    steps.append(f"mkdir -p {shlex.quote(str(root / 'proc'))} && mount -t proc -o nosuid,nodev,noexec proc {shlex.quote(str(root / 'proc'))}")
    # Create the browser's cache/temp directories after the mounts (they live in
    # the writable home) so a renderer never has to discover they are missing.
    for name in (".cache", "tmp"):
        steps.append(f"mkdir -p {shlex.quote(str(home / name))}")
    env_args = " ".join(shlex.quote(f"{k}={v}") for k, v in sorted(env.items()))
    cmd_args = " ".join(shlex.quote(str(c)) for c in command)
    enter_cwd = shlex.quote('cd ' + shlex.quote(str(cwd)) + ' && exec "$@"')
    chroot = _tool("chroot", "/usr/sbin/chroot")
    setpriv = _tool("setpriv", "/usr/bin/setpriv")
    env_bin = _tool("env", "/usr/bin/env")
    prlimit = _tool("prlimit", "/usr/bin/prlimit")
    timeout_bin = _tool("timeout", "/usr/bin/timeout")
    sh_bin = _tool("sh", "/bin/sh")
    child = (f"exec {shlex.quote(chroot)} {shlex.quote(str(root))} {shlex.quote(setpriv)} --no-new-privs "
             f"--bounding-set=-all --inh-caps=-all --ambient-caps=-all {shlex.quote(env_bin)} -i {env_args} "
             f"{shlex.quote(prlimit)} --fsize={LIMITS['fsize_bytes']} --nofile={LIMITS['nofile']} "
             f"--nproc={LIMITS['nproc']} --core=0 -- {shlex.quote(timeout_bin)} --kill-after=5 {timeout_s} "
             f"{shlex.quote(sh_bin)} -c {enter_cwd} sandbox {cmd_args}")
    steps.append(child)
    return ["unshare", "-rmnpf", "sh", "-c", " && ".join(steps)]


def probe_isolation() -> Isolation:
    reasons: list[str] = []
    facts: dict = {}
    for tool in ("unshare", "mount", "prlimit", "timeout", "env", "sh", "setpriv"):
        if not _which(tool):
            reasons.append(f"{tool} not found")
    for tool in _REQUIRED_TOOLS:
        if not _resolve_tool(tool):
            reasons.append(f"{tool} not found (the sandbox exec chain needs it)")
    node = _which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)
    if not node:
        reasons.append("node not found")
    if not (WEB_NODE_MODULES / "next" / "package.json").exists():
        reasons.append("apps/web/node_modules is not installed (run pnpm install --frozen-lockfile)")
    if reasons:
        return Isolation(False, tuple(reasons), facts, node)
    with tempfile.TemporaryDirectory(prefix="amc-ucpo-probe-") as tmp, tempfile.TemporaryDirectory(prefix="amc-ucpo-canary-") as outside:
        work = Path(tmp)
        canary = Path(outside) / "host-canary"
        canary.write_text("synthetic isolation canary", encoding="utf-8")
        script = (f"test ! -e {shlex.quote(str(canary))} && test ! -e {shlex.quote(str(REPO_ROOT / 'README.md'))} "
                  f"&& test -r {shlex.quote(str(WEB_NODE_MODULES / 'next' / 'package.json'))} "
                  f"&& test ! -e /proc/1/root{shlex.quote(str(canary))} "
                  "&& test -e /proc/self/exe && echo hidden > boundary && env | sort > env && echo ok > ok")
        try:
            proc = subprocess.run(wrap(["sh", "-c", script], cwd=work, home=work, node=node, timeout_s=20),
                                  capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return Isolation(False, (f"sandbox probe failed to run: {exc}",), facts, node)
        if proc.returncode != 0 or not (work / "ok").exists():
            return Isolation(False, (f"sandbox boundary probe exited {proc.returncode}: {proc.stderr.strip()[-300:]}",), facts, node)
        env_keys = sorted(line.split("=", 1)[0] for line in (work / "env").read_text().splitlines() if "=" in line)
        facts = {"network_namespace": True, "pid_namespace": True, "filesystem": "minimal chroot",
                 "host_canary": "hidden", "repository_source": "hidden", "capabilities": "dropped",
                 "env_keys": env_keys, "limits": dict(LIMITS), "node": node,
                 "seccomp": False, "cgroup_quota": False}
        # The allowlist is the contract for what a sandboxed process may see.
        # XDG_CACHE_HOME is added deliberately: it points at the writable home
        # inside the namespace and is what lets Chromium print to PDF there.
        # Anything not listed here is a leak and fails the probe, so adding a
        # name is a security decision, never a convenience.
        allowed = {"PATH", "HOME", "TMPDIR", "XDG_CACHE_HOME", "NEXT_TELEMETRY_DISABLED", "CI", "LANG",
                   "PWD", "SHLVL", "_", "OLDPWD"}
        if set(env_keys) - allowed:
            reasons.append(f"environment not scrubbed: {sorted(set(env_keys) - allowed)}")
        try:
            net = subprocess.run(wrap([node, "-e", "require('net').connect(443,'1.1.1.1').on('connect',()=>process.exit(0))"
                                       ".on('error',()=>process.exit(3))"], cwd=work, home=work, node=node, timeout_s=10),
                                 capture_output=True, text=True, timeout=30)
            facts["network_probe_exit"] = net.returncode
            if net.returncode != 3:
                reasons.append(f"network isolation not demonstrated (probe exit {net.returncode})")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            reasons.append(f"network isolation probe failed: {type(exc).__name__}")
    return Isolation(not reasons, tuple(reasons), facts, node)


__all__ = ["Isolation", "LIMITS", "REPO_ROOT", "WEB_NODE_MODULES", "probe_isolation", "wrap"]
