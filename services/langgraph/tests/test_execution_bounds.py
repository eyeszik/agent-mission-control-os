"""ASI08/ASI10 execution bounds: depth, call budget, identical-call loops, per-tool circuit breaker."""
from __future__ import annotations

import threading

import pytest

from services.langgraph.agency.council import gateway
from services.langgraph.agency.council.gateway import GatewayDenied, invoke
from services.langgraph.agency.reliability import execution_bounds as eb
from services.langgraph.agency.reliability.execution_bounds import BoundViolation, Limits, SessionGuard
from services.langgraph.persistence import council as store
from services.langgraph.tests.council_support import council, gated_mission  # noqa: F401 - fixture


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _fresh_registry():
    eb.reset_registry()
    yield
    eb.reset_registry()


def _guard(clock: FakeClock, **limits) -> SessionGuard:
    return SessionGuard(limits=Limits(**limits), clock=clock)


# --- limits from META_CONFIG ----------------------------------------------------------

def test_limits_cannot_exceed_the_contract_bounds():
    with pytest.raises(ValueError):
        Limits(max_depth=13)
    with pytest.raises(ValueError):
        Limits(retry_limit=4)
    with pytest.raises(ValueError):
        Limits(session_timeout_s=0)
    assert Limits().max_identical == 4  # 1 attempt + 3 retries


# --- depth, budget, timeout ------------------------------------------------------------

def test_depth_is_bounded_at_twelve():
    clock = FakeClock()
    guard = _guard(clock)
    guard.admit("tool", "h1", depth=12)
    with pytest.raises(BoundViolation) as info:
        guard.admit("tool", "h2", depth=13)
    assert info.value.code == "DEPTH_EXCEEDED"


def test_call_budget_stops_further_calls():
    clock = FakeClock()
    guard = _guard(clock, max_calls=3)
    for i in range(3):
        guard.admit("tool", f"h{i}")
    with pytest.raises(BoundViolation) as info:
        guard.admit("tool", "h-extra")
    assert info.value.code == "CALL_BUDGET_EXHAUSTED"


def test_session_times_out_after_the_contract_window():
    clock = FakeClock()
    guard = _guard(clock)
    clock.advance(299)
    guard.admit("tool", "h")
    clock.advance(2)
    with pytest.raises(BoundViolation) as info:
        guard.admit("tool", "h2")
    assert info.value.code == "SESSION_TIMEOUT"


# --- identical-call loops (retry limit) ------------------------------------------------

def test_identical_calls_stop_after_one_attempt_plus_three_retries():
    guard = _guard(FakeClock())
    for _ in range(4):
        guard.admit("workspace.read_file", "same-args")
    with pytest.raises(BoundViolation) as info:
        guard.admit("workspace.read_file", "same-args")
    assert info.value.code == "LOOP_DETECTED"
    # Different arguments to the same tool are not a loop.
    guard.admit("workspace.read_file", "other-args")


def test_refused_calls_change_no_counters():
    guard = _guard(FakeClock(), max_calls=2)
    guard.admit("t", "a")
    guard.admit("t", "a")
    with pytest.raises(BoundViolation):
        guard.admit("t", "a")  # budget and loop both exceeded
    assert guard.admitted_calls == 2


# --- circuit breaker -------------------------------------------------------------------

def test_breaker_opens_after_threshold_and_isolates_only_the_failing_node():
    clock = FakeClock()
    guard = _guard(clock, failure_threshold=3)
    for i in range(3):
        guard.admit("flaky", f"a{i}")
        guard.record("flaky", ok=False)
    assert guard.breaker_state("flaky") == eb.OPEN
    with pytest.raises(BoundViolation) as info:
        guard.admit("flaky", "a-new")
    assert info.value.code == "CIRCUIT_OPEN"
    guard.admit("healthy", "b")  # unrelated node keeps working
    assert guard.breaker_state("healthy") == eb.CLOSED


def test_success_resets_consecutive_failures():
    guard = _guard(FakeClock(), failure_threshold=3)
    for i in range(2):
        guard.admit("t", f"x{i}")
        guard.record("t", ok=False)
    guard.admit("t", "ok")
    guard.record("t", ok=True)
    guard.admit("t", "x2")
    guard.record("t", ok=False)
    assert guard.breaker_state("t") == eb.CLOSED  # not three in a row


