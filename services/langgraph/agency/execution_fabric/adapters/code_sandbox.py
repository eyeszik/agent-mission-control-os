"""Code sandbox: validate a Python patch in an isolated scratch copy.

What it does, exactly:

* builds a fresh temporary directory and writes only the supplied base files
  into it (it never touches the repository working tree, and the patch is
  never applied to it);
* accepts relative POSIX paths only: absolute paths, ``..``/``.`` segments,
  backslashes, NUL bytes and anything resolving outside the scratch root are
  rejected before a byte is written;
* accepts Python sources only, and records an AST structural diff per file; a
  patch that does not parse is rejected;
* runs commands from a closed allowlist (``py_compile``) with a scrubbed
  environment (no inherited secrets or proxies), resource limits (address
  space, CPU, open files, file size) and a timeout, inside a Linux user, mount
  and network namespace (``unshare -rmn``). Inside the mount namespace the root
  filesystem is remounted read-only (OWASP ASI05), so a patch-validation command
  cannot write to the host, the repository or the scratch copy. The sandbox
  refuses to run when that namespace cannot be created (fail closed).

What it does not do: no seccomp profile and no socket proxy. Isolation is
reported as observed, never assumed.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from ..verifiers import Verdict, ast_structural_diff

_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}$")
ALLOWED_SUFFIXES = (".py",)
MAX_FILES = 50
MAX_FILE_BYTES = 200_000
# ``py_compile`` writes bytecode into the source tree, which the read-only root forbids. This check
# performs the same syntax compilation in memory and writes nothing.
_COMPILE_ONLY = "import sys\nwith open(sys.argv[-1], 'rb') as handle:\n    compile(handle.read(), sys.argv[-1], 'exec')\n"
COMMAND_ALLOWLIST = {"py_compile": ("-I", "-c", _COMPILE_ONLY)}
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}


class SandboxViolation(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def safe_relpath(path: str) -> PurePosixPath:
    if not isinstance(path, str) or "\x00" in path or "\\" in path or not _SAFE.match(path):
        raise SandboxViolation("PATH_REJECTED", repr(path))
    pure = PurePosixPath(path)
    # Check the raw segments: PurePosixPath silently drops "." and empty ones.
    if pure.is_absolute() or any(seg in {"", ".", ".."} for seg in path.split("/")):
        raise SandboxViolation("PATH_TRAVERSAL", path)
    if pure.suffix not in ALLOWED_SUFFIXES:
        raise SandboxViolation("SUFFIX_REJECTED", path)
    return pure


@functools.lru_cache(maxsize=1)
def network_namespace_available() -> bool:
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    try:
        return subprocess.run([unshare, "-rn", "true"], capture_output=True, timeout=5, env=_ENV).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@functools.lru_cache(maxsize=1)
def mount_namespace_available() -> bool:
    """True when a user+mount+network namespace can be created and its root remounted read-only."""
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    probe = "mount --make-rprivate / && mount -o remount,bind,ro /"
    try:
        return subprocess.run([unshare, "-rmn", "sh", "-c", probe], capture_output=True, timeout=5,
                              env=_ENV).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# The shell step runs inside the new mount namespace. It makes the namespace private, remounts the root
# read-only, then replaces itself with the requested command. $0 is the interpreter, $@ its arguments.
_READONLY_ROOT_STEP = 'mount --make-rprivate / && mount -o remount,bind,ro / && exec "$0" "$@"'


def isolated_argv(inner: list[str]) -> list[str]:
    """The argv that runs ``inner`` in a fresh user, mount and network namespace with a read-only root."""
    unshare = shutil.which("unshare") or "unshare"
    return [unshare, "-rmn", "sh", "-c", _READONLY_ROOT_STEP, *inner]


# Limits are applied by a tiny exec shim in the child rather than with
# ``preexec_fn``, which is unsafe when the caller runs skills on threads.
_LIMITER = (
    "import os, resource, sys\n"
    "resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))\n"
    "resource.setrlimit(resource.RLIMIT_CPU, (20, 20))\n"
    "resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))\n"
    "resource.setrlimit(resource.RLIMIT_FSIZE, (10 << 20, 10 << 20))\n"
    "os.execv(sys.argv[1], sys.argv[1:])\n"
)


def _write(root: Path, rel: PurePosixPath, text: str) -> None:
    target = (root / rel).resolve()
    if root.resolve() not in target.parents:
        raise SandboxViolation("PATH_ESCAPE", str(rel))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise SandboxViolation("SYMLINK_REJECTED", str(rel))
    target.write_text(text, encoding="utf-8")


def run_patch(base: dict[str, str], patch: dict[str, str], commands: list[list[str]], *, timeout: float = 30.0) -> dict[str, Any]:
    if len(base) + len(patch) > MAX_FILES:
        raise SandboxViolation("TOO_MANY_FILES", str(len(base) + len(patch)))
    checked_base = {safe_relpath(p): t for p, t in base.items()}
    checked_patch = {safe_relpath(p): t for p, t in patch.items()}
    for text in (*checked_base.values(), *checked_patch.values()):
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise SandboxViolation("FILE_REJECTED", "file content missing or too large")
    if not network_namespace_available():
        raise SandboxViolation("SANDBOX_UNAVAILABLE", "no network namespace can be created on this host")
    if not mount_namespace_available():
        raise SandboxViolation("SANDBOX_UNAVAILABLE", "no read-only mount namespace can be created on this host")

    diffs = {}
    for rel, text in sorted(checked_patch.items(), key=lambda kv: str(kv[0])):
        try:
            diffs[str(rel)] = ast_structural_diff(checked_base.get(rel, ""), text)
        except SyntaxError as exc:
            raise SandboxViolation("PATCH_NOT_PARSEABLE", f"{rel}: {exc.msg} (line {exc.lineno})") from exc

    results = []
    with tempfile.TemporaryDirectory(prefix="amc-sandbox-") as tmp:
        root = Path(tmp)
        for rel, text in {**checked_base, **checked_patch}.items():
            _write(root, rel, text)
        for command in commands:
            if not command or command[0] not in COMMAND_ALLOWLIST or len(command) != 2:
                raise SandboxViolation("COMMAND_REJECTED", repr(command))
            target = safe_relpath(command[1])
            argv = isolated_argv([sys.executable, "-I", "-c", _LIMITER,
                                  sys.executable, *COMMAND_ALLOWLIST[command[0]], str(target)])
            try:
                proc = subprocess.run(argv, cwd=root, env=dict(_ENV), capture_output=True, text=True, timeout=timeout)
                results.append({"command": command[0], "target": str(target), "returncode": proc.returncode,
                                "stderr_tail": proc.stderr[-2000:]})
            except subprocess.TimeoutExpired:
                results.append({"command": command[0], "target": str(target), "returncode": None, "stderr_tail": "TIMEOUT"})
    return {
        "kind": "code_patch_validation",
        "diffs": diffs,
        "commands": results,
        "passed": all(r["returncode"] == 0 for r in results),
        "applied_to_repository": False,
        "isolation": {
            "filesystem": "FRESH_TEMP_COPY",
            "root_mount": "READ_ONLY_IN_MOUNT_NAMESPACE",
            "network": "LINUX_NETNS",
            "environment": "SCRUBBED",
            "resource_limits": ["RLIMIT_AS=1GiB", "RLIMIT_CPU=20s", "RLIMIT_NOFILE=64", "RLIMIT_FSIZE=10MiB"],
            "readonly_overlay": False,
            "seccomp": False,
            "socket_proxy": False,
        },
    }


def code_patch_sandbox(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("inputs", {})
    report = run_patch(dict(inputs.get("base") or {}), dict(inputs.get("patch") or {}), list(inputs.get("commands") or []))
    return {"content": json.dumps(report, sort_keys=True, indent=2), "mime_type": "application/json", "subtype": "code_patch"}


def validate_commands_passed(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    report = json.loads(output["content"])
    ok = report.get("passed") is True and report.get("applied_to_repository") is False
    return Verdict("sandbox_commands_passed", ok,
                   "all allowlisted commands exited 0" if ok else f"command failures: {[r for r in report.get('commands', []) if r.get('returncode') != 0]}")


# Exposed for tests: the scrubbed environment never contains host secrets.
SANDBOX_ENV = dict(_ENV)
