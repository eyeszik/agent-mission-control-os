"""Local, fail-closed repository patch checks in a narrow Linux namespace.

This is a deterministic synthetic-fixture executor, not a general model-code runner.
It snapshots only caller-supplied regular text files, applies a non-empty patch
in a disposable root, and invokes only the stdlib ``unittest`` command. There is
no host fallback, shell, network, Git metadata, home directory, provider secret,
MCP process, or GitHub operation in the sandbox.

The kernel is shared. Seccomp and writable cgroup limits are unavailable in
this environment, so model-generated repository execution remains blocked even
when the low-risk fixture probe succeeds. No PR, deployment, or other external
write is performed here.
"""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from services.langgraph.agency.execution.canonical import canonical_hash

from .context import verify_context_bytes
from .contracts import (
    CheckRecord,
    CheckSpec,
    CheckStatus,
    ContextRecord,
    ExecutionLimits,
    ExecutionResultRecord,
    IsolationReceipt,
    PlanRecord,
    ReviewStatus,
    safe_repo_path,
)

_TMPFS_BYTES = 16_000_000
_TMPFS_INODES = 4096
_CONTROL_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
_SANDBOX_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/tmp/home",
    "TMPDIR": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "AMC_SANDBOX_MODE": "engineering-local-fixture",
}