def test_half_open_admits_exactly_one_probe_then_closes_on_success():
    clock = FakeClock()
    guard = _guard(clock, failure_threshold=1, cooldown_s=60)
    guard.admit("t", "a")
    guard.record("t", ok=False)
    with pytest.raises(BoundViolation):
        guard.admit("t", "b")  # still cooling down
    clock.advance(60)
    guard.admit("t", "probe")
    assert guard.breaker_state("t") == eb.HALF_OPEN
    with pytest.raises(BoundViolation) as info:
        guard.admit("t", "second-while-probing")
    assert info.value.code == "CIRCUIT_OPEN"
    guard.record("t", ok=True)
    assert guard.breaker_state("t") == eb.CLOSED


def test_failed_probe_reopens_the_breaker_for_a_full_cooldown():
    clock = FakeClock()
    guard = _guard(clock, failure_threshold=1, cooldown_s=60)
    guard.admit("t", "a")
    guard.record("t", ok=False)
    clock.advance(60)
    guard.admit("t", "probe")
    guard.record("t", ok=False)
    assert guard.breaker_state("t") == eb.OPEN
    clock.advance(59)
    with pytest.raises(BoundViolation):
        guard.admit("t", "too-early")


def test_concurrent_admission_never_exceeds_the_budget():
    # The velocity bound (ASI10) is disabled here so that this test still isolates the call budget.
    # It is tested on its own below.
    guard = _guard(FakeClock(), max_calls=60, max_calls_per_window=10_000)
    admitted, refused = [], []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            guard.admit("t", f"h{i}")
            with lock:
                admitted.append(i)
        except BoundViolation:
            with lock:
                refused.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(200)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(admitted) == 60 and len(refused) == 140


# --- session registry --------------------------------------------------------------------

def test_guard_for_returns_one_guard_per_session_and_evicts_the_oldest(monkeypatch):
    monkeypatch.setattr(eb, "MAX_SESSIONS", 2)
    first = eb.guard_for(("t", "p", "m1"))
    assert eb.guard_for(("t", "p", "m1")) is first
    eb.guard_for(("t", "p", "m2"))
    eb.guard_for(("t", "p", "m3"))  # evicts m1 (least recently used)
    assert eb.guard_for(("t", "p", "m1")) is not first


# --- execution-layer integration through the real council tool gateway --------------------

def _ctx(mission: dict) -> dict:
    return {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"],
            "mission_id": mission["mission_id"], "user_id": "tester"}


def _codes(mission_id: str) -> list[tuple[str, str]]:
    return [(a["decision"], a["reason_code"]) for a in store.list_tool_audits(mission_id)]


def test_gateway_loop_guard_denies_the_fifth_identical_call_and_audits_it(monkeypatch, council):  # noqa: F811 - pytest fixture injection
    mission = gated_mission(monkeypatch, council["project_id"])
    args = {"text": "same text every time"}
    for _ in range(4):
        invoke("policy.scan_text", args, ctx=_ctx(mission), seat="fable")
    with pytest.raises(GatewayDenied) as info:
        invoke("policy.scan_text", args, ctx=_ctx(mission), seat="fable")
    assert info.value.code == "LOOP_DETECTED" and info.value.status == 429
    assert ("DENIED", "LOOP_DETECTED") in _codes(mission["mission_id"])


def test_gateway_circuit_opens_after_repeated_tool_failures_and_the_tool_stops_running(monkeypatch, council):  # noqa: F811 - pytest fixture injection
    mission = gated_mission(monkeypatch, council["project_id"])
    calls = {"n": 0}

    def broken(ctx, args):
        calls["n"] += 1
        raise RuntimeError("downstream outage")

    spec = gateway.LOCAL_TOOLS["policy.scan_text"]
    monkeypatch.setitem(gateway.LOCAL_TOOLS, "policy.scan_text",
                        gateway.ToolSpec(**{**spec.__dict__, "handler": broken}))
    for i in range(3):  # distinct arguments, so only the breaker can stop them
        error = _denied_call(mission, f"attempt {i}")
        assert error.code == "TOOL_FAILED"
    error = _denied_call(mission, "attempt 3")
    assert error.code == "CIRCUIT_OPEN"
    assert calls["n"] == 3  # the handler never ran once the circuit opened


def _denied_call(mission: dict, text: str) -> GatewayDenied:
    with pytest.raises(GatewayDenied) as info:
        invoke("policy.scan_text", {"text": text}, ctx=_ctx(mission), seat="fable")
    return info.value
