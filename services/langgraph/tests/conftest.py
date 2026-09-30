import os

# Tests run with an explicit loopback-only server principal. Production auth is
# intentionally not synthesized by the test harness.
os.environ.setdefault("AMC_AUTH_MODE", "local")
os.environ.setdefault("AMC_LOCAL_USER_ID", "test-operator")
os.environ.setdefault("AMC_LOCAL_TENANT_ID", "tenant-events-test")
os.environ.setdefault("AMC_LOCAL_PROJECT_IDS", "*")
# The single test principal both starts and decides runs, which separation of
# duties forbids; the local-only self-approval switch keeps those flows testable.
# tests/test_approval_authority.py exercises the enforced behaviour explicitly.
os.environ.setdefault("AMC_LOCAL_ROLE", "admin")
os.environ.setdefault("AMC_ALLOW_SELF_APPROVAL", "1")
# One tenant creates hundreds of runs across the suite; limits are exercised
# explicitly in tests/test_cost_and_rate_limits.py.
os.environ.setdefault("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "0")
os.environ.setdefault("AMC_MAX_ACTIVE_RUNS_PER_TENANT", "0")
