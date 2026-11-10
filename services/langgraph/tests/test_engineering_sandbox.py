"""Synthetic patch execution: immutable tree, bounded checks, and fail-closed isolation."""

from datetime import datetime

import pytest

from services.langgraph.agency.engineering import sandbox
from services.langgraph.agency.engineering.context import (
    ContextIntegrityError,
    build_context_record,
)
from services.langgraph.agency.engineering.contracts import (
    CheckSpec,
    CheckStatus,
    ContextRecord,
    ExecutionLimits,
    IsolationReceipt,
    PlanRecord,
    PlanStep,
    ReviewStatus,
)
from services.langgraph.agency.engineering.sandbox import (
    SandboxViolation,
    execute_synthetic_fixture_patch,
    probe_isolation,
)


def fixture_files(expected: str = "new", *, test_body: str | None = None) -> dict[str, str]:
    return {
        "src/__init__.py": "",
        "src/value.py": 'def value(): return "old"\n',
        "tests/__init__.py": "",
        "tests/test_value.py": test_body or (
            "import mmap\n"
            "import resource\n"
            "import unittest\n"
            "from src.value import value\n"
            "class TestValue(unittest.TestCase):\n"
            "    def test_address_space_limit(self):\n"
            "        limit = resource.getrlimit(resource.RLIMIT_AS)[0]\n"
            "        with self.assertRaises(OSError):\n"
            "            mmap.mmap(-1, limit * 2)\n"
            "    def test_patch(self):\n"
            "        self.assertEqual(value(), " + repr(expected) + ")\n"
            "        try:\n"
            "            open('/workspace/src/value.py', 'w').write('tampered')\n"
            "        except OSError:\n"
            "            self.assertTrue(True)\n"
            "        else:\n"
            "            self.fail('workspace must be read-only')\n"
        ),
        "README.md": "synthetic fixture\n",
    }


def limits(**changes) -> ExecutionLimits:
    raw = {
        "max_wall_seconds": 30,
        "max_cpu_seconds": 10,
        "max_memory_bytes": 268_435_456,
        "max_processes": 4,
        "max_files": 50,
        "max_file_bytes": 200_000,
        "max_workspace_bytes": 1_000_000,
        "max_output_bytes": 65_536,
    }
    raw.update(changes)
    return ExecutionLimits(**raw)


def valid_probe_facts(execution_limits: ExecutionLimits) -> dict:
    return {
        "pid": 1,
        "proc_pid_1": True,
        "env": sandbox._SANDBOX_ENV,
        "python_version": "3.12",
        "machine": "x86_64",
        "kernel": "test-kernel",
        "home_entries": [],
        "root_entries": ["bin", "dev", "etc", "home", "lib", "lib64", "opt", "proc", "root", "run", "sys", "tmp", "usr", "var", "workspace"],
        "user_namespace_distinct": True,
        "mount_namespace_distinct": True,
        "pid_namespace_distinct": True,
        "network_namespace_distinct": True,
        "workspace_read_only": True,
        "usr_read_only": True,
        "etc_read_only": True,
        "root_read_only": True,
        "tmp_writable": True,
        "tmp_total_bytes": min(sandbox._TMPFS_BYTES, execution_limits.max_workspace_bytes),
        "tmp_total_inodes": sandbox._TMPFS_INODES,
        "no_new_privs": True,
        "capabilities_dropped": True,
        "network_interfaces": [],
        "network_routes": [],
        "limits": {
            "as": (execution_limits.max_memory_bytes, execution_limits.max_memory_bytes),
            "cpu": (execution_limits.max_cpu_seconds, execution_limits.max_cpu_seconds),
            "nproc": (execution_limits.max_processes, execution_limits.max_processes),
            "fsize": (execution_limits.max_output_bytes, execution_limits.max_output_bytes),
            "nofile": (128, 128),
            "core": (0, 0),
        },
        "nproc_child_count": execution_limits.max_processes - 1,
    }


def context_for(base: dict[str, str]) -> ContextRecord:
    return build_context_record(revision="a" * 40, files=base, method="EXPLICIT_FILE")


def plan_for(base: dict[str, str], *, context: ContextRecord | None = None,
             check_module: str = "tests.test_value", execution_limits: ExecutionLimits | None = None,
             timeout: int = 20) -> PlanRecord:
    context = context or context_for(base)
    base_bytes = {path: content.encode("utf-8") for path, content in base.items()}
    return PlanRecord(
        plan_id="fixture-plan-001",
        base_revision=context.revision,
        base_tree_hash=sandbox._tree_hash(base_bytes),
        context_hash=context.context_hash,
        steps=(PlanStep(step_id="IMPLEMENT", objective="Apply a synthetic local patch"),),
        allowed_paths=("src",),
        allowed_argv=("PYTHON_UNITTEST",),
        checks=(CheckSpec(requirement_id="TEST_VALUE", argv=("python", "-S", "-m", "unittest", "-v", check_module),
                          timeout_seconds=timeout),),
        limits=execution_limits or limits(),
        stop_conditions=("isolation unavailable", "tree drift", "failed check"),
    )


