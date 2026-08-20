import os

# Tests run with an explicit loopback-only server principal. Production auth is
# intentionally not synthesized by the test harness.
os.environ.setdefault("AMC_AUTH_MODE", "local")
os.environ.setdefault("AMC_LOCAL_USER_ID", "test-operator")
os.environ.setdefault("AMC_LOCAL_TENANT_ID", "tenant-events-test")
os.environ.setdefault("AMC_LOCAL_PROJECT_IDS", "*")
