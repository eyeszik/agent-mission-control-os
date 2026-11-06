---
name: hmac-replay-multiworker
description: Debug and extend the HMAC v2 ingress and its shared nonce store (ASI07) for multi-worker deployments. Use when the multi-worker replay test fails, when touching security/hmac_ingress.py, security/replay_store.py, persistence/database.py, or the hmac_replay_nonces table, or when diagnosing 500s under concurrent startup.
---

# HMAC v2 replay protection across workers

## Design
- Protocol v2 signs `AMC-HMAC-V2\n` + timestamp + nonce + body. Freshness window 300 s.
- Nonces are stored in the **shared DB layer** (`hmac_replay_nonces`), with no new infrastructure.
  The store is `database` by default. `memory` is refused when `WEB_CONCURRENCY` or `UVICORN_WORKERS` is above 1.
- State is written only after a valid signature. Saturation returns 503.

## Tests
- `services/langgraph/tests/test_hmac_replay_shared.py` runs a real multi-worker server (`hmac_replay_worker_app.py`).
  Expected: 1 accepted, 47 rejected for replays. Run it 3 times, since concurrency bugs can be intermittent.
- `test_hmac_ingress_runtime.py` isolates the DB per test.

## Open investigation (unconfirmed)
- An earlier run showed 40 × 401 and 8 × 500 under concurrent startup. It did **not** reproduce in a fresh environment
  (3 consecutive passes after a reset). The root cause is **not confirmed**. Suspected: concurrent schema migration
  in `init_db` (`_ensure_approval_columns` ALTER TABLE). Treat it as a hypothesis.
- To investigate: rerun the concurrent `init_db` probe with `cwd` at the repo root (or `PYTHONPATH` set), capture the
  500 traceback first, and change nothing until the traceback is read.
