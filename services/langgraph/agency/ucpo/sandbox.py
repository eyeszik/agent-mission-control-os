"""Isolation for untrusted generated source. A temporary directory is not isolation.

``probe_isolation`` proves, by running them, the properties the build relies on:

* a user + mount + network namespace (``unshare -rmn``) with no network interface but loopback;
* the repository re-mounted read-only inside that namespace (so ``node_modules`` is usable but not writable);
* a scrubbed environment (``env -i``) and ``prlimit`` resource caps;
* a wall-clock ``timeout``.

If any property cannot be demonstrated the result is ``available=False`` and callers must
return ``BLOCKED_ISOLATION`` without executing generated code.
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
# Resource caps applied to every sandboxed process. Address-space caps break V8, so memory is bounded by time instead.
LIMITS = {"fsize_bytes": 256 * 1024 * 1024, "nofile": 4096, "core": 0}


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


def wrap(command: list[str], *, cwd: Path, home: Path, node: str, timeout_s: int, network: bool = False,
         extra_env: Optional[dict[str, str]] = None) -> list[str]:
    """The argv that runs ``command`` in the sandbox: new namespaces, read-only repo, scrubbed env, caps, timeout."""
    env = {"PATH": f"{Path(node).parent}:/usr/bin:/bin", "HOME": str(home), "NEXT_TELEMETRY_DISABLED": "1",
           "CI": "1", "LANG": "C.UTF-8", **(extra_env or {})}
    inner = " ".join([
        f"mount --bind {shlex.quote(str(REPO_ROOT))} {shlex.quote(str(REPO_ROOT))}",
        f"&& mount -o remount,bind,ro {shlex.quote(str(REPO_ROOT))}",
        f"&& cd {shlex.quote(str(cwd))}",
        "&& exec env -i", *(shlex.quote(f"{k}={v}") for k, v in sorted(env.items())),
        "prlimit", f"--fsize={LIMITS['fsize_bytes']}", f"--nofile={LIMITS['nofile']}", f"--core={LIMITS['core']}", "--",
        "timeout", "--kill-after=5", str(timeout_s), *(shlex.quote(c) for c in command),
    ])
    return ["unshare", "-rm" + ("" if network else "n"), "sh", "-c", inner]


def probe_isolation() -> Isolation:
    reasons: list[str] = []
    facts: dict = {}
    for tool in ("unshare", "mount", "prlimit", "timeout", "env", "sh"):
        if not _which(tool):
            reasons.append(f"{tool} not found")
    node = _which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)
    if not node:
        reasons.append("node not found")
    if not (WEB_NODE_MODULES / "next" / "package.json").exists():
        reasons.append("apps/web/node_modules is not installed (run pnpm install --frozen-lockfile)")
    if reasons:
        return Isolation(False, tuple(reasons), facts, node)
    with tempfile.TemporaryDirectory(prefix="amc-ucpo-probe-") as tmp:
        work = Path(tmp)
        script = ("ip -o link 2>/dev/null | wc -l > links; "
                  "(touch {repo}/.amc-ro-probe 2>/dev/null && echo writable || echo readonly) > repo; "
                  "env | sort > env; echo ok > ok").format(repo=shlex.quote(str(REPO_ROOT)))
        argv = wrap(["sh", "-c", script], cwd=work, home=work, node=node, timeout_s=20)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Isolation(False, (f"sandbox probe failed to run: {exc}",), facts, node)
        if proc.returncode != 0 or not (work / "ok").exists():
            return Isolation(False, (f"sandbox probe exited {proc.returncode}: {proc.stderr.strip()[-300:]}",), facts, node)
        repo_state = (work / "repo").read_text().strip()
        env_keys = sorted(line.split("=", 1)[0] for line in (work / "env").read_text().splitlines() if "=" in line)
        stray = REPO_ROOT / ".amc-ro-probe"
        if stray.exists():
            stray.unlink()
        facts = {"network_namespace": True, "repo_mount": repo_state, "env_keys": env_keys,
                 "limits": dict(LIMITS), "node": node}
        if repo_state != "readonly":
            reasons.append("repository is writable inside the sandbox")
        allowed = {"PATH", "HOME", "NEXT_TELEMETRY_DISABLED", "CI", "LANG", "PWD", "SHLVL", "_", "OLDPWD"}
        if set(env_keys) - allowed:
            reasons.append(f"environment not scrubbed: {sorted(set(env_keys) - allowed)}")
        # Network: a connection to a routable address must fail inside the namespace.
        net = subprocess.run(wrap([node, "-e", "require('net').connect(443,'1.1.1.1').on('connect',()=>{console.log('NET');process.exit(0)})"
                                   ".on('error',()=>process.exit(3))"], cwd=work, home=work, node=node, timeout_s=10),
                             capture_output=True, text=True, timeout=30)
        facts["network_probe_exit"] = net.returncode
        if "NET" in net.stdout:
            reasons.append("network reachable inside the sandbox")
    return Isolation(not reasons, tuple(reasons), facts, node)


__all__ = ["Isolation", "LIMITS", "REPO_ROOT", "WEB_NODE_MODULES", "probe_isolation", "wrap"]