class SandboxViolation(ValueError):
    """Input or policy failure before untrusted code is started."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class _ProcessResult:
    exit_code: int | None
    output_hash: str | None
    output_bytes: int
    output_tail: bytes
    started_at: str
    finished_at: str
    timed_out: bool = False
    output_limited: bool = False
    launch_error: str | None = None


# This helper runs only after ``unshare`` creates user/mount/network/PID
# namespaces. It mounts a minimal read-only root, chroots, drops capabilities,
# applies rlimits, and execs exactly the argv selected by the fixed runner.
_BOOTSTRAP = r'''import ctypes, json, os, resource, subprocess, sys
root, command, env, limits, cwd = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3]), json.loads(sys.argv[4]), sys.argv[5]
mount = "/usr/bin/mount"
def run(args):
    proc = subprocess.run([mount, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LANG": "C"}, timeout=5)
    if proc.returncode:
        raise RuntimeError("namespace mount setup failed")
run(["--make-rprivate", "/"])
run(["--bind", root, root])
run(["-o", "remount,bind,ro,nosuid", root])
run(["--bind", "/usr", root + "/usr"])
run(["-o", "remount,bind,ro,nosuid", "/usr", root + "/usr"])
run(["-t", "tmpfs", "-o", "size=" + str(limits["disk_bytes"]) + ",nr_inodes=" + str(limits["disk_inodes"]) + ",nosuid,nodev,noexec", "tmpfs", root + "/tmp"])
run(["-t", "proc", "-o", "nosuid,nodev,noexec,hidepid=2", "proc", root + "/proc"])
for device in ("null", "zero", "urandom"):
    run(["--bind", "/dev/" + device, root + "/dev/" + device])
os.chdir(root)
os.chroot(".")
os.chdir("/workspace" + (("/" + cwd) if cwd else ""))
os.mkdir("/tmp/home", 0o700)
os.umask(0o077)
resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"], limits["memory_bytes"]))
resource.setrlimit(resource.RLIMIT_CPU, (limits["cpu_seconds"], limits["cpu_seconds"]))
resource.setrlimit(resource.RLIMIT_NPROC, (limits["processes"], limits["processes"]))
resource.setrlimit(resource.RLIMIT_FSIZE, (limits["output_bytes"], limits["output_bytes"]))
resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
for fd in range(3, 1024):
    try: os.close(fd)
    except OSError: pass
libc = ctypes.CDLL(None, use_errno=True)
class CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
class CapData(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
header = CapHeader(0x20080522, 0)
data = (CapData * 2)(CapData(0, 0, 0), CapData(0, 0, 0))
if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
    raise OSError(ctypes.get_errno(), "capability drop failed")
if libc.prctl(38, 1, 0, 0, 0) != 0:
    raise OSError(ctypes.get_errno(), "no_new_privs could not be set")
os.execve(command[0], command, env)
'''

_PROBE_CODE = r'''import json, os, platform, resource, socket, sys
expected_userns, expected_mntns, expected_netns, expected_pidns = map(int, sys.argv[1:])
interfaces = [name for _, name in socket.if_nameindex() if name != "lo"]
routes = [line for line in open("/proc/net/route", encoding="ascii").read().splitlines()[1:] if line.strip()]
nproc_limit = resource.getrlimit(resource.RLIMIT_NPROC)[0]
children = []
for _ in range(min(int(nproc_limit) + 2, 34)):
    try:
        child = os.fork()
    except OSError:
        break
    if child == 0:
        os._exit(0)
    children.append(child)
for child in children:
    os.waitpid(child, 0)
tmp_stat = os.statvfs("/tmp")
facts = {"pid": os.getpid(), "python_version": sys.version, "python_implementation": sys.implementation.name,
         "machine": platform.machine(), "kernel": os.uname().release,
         "tmp_total_bytes": tmp_stat.f_blocks * tmp_stat.f_frsize, "tmp_total_inodes": tmp_stat.f_files,
         "env": dict(os.environ), "home_entries": os.listdir("/home"),
         "root_entries": sorted(os.listdir("/")), "proc_pid_1": os.path.isdir("/proc/1"),
         "user_namespace_distinct": os.stat("/proc/self/ns/user").st_ino != expected_userns,
         "mount_namespace_distinct": os.stat("/proc/self/ns/mnt").st_ino != expected_mntns,
         "pid_namespace_distinct": os.stat("/proc/self/ns/pid").st_ino != expected_pidns,
         "workspace_read_only": False, "usr_read_only": False, "etc_read_only": False,
         "tmp_writable": False, "network_namespace_distinct": os.stat("/proc/self/ns/net").st_ino != expected_netns,
         "network_interfaces": interfaces, "network_routes": routes, "nproc_child_count": len(children),
         "limits": {"as": resource.getrlimit(resource.RLIMIT_AS), "cpu": resource.getrlimit(resource.RLIMIT_CPU),
                    "nproc": resource.getrlimit(resource.RLIMIT_NPROC), "fsize": resource.getrlimit(resource.RLIMIT_FSIZE),
                    "nofile": resource.getrlimit(resource.RLIMIT_NOFILE), "core": resource.getrlimit(resource.RLIMIT_CORE)}}
status = dict(line.split(":", 1) for line in open("/proc/self/status", encoding="ascii") if ":" in line)
facts["no_new_privs"] = status.get("NoNewPrivs", "").strip() == "1"
facts["capabilities_dropped"] = int(status.get("CapEff", "0").strip() or "0", 16) == 0
for path, key in (("/workspace/probe.txt", "workspace_read_only"),
                  ("/usr/amc-write-probe", "usr_read_only"), ("/etc/amc-write-probe", "etc_read_only"),
                  ("/root/amc-write-probe", "root_read_only")):
    try:
        open(path, "w", encoding="ascii").write("changed")
    except OSError:
        facts[key] = True
try:
    open("/tmp/probe", "w").write("ok")
    facts["tmp_writable"] = open("/tmp/probe").read() == "ok"
except OSError:
    pass
print(json.dumps(facts, sort_keys=True))
'''

_RUNNER_RESULT_PREFIX = b"@@AMC_ENGINEERING_RESULT@@"
_UNITTEST_CODE = r'''import json, os, sys, traceback, unittest
sys.path.insert(0, os.getcwd())
modules = sys.argv[1:]
count = 0
result = None
try:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for module in modules:
        suite.addTests(loader.loadTestsFromName(module))
    count = suite.countTestCases()
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    passed = result.wasSuccessful() and count > 0 and result.testsRun > 0
except BaseException:
    traceback.print_exc(file=sys.stdout)
    passed = False
payload = {"passed": bool(passed), "count": int(count),
           "tests_run": int(result.testsRun) if result is not None else 0}
print("@@AMC_ENGINEERING_RESULT@@" + json.dumps(payload, sort_keys=True), flush=True)
sys.exit(0 if passed else 1)
'''
_RUNNER_SHA256 = hashlib.sha256(_UNITTEST_CODE.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_no_ancestor_files(files: Mapping[str, bytes]) -> None:
    paths = set(files)
    for raw_path in paths:
        for parent in PurePosixPath(raw_path).parents:
            if parent.as_posix() != "." and parent.as_posix() in paths:
                raise SandboxViolation("PATH_ANCESTOR_CONFLICT", raw_path)


def _safe_files(files: Mapping[str, str | bytes], limits: ExecutionLimits) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or not files:
        raise SandboxViolation("EMPTY_CONTEXT", "a non-empty base file map is required")
    normalized: dict[str, bytes] = {}
    total = 0
    for raw_path, raw_content in files.items():
        path = safe_repo_path(raw_path)
        if path in normalized:
            raise SandboxViolation("DUPLICATE_PATH", path)
        if isinstance(raw_content, str):
            data = raw_content.encode("utf-8")
        elif isinstance(raw_content, bytes):
            data = raw_content
        else:
            raise SandboxViolation("CONTENT_TYPE_REJECTED", path)
        if b"\x00" in data:
            raise SandboxViolation("BINARY_CONTENT_REJECTED", path)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SandboxViolation("NON_UTF8_CONTENT_REJECTED", path) from exc
        if len(data) > limits.max_file_bytes:
            raise SandboxViolation("FILE_LIMIT_EXCEEDED", path)
        total += len(data)
        if total > limits.max_workspace_bytes:
            raise SandboxViolation("WORKSPACE_LIMIT_EXCEEDED", "base files exceed byte budget")
        normalized[path] = data
    _assert_no_ancestor_files(normalized)
    if len(normalized) > limits.max_files:
        raise SandboxViolation("FILE_COUNT_LIMIT_EXCEEDED", str(len(normalized)))
    return normalized


def _tree_hash(files: Mapping[str, bytes]) -> str:
    manifest = [{"path": path, "blob_hash": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
                for path, data in sorted(files.items(), key=lambda item: item[0].encode("utf-8"))]
    return canonical_hash(manifest)


def _patch_hash(patch: Mapping[str, bytes], deletions: tuple[str, ...]) -> str:
    return canonical_hash({
        "files": [{"path": path, "blob_hash": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
                  for path, data in sorted(patch.items(), key=lambda item: item[0].encode("utf-8"))],
        "deletions": sorted(deletions),
    })


def _module_paths(module: str) -> tuple[str, ...]:
    parts = module.split(".")
    base = "/".join(parts)
    return tuple("/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts))) + (base + ".py",)


def _within_scope(path: str, scopes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in scopes)


def _validate_plan_inputs(base: dict[str, bytes], patch: dict[str, bytes], deletions: tuple[str, ...],
                          plan: PlanRecord) -> tuple[dict[str, bytes], tuple[str, ...]]:
    if plan.base_tree_hash != _tree_hash(base):
        raise SandboxViolation("BASE_TREE_MISMATCH", "plan does not bind the supplied base snapshot")
    if not patch and not deletions:
        raise SandboxViolation("EMPTY_PATCH", "patch must contain at least one change")
    changed = set(patch) | set(deletions)
    if len(changed) != len(patch) + len(deletions):
        raise SandboxViolation("PATCH_CONFLICT", "a path is both changed and deleted")
    if any(path not in base for path in deletions):
        raise SandboxViolation("DELETE_TARGET_MISSING", "patch deletes a path not present in the base")
    test_paths = {path for check in plan.checks for module in check.argv[5:] for path in _module_paths(module)}
    if changed & test_paths:
        raise SandboxViolation("TEST_EVIDENCE_MODIFIED", "checks must use test modules unchanged by the patch")
    if any(not _within_scope(path, plan.allowed_paths) for path in changed):
        raise SandboxViolation("PATH_OUT_OF_SCOPE", "patch modifies a path outside the plan")
    for path in test_paths:
        if path.endswith("/__init__.py") and path not in base:
            continue
        if path not in base:
            raise SandboxViolation("CHECK_MODULE_MISSING", path)
    result = {**base, **patch}
    for path in deletions:
        result.pop(path)
    _assert_no_ancestor_files(result)
    if result == base:
        raise SandboxViolation("NO_OP_PATCH", "the patch does not change the base tree")
    if len(result) > plan.limits.max_files:
        raise SandboxViolation("FILE_COUNT_LIMIT_EXCEEDED", str(len(result)))
    if sum(len(data) for data in result.values()) > plan.limits.max_workspace_bytes:
        raise SandboxViolation("WORKSPACE_LIMIT_EXCEEDED", "patched tree exceeds byte budget")
    return result, tuple(sorted(changed))


def _isolation(limits: ExecutionLimits, available: bool, blockers: tuple[str, ...] = (),
               environment_hash: str | None = None) -> IsolationReceipt:
    return IsolationReceipt(
        available=available,
        environment_hash=environment_hash,
        mode="USER_MOUNT_NET_PID_NAMESPACE_CHROOT",
        filesystem="READ_ONLY_WORKSPACE_EPHEMERAL_TMPFS",
        network="ISOLATED_NO_EGRESS",
        memory_limit=f"RLIMIT_AS={limits.max_memory_bytes} per process; aggregate cgroup cap unavailable",
        cpu_limit=f"RLIMIT_CPU={limits.max_cpu_seconds} seconds per process",
        process_limit=f"PID namespace + RLIMIT_NPROC={limits.max_processes}; cgroup pids cap unavailable",
        disk_limit=f"read-only root/workspace; /tmp tmpfs={min(_TMPFS_BYTES, limits.max_workspace_bytes)} bytes",
        output_limit=f"captured combined output <= {limits.max_output_bytes} bytes; no raw output persisted",
        blockers=blockers,
    )


def _write_rootfs(root: Path, files: Mapping[str, bytes]) -> None:
    dirs = ("usr", "proc", "tmp", "workspace", "dev", "home", "root", "run", "var", "etc", "opt", "sys")
    for name in dirs:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name, target in (("lib", "usr/lib"), ("lib64", "usr/lib64"), ("bin", "usr/bin")):
        (root / name).symlink_to(target)
    (root / "var" / "tmp").symlink_to("/tmp")
    (root / "etc" / "passwd").write_text("root:x:0:0:root:/root:/bin/false\n", encoding="ascii")
    (root / "etc" / "group").write_text("root:x:0:\n\nnobody:x:65534:\n", encoding="ascii")
    (root / "etc" / "nsswitch.conf").write_text("passwd: files\ngroup: files\n", encoding="ascii")
    runner = root / "opt" / "amc-engineering-unittest-runner.py"
    runner.write_text(_UNITTEST_CODE, encoding="utf-8")
    runner.chmod(0o444)
    for name in ("null", "zero", "urandom"):
        (root / "dev" / name).touch()
    for rel, data in files.items():
        target = root / "workspace" / PurePosixPath(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
    for directory, _, _ in os.walk(root / "workspace", topdown=False):
        Path(directory).chmod(0o555)
    for name in ("proc", "tmp", "dev", "home", "root", "run", "var", "etc", "opt", "sys", "usr"):
        (root / name).chmod(0o555)
    root.chmod(0o555)


def _resource_map(limits: ExecutionLimits) -> dict:
    return {
        "cpu_seconds": limits.max_cpu_seconds,
        "memory_bytes": limits.max_memory_bytes,
        "processes": limits.max_processes,
        "output_bytes": limits.max_output_bytes,
        "disk_bytes": min(_TMPFS_BYTES, limits.max_workspace_bytes),
        "disk_inodes": _TMPFS_INODES,
    }


def _launch_namespace(root: Path, command: list[str], cwd: str, limits: ExecutionLimits, timeout: int) -> _ProcessResult:
    started_at = _now()
    unshare = shutil.which("unshare")
    if not unshare or not shutil.which("mount"):
        return _ProcessResult(None, None, 0, b"", started_at, _now(), launch_error="namespace tools absent")
    argv = [unshare, "--user", "--map-root-user", "--mount", "--net", "--pid", "--fork", sys.executable,
            "-I", "-c", _BOOTSTRAP, str(root), json.dumps(command), json.dumps(_SANDBOX_ENV),
            json.dumps(_resource_map(limits)), cwd]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=_CONTROL_ENV, close_fds=True, start_new_session=True)
    except OSError as exc:
        return _ProcessResult(None, None, 0, b"", started_at, _now(), launch_error=type(exc).__name__)
    return _capture_output(proc, limits.max_output_bytes, timeout, started_at)


def _capture_output(proc: subprocess.Popen, output_limit: int, timeout: int, started_at: str) -> _ProcessResult:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    digest, output = hashlib.sha256(), bytearray()
    total, deadline, timed_out, over_limit = 0, time.monotonic() + timeout, False, False
    while selector.get_map():
        if time.monotonic() >= deadline and not timed_out:
            timed_out = True
            _terminate(proc)
        for key, _ in selector.select(timeout=0.05):
            chunk = os.read(key.fd, 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            digest.update(chunk)
            total += len(chunk)
            if total > output_limit and not over_limit:
                over_limit = True
                _terminate(proc)
            output.extend(chunk)
            if len(output) > output_limit:
                del output[:len(output) - output_limit]
    selector.close()
    output_hash = None if over_limit or timed_out else digest.hexdigest()
    return _ProcessResult(proc.wait(), output_hash, min(total, output_limit), bytes(output),
                          started_at, _now(), timed_out, over_limit)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=0.5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def probe_isolation(limits: ExecutionLimits | None = None) -> IsolationReceipt:
    """Probe the exact local namespace setup and return its evidenced controls."""
    return _probe_sandbox(limits or _fixture_limits())[0]


def _probe_sandbox(limits: ExecutionLimits) -> tuple[IsolationReceipt, dict]:
    missing = [name for name in ("unshare", "mount") if not shutil.which(name)]
    if missing:
        receipt = _isolation(limits, False, tuple(f"{name.upper()}_UNAVAILABLE" for name in missing))
        return receipt, {}
    with tempfile.TemporaryDirectory(prefix="amc-engineering-probe-") as temp:
        root = Path(temp) / "root"
        root.mkdir()
        _write_rootfs(root, {"probe.txt": b"read-only probe\n"})
        host_namespaces = [os.stat(f"/proc/self/ns/{name}").st_ino for name in ("user", "mnt", "net", "pid")]
        command = ["/usr/bin/python3", "-I", "-S", "-c", _PROBE_CODE,
                   *(str(namespace_id) for namespace_id in host_namespaces)]
        observed = _launch_namespace(root, command, "", limits, timeout=min(20, limits.max_wall_seconds))
    blockers: list[str] = []
    if observed.launch_error:
        blockers.append("NAMESPACE_LAUNCH_FAILED")
    if observed.exit_code != 0 or not observed.output_tail:
        blockers.append("ISOLATION_PROBE_FAILED")
    facts: dict = {}
    if not blockers:
        try:
            facts = json.loads(observed.output_tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            blockers.append("ISOLATION_PROBE_INVALID_RESULT")
    _verify_probe(facts, limits, blockers)
    environment_hash = None
    if facts and not blockers:
        environment_hash = canonical_hash({
            "sandbox": "engineering-fixture/v1",
            "unittest_runner_sha256": _RUNNER_SHA256,
            "python_version": facts["python_version"],
            "python_implementation": facts["python_implementation"],
            "machine": facts["machine"],
            "kernel": facts["kernel"],
            "tmp_total_bytes": facts["tmp_total_bytes"],
            "tmp_total_inodes": facts["tmp_total_inodes"],
            "namespace_observations": {
                key: facts[key] for key in (
                    "user_namespace_distinct", "mount_namespace_distinct",
                    "network_namespace_distinct", "pid_namespace_distinct",
                )
            },
            "limits": limits.model_dump(mode="json"),
            "environment": _SANDBOX_ENV,
        })
    receipt = _isolation(limits, not blockers, tuple(sorted(set(blockers))), environment_hash)
    return receipt, facts


def _verify_probe(facts: dict, limits: ExecutionLimits, blockers: list[str]) -> None:
    if not facts:
        return
    if (facts.get("pid") != 1 or not facts.get("proc_pid_1")
            or not facts.get("pid_namespace_distinct")):
        blockers.append("PID_NAMESPACE_UNVERIFIED")
    if not facts.get("user_namespace_distinct"):
        blockers.append("USER_NAMESPACE_UNVERIFIED")
    if not facts.get("mount_namespace_distinct"):
        blockers.append("MOUNT_NAMESPACE_UNVERIFIED")
    if facts.get("env") != _SANDBOX_ENV:
        blockers.append("ENVIRONMENT_NOT_SCRUBBED")
    if not facts.get("python_version") or not facts.get("machine") or not facts.get("kernel"):
        blockers.append("ENVIRONMENT_FINGERPRINT_UNAVAILABLE")
    expected_root = ["bin", "dev", "etc", "home", "lib", "lib64", "opt", "proc", "root", "run", "sys", "tmp", "usr", "var", "workspace"]
    if facts.get("home_entries") or facts.get("root_entries") != expected_root:
        blockers.append("HOST_HOME_OR_ROOT_VISIBLE")
    if (not facts.get("workspace_read_only") or not facts.get("usr_read_only") or not facts.get("etc_read_only")
            or not facts.get("root_read_only") or not facts.get("tmp_writable")):
        blockers.append("FILESYSTEM_POLICY_UNVERIFIED")
    tmp_bytes = facts.get("tmp_total_bytes", 0)
    tmp_inodes = facts.get("tmp_total_inodes", 0)
    tmp_limit = min(_TMPFS_BYTES, limits.max_workspace_bytes)
    if not 0 < tmp_bytes <= tmp_limit + 4096 or not 0 < tmp_inodes <= _TMPFS_INODES:
        blockers.append("TMPFS_BOUNDS_UNVERIFIED")
    if not facts.get("no_new_privs") or not facts.get("capabilities_dropped"):
        blockers.append("PRIVILEGE_DROP_UNVERIFIED")
    if (not facts.get("network_namespace_distinct") or facts.get("network_interfaces")
            or facts.get("network_routes")):
        blockers.append("NETWORK_NAMESPACE_UNVERIFIED")
    observed = facts.get("limits", {})
    expected = {"as": limits.max_memory_bytes, "cpu": limits.max_cpu_seconds, "nproc": limits.max_processes,
                "fsize": limits.max_output_bytes, "nofile": 128, "core": 0}
    for name, value in expected.items():
        if observed.get(name, (None,))[0] != value:
            blockers.append(f"{name.upper()}_RLIMIT_UNVERIFIED")
    if facts.get("nproc_child_count", limits.max_processes) > limits.max_processes - 1:
        blockers.append("PROCESS_LIMIT_ENFORCEMENT_UNVERIFIED")


def _fixture_limits() -> ExecutionLimits:
    return ExecutionLimits(max_wall_seconds=30, max_cpu_seconds=10, max_memory_bytes=268_435_456,
                           max_processes=4, max_files=50, max_file_bytes=200_000,
                           max_workspace_bytes=1_000_000, max_output_bytes=65_536)


def _not_run_check(check: CheckSpec, tree: str, environment: str, plan_hash: str,
                   status: CheckStatus, reason: str) -> CheckRecord:
    argv = ("/usr/bin/python3", "-I", "-S", "/opt/amc-engineering-unittest-runner.py", *check.argv[5:])
    return CheckRecord(requirement_id=check.requirement_id, plan_hash=plan_hash, argv=argv, cwd=check.cwd,
                       tree_hash=tree, environment_hash=environment, exit_code=None, status=status, output_sha256=None,
                       output_bytes=0, summary=reason[:300], started_at=_now(), finished_at=_now())


def _runner_payload(output: bytes) -> dict | None:
    marker = output.rfind(_RUNNER_RESULT_PREFIX)
    if marker < 0:
        return None
    raw = output[marker + len(_RUNNER_RESULT_PREFIX):].splitlines()[0].strip()
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
        return None
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("passed"), bool) or not isinstance(value.get("count"), int):
        return None
    if not isinstance(value.get("tests_run"), int):
        return None
    return value


def _summary(output: bytes, code: int | None, timed_out: bool, output_limited: bool) -> str:
    if timed_out:
        return "check timed out; output omitted"
    if output_limited:
        return "check exceeded the bounded output limit; output omitted"
    payload = _runner_payload(output)
    if payload is not None:
        passed = code == 0 and payload["passed"] and payload["count"] > 0 and payload["tests_run"] > 0
        result = "passed" if passed else "failed"
        return f"stdlib unittest ran {payload['tests_run']} test(s); {result}"
    return "check did not produce runner evidence; output omitted" if code == 0 else (
        f"check exited {code}; output omitted" if code is not None else "check did not start")


def _check_record(check: CheckSpec, tree: str, env_hash: str, plan_hash: str, proc: _ProcessResult) -> CheckRecord:
    payload = _runner_payload(proc.output_tail)
    passed = (proc.exit_code == 0 and not proc.timed_out and not proc.output_limited and payload is not None
              and payload["passed"] and payload["count"] > 0 and payload["tests_run"] > 0)
    status = CheckStatus.PASS if passed else CheckStatus.FAIL
    argv = ("/usr/bin/python3", "-I", "-S", "/opt/amc-engineering-unittest-runner.py", *check.argv[5:])
    return CheckRecord(requirement_id=check.requirement_id, plan_hash=plan_hash, argv=argv, cwd=check.cwd,
                       tree_hash=tree, environment_hash=env_hash, exit_code=proc.exit_code, status=status,
                       output_sha256=proc.output_hash, output_bytes=proc.output_bytes,
                       summary=_summary(proc.output_tail, proc.exit_code, proc.timed_out, proc.output_limited),
                       started_at=proc.started_at, finished_at=proc.finished_at)


def _disk_tree_hash(workspace: Path, limits: ExecutionLimits) -> str:
    files: dict[str, bytes] = {}
    total = 0
    for item in sorted(workspace.rglob("*")):
        if item.is_symlink():
            raise SandboxViolation("SYMLINK_CREATED", "workspace contains a symlink after checks")
        if not item.is_file():
            continue
        rel = item.relative_to(workspace).as_posix()
        safe_repo_path(rel)
        data = item.read_bytes()
        total += len(data)
        if len(files) + 1 > limits.max_files or total > limits.max_workspace_bytes:
            raise SandboxViolation("POST_CHECK_TREE_LIMIT", "sandbox workspace exceeds its bound")
        files[rel] = data
    return _tree_hash(files)


def _result_status(checks: list[CheckRecord]) -> ReviewStatus:
    if any(check.status is CheckStatus.BLOCKED for check in checks):
        return ReviewStatus.BLOCKED
    return ReviewStatus.PASSED if checks and all(c.status is CheckStatus.PASS for c in checks) else ReviewStatus.FAILED


def execute_synthetic_fixture_patch(base_files: Mapping[str, str | bytes], patch_files: Mapping[str, str | bytes], plan: PlanRecord,
                  *, context: ContextRecord, delete_paths: tuple[str, ...] = ()) -> ExecutionResultRecord:
    """Apply one non-empty text patch and run declared stdlib tests in isolation.

    This fixture tier is intentionally not wired to model routing or an API.
    Model-generated code remains blocked until stronger aggregate resource
    controls and a separately reviewed provider/authority path are installed.
    """
    # Re-validate serialized values so ``model_copy(update=...)`` cannot bypass
    # the immutable plan/context hash validators on frozen Pydantic models.
    plan = PlanRecord.model_validate(plan.model_dump(mode="json"))
    context = ContextRecord.model_validate(context.model_dump(mode="json"))
    limits = plan.limits
    base = _safe_files(base_files, limits)
    if context.revision != plan.base_revision:
        raise SandboxViolation("BASE_REVISION_MISMATCH", "context and plan revisions differ")
    if context.context_hash != plan.context_hash:
        raise SandboxViolation("CONTEXT_HASH_MISMATCH", "plan does not bind the supplied context manifest")
    verify_context_bytes(context, base)
    patch = _safe_files(patch_files, limits) if patch_files else {}
    deletions = tuple(safe_repo_path(path) for path in delete_paths)
    result_files, changed = _validate_plan_inputs(base, patch, deletions, plan)
    base_hash, result_hash = _tree_hash(base), _tree_hash(result_files)
    patch_hash = _patch_hash(patch, deletions)
    wall_deadline = time.monotonic() + limits.max_wall_seconds
    isolation, _environment_facts = _probe_sandbox(limits)
    environment_hash = isolation.environment_hash or canonical_hash({
        "sandbox": "engineering-fixture/v1", "limits": limits.model_dump(mode="json"),
        "environment": _SANDBOX_ENV, "probe_blockers": list(isolation.blockers),
    })
    if not isolation.available:
        checks = tuple(_not_run_check(c, result_hash, environment_hash, plan.plan_hash,
                                      CheckStatus.BLOCKED, "isolation unavailable") for c in plan.checks)
        return ExecutionResultRecord(status=ReviewStatus.BLOCKED, execution_tier="SYNTHETIC_FIXTURE",
                                     plan_id=plan.plan_id, plan_hash=plan.plan_hash,
                                     base_revision=plan.base_revision, context_hash=context.context_hash,
                                     base_tree_hash=base_hash, patch_hash=patch_hash, result_tree_hash=result_hash,
                                     changed_paths=changed, checks=checks, isolation=isolation)
    checks: list[CheckRecord] = []
    with tempfile.TemporaryDirectory(prefix="amc-engineering-run-") as temp:
        root = Path(temp) / "root"
        root.mkdir()
        _write_rootfs(root, result_files)
        workspace = root / "workspace"
        if _disk_tree_hash(workspace, limits) != result_hash:
            raise SandboxViolation("SNAPSHOT_MISMATCH", "isolated workspace differs from the immutable patch tree")
        for spec in plan.checks:
            remaining = int(wall_deadline - time.monotonic())
            if remaining <= 0:
                checks.append(_not_run_check(spec, result_hash, environment_hash, plan.plan_hash,
                                             CheckStatus.NOT_RUN, "plan wall-clock budget exhausted"))
                break
            command = ["/usr/bin/python3", "-I", "-S", "/opt/amc-engineering-unittest-runner.py", *spec.argv[5:]]
            proc = _launch_namespace(root, command, spec.cwd, limits,
                                     timeout=min(spec.timeout_seconds, remaining))
            check = _check_record(spec, result_hash, environment_hash, plan.plan_hash, proc)
            checks.append(check)
            if proc.launch_error:
                checks[-1] = check.model_copy(update={"status": CheckStatus.BLOCKED,
                                                      "summary": "namespace command could not start"})
                break
            if _disk_tree_hash(workspace, limits) != result_hash:
                checks[-1] = check.model_copy(update={"status": CheckStatus.FAIL,
                                                      "summary": "source tree changed after checks; evidence invalidated"})
                break
            if check.status is not CheckStatus.PASS:
                break
    while len(checks) < len(plan.checks):
        checks.append(_not_run_check(plan.checks[len(checks)], result_hash, environment_hash, plan.plan_hash,
                                     CheckStatus.NOT_RUN, "not run after an earlier check blocked or failed"))
    return ExecutionResultRecord(status=_result_status(checks), execution_tier="SYNTHETIC_FIXTURE",
                                 plan_id=plan.plan_id, plan_hash=plan.plan_hash,
                                 base_revision=plan.base_revision, context_hash=context.context_hash,
                                 base_tree_hash=base_hash, patch_hash=patch_hash, result_tree_hash=result_hash,
                                 changed_paths=changed, checks=tuple(checks), isolation=isolation)


__all__ = ["SandboxViolation", "execute_synthetic_fixture_patch", "probe_isolation"]