def execute_fixture(base: dict[str, str], patch: dict[str, str], *, context: ContextRecord | None = None,
                    plan: PlanRecord | None = None) -> sandbox.ExecutionResultRecord:
    context = context or context_for(base)
    plan = plan or plan_for(base, context=context)
    return execute_synthetic_fixture_patch(base, patch, plan, context=context)


def test_isolation_probe_observes_namespace_filesystem_network_and_rlimits():
    receipt = probe_isolation(limits())
    assert receipt.mode == "USER_MOUNT_NET_PID_NAMESPACE_CHROOT"
    assert receipt.shared_kernel is True
    assert receipt.seccomp == "NOT_CONFIGURED"
    assert "aggregate cgroup cap unavailable" in receipt.memory_limit
    assert "cgroup pids cap unavailable" in receipt.process_limit
    if receipt.available:
        assert receipt.blockers == ()
        assert receipt.environment_hash and len(receipt.environment_hash) == 64
    else:
        assert receipt.blockers


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("tmp_total_bytes", 0),
        ("tmp_total_bytes", sandbox._TMPFS_BYTES + 4_097),
        ("tmp_total_inodes", 0),
        ("tmp_total_inodes", sandbox._TMPFS_INODES + 1),
    ],
)
def test_probe_verifier_rejects_unbounded_tmpfs_facts(field: str, invalid_value: int):
    facts = valid_probe_facts(limits())
    facts[field] = invalid_value
    blockers: list[str] = []
    sandbox._verify_probe(facts, limits(), blockers)
    assert "TMPFS_BOUNDS_UNVERIFIED" in blockers


@pytest.mark.parametrize(
    ("field", "expected_blocker"),
    [
        ("user_namespace_distinct", "USER_NAMESPACE_UNVERIFIED"),
        ("mount_namespace_distinct", "MOUNT_NAMESPACE_UNVERIFIED"),
        ("pid_namespace_distinct", "PID_NAMESPACE_UNVERIFIED"),
        ("network_namespace_distinct", "NETWORK_NAMESPACE_UNVERIFIED"),
    ],
)
def test_probe_verifier_rejects_missing_namespace_separation(field: str, expected_blocker: str):
    facts = valid_probe_facts(limits())
    facts[field] = False
    blockers: list[str] = []
    sandbox._verify_probe(facts, limits(), blockers)
    assert expected_blocker in blockers


def test_fixture_patch_runs_only_in_isolation_and_binds_result_to_tested_tree():
    base = fixture_files()
    patch = {"src/value.py": 'def value(): return "new"\n'}
    result = execute_fixture(base, patch)
    if not result.isolation.available:
        assert result.status is ReviewStatus.BLOCKED
        assert result.checks[0].status is CheckStatus.BLOCKED
        assert result.checks[0].exit_code is None
        return
    assert result.status is ReviewStatus.PASSED
    assert result.execution_tier == "SYNTHETIC_FIXTURE"
    assert result.base_tree_hash != result.result_tree_hash
    assert result.patch_hash != result.result_tree_hash
    assert result.changed_paths == ("src/value.py",)
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.status is CheckStatus.PASS
    assert check.tree_hash == result.result_tree_hash
    assert check.environment_hash == result.isolation.environment_hash
    assert check.output_sha256 and check.output_bytes > 0
    assert "2 test(s); passed" in check.summary
    assert datetime.fromisoformat(check.started_at) <= datetime.fromisoformat(check.finished_at)
    assert base["src/value.py"] == 'def value(): return "old"\n'
    assert patch["src/value.py"] == 'def value(): return "new"\n'


def test_plan_hash_is_deterministic_and_rejects_content_drift():
    base = fixture_files()
    plan = plan_for(base)
    assert plan.plan_hash and len(plan.plan_hash) == 64
    serialized = plan.model_dump(mode="json")
    assert PlanRecord.model_validate(serialized).plan_hash == plan.plan_hash
    serialized["steps"][0]["objective"] = "Unapproved plan drift."
    with pytest.raises(ValueError, match="plan hash does not match"):
        PlanRecord.model_validate(serialized)


def test_context_manifest_and_plan_bind_the_exact_input_bytes():
    base = fixture_files()
    context = context_for(base)
    plan = plan_for(base, context=context)
    tampered = dict(base)
    tampered["src/value.py"] = 'def value(): return "different"\\n'
    with pytest.raises(ContextIntegrityError, match="CONTEXT_BLOB_MISMATCH"):
        execute_synthetic_fixture_patch(tampered, {"src/value.py": 'def value(): return "new"\\n'}, plan, context=context)
    malformed = context.model_dump(mode="json")
    malformed["context_hash"] = "f" * 64
    with pytest.raises(ValueError, match="context hash does not match"):
        ContextRecord.model_validate(malformed)


def test_changed_test_evidence_is_rejected_before_execution():
    base = fixture_files()
    with pytest.raises(SandboxViolation, match="TEST_EVIDENCE_MODIFIED"):
        execute_fixture(base, {"src/value.py": 'def value(): return "new"\n',
                               "tests/test_value.py": "# replaced evidence"})


def test_out_of_scope_patch_is_rejected_before_execution():
    base = fixture_files()
    with pytest.raises(SandboxViolation, match="PATH_OUT_OF_SCOPE"):
        execute_fixture(base, {"README.md": "outside the plan\n"})


def test_noop_binary_traversal_and_oversized_inputs_are_rejected():
    base = fixture_files()
    with pytest.raises(SandboxViolation, match="NO_OP_PATCH"):
        execute_fixture(base, {"src/value.py": base["src/value.py"]})
    with pytest.raises(ValueError):
        execute_fixture(base, {"../escape.py": "bad"})
    with pytest.raises(SandboxViolation, match="BINARY_CONTENT_REJECTED"):
        execute_fixture(base, {"src/value.py": b"\x00binary"})
    with pytest.raises(SandboxViolation, match="FILE_LIMIT_EXCEEDED"):
        execute_fixture(base, {"src/value.py": "x" * 200_001})


def test_missing_isolation_blocks_without_host_fallback(monkeypatch):
    base = fixture_files()
    blocked = IsolationReceipt(
        available=False,
        mode="USER_MOUNT_NET_PID_NAMESPACE_CHROOT",
        filesystem="READ_ONLY_WORKSPACE_EPHEMERAL_TMPFS",
        network="ISOLATED_NO_EGRESS",
        memory_limit="unavailable",
        cpu_limit="unavailable",
        process_limit="unavailable",
        disk_limit="unavailable",
        output_limit="unavailable",
        blockers=("CGROUP_WRITE_BLOCKED",),
    )
    monkeypatch.setattr(sandbox, "_probe_sandbox", lambda _limits: (blocked, {}))
    monkeypatch.setattr(sandbox, "_launch_namespace",
                        lambda *args, **kwargs: pytest.fail("host fallback must never execute"))
    result = execute_fixture(base, {"src/value.py": 'def value(): return "new"\n'})
    assert result.status is ReviewStatus.BLOCKED
    assert result.checks[0].status is CheckStatus.BLOCKED
    assert result.checks[0].exit_code is None
    assert result.isolation.blockers == ("CGROUP_WRITE_BLOCKED",)


def test_failed_test_never_produces_passed_review():
    base = fixture_files(expected="does-not-match")
    result = execute_fixture(base, {"src/value.py": 'def value(): return "new"\n'})
    if not result.isolation.available:
        pytest.skip("user/mount/net/PID namespaces unavailable; fail-closed test covered separately")
    assert result.status is ReviewStatus.FAILED
    assert result.checks[0].status is CheckStatus.FAIL
    assert result.checks[0].exit_code != 0


def test_zero_discovered_tests_cannot_be_reported_as_passed():
    base = fixture_files(test_body="# empty module; no tests\n")
    result = execute_fixture(base, {"src/value.py": "fixture source; no tests discovered"})
    if not result.isolation.available:
        pytest.skip("user/mount/net/PID namespaces unavailable; fail-closed test covered separately")
    assert result.status is ReviewStatus.FAILED
    assert result.checks[0].status is CheckStatus.FAIL
    assert "0 test(s); failed" in result.checks[0].summary


def test_wall_clock_timeout_is_recorded_as_failure_not_success():
    base = fixture_files(test_body="import time\ntime.sleep(3)\n")
    result = execute_fixture(base, {"src/value.py": 'def value(): return "new"\n'},
                             plan=plan_for(base, execution_limits=limits(max_wall_seconds=6), timeout=1))
    if not result.isolation.available:
        pytest.skip("user/mount/net/PID namespaces unavailable; fail-closed test covered separately")
    assert result.status is ReviewStatus.FAILED
    assert result.checks[0].status is CheckStatus.FAIL
    assert "timed out" in result.checks[0].summary
    assert result.checks[0].exit_code != 0


def test_cpu_limit_kills_an_unbounded_test_process():
    base = fixture_files(test_body="while True:\n    pass\n")
    result = execute_fixture(
        base,
        {"src/value.py": "fixture source"},
        plan=plan_for(base, execution_limits=limits(max_cpu_seconds=1, max_wall_seconds=5), timeout=4),
    )
    if not result.isolation.available:
        pytest.skip("user/mount/net/PID namespaces unavailable; fail-closed test covered separately")
    assert result.status is ReviewStatus.FAILED
    assert result.checks[0].status is CheckStatus.FAIL
    assert result.checks[0].exit_code not in (None, 0)
    assert "timed out" not in result.checks[0].summary


def test_output_capture_is_bounded_and_raw_test_output_is_not_retained():
    base = fixture_files(test_body="print('O' * 30000)\n")
    result = execute_fixture(base, {"src/value.py": 'def value(): return "new"\n'},
                             plan=plan_for(base, execution_limits=limits(max_output_bytes=4096)))
    if not result.isolation.available:
        pytest.skip("user/mount/net/PID namespaces unavailable; fail-closed test covered separately")
    check = result.checks[0]
    assert result.status is ReviewStatus.FAILED
    assert check.status is CheckStatus.FAIL
    assert check.output_bytes <= 4096
    assert check.output_sha256 is None
    assert "output" in check.summary
