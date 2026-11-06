"""ASI10: anomaly strikes, the session halt, and owner-only clearance. Deterministic clock, no sleeps."""

import pytest

from services.langgraph.agency.reliability import execution_bounds as eb
from services.langgraph.agency.reliability.execution_bounds import BoundViolation, Limits, SessionGuard


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _fresh_registry():
    eb.reset_registry()
    yield
    eb.reset_registry()


def _guard(clock: FakeClock, **limits) -> SessionGuard:
    base = {"max_calls": 10_000, "max_calls_per_window": 10_000, "max_novel_tools": 10_000,
            "max_consecutive_refusals": 10_000, "max_session_spawns": 10_000, "drift_window": 3, "max_strikes": 3}
    base.update(limits)
    return SessionGuard(limits=Limits(**base), clock=clock)


def _code(fn) -> str:
    with pytest.raises(BoundViolation) as exc:
        fn()
    return exc.value.code


def test_velocity_is_a_strike_and_the_call_that_exceeds_it_is_refused():
    clock = FakeClock()
    guard = _guard(clock, max_calls_per_window=3, window_s=10.0)
    for i in range(3):
        guard.admit("t", f"h{i}")
    assert _code(lambda: guard.admit("t", "h9")) == "VELOCITY_EXCEEDED"
    assert guard.anomaly_state()["strikes"] == ["VELOCITY_EXCEEDED"]
    clock.t += 11  # the window slides forward and calls are admitted again
    guard.admit("t", "h10")


def test_tool_sprawl_is_detected():
    clock = FakeClock()
    guard = _guard(clock, max_novel_tools=2)
    guard.admit("a", "1")
    guard.admit("b", "1")
    assert _code(lambda: guard.admit("c", "1")) == "TOOL_SPRAWL"


def test_goal_drift_needs_consecutive_off_objective_calls():
    clock = FakeClock()
    guard = _guard(clock, drift_window=3)
    objective = eb.objective_terms("Design a landing page for the Northline coffee roastery")
    on = "landing page hero copy for the roastery"
    off = "compute the tax on cryptocurrency withdrawals"
    guard.admit("w", "a", objective=objective, text=on)
    guard.admit("w", "b", objective=objective, text=off)
    guard.admit("w", "c", objective=objective, text=on)  # resets the run
    guard.admit("w", "d", objective=objective, text=off)
    guard.admit("w", "e", objective=objective, text=off)
    assert _code(lambda: guard.admit("w", "f", objective=objective, text=off)) == "GOAL_DRIFT"


def test_drift_is_off_without_an_objective():
    guard = _guard(FakeClock(), drift_window=1)
    for i in range(5):
        guard.admit("w", f"h{i}", objective=frozenset(), text="anything at all here")


def test_refusal_streak_is_a_strike():
    clock = FakeClock()
    guard = _guard(clock, max_calls=1, max_consecutive_refusals=2)
    guard.admit("t", "h0")
    assert _code(lambda: guard.admit("t", "h1")) == "CALL_BUDGET_EXHAUSTED"
    assert _code(lambda: guard.admit("t", "h2")) == "CALL_BUDGET_EXHAUSTED"
    assert guard.anomaly_state()["strikes"] == ["REFUSAL_STREAK"]


def test_replication_is_capped_per_session():
    guard = _guard(FakeClock(), max_session_spawns=1)
    guard.admit("spawn", "1", spawns_session=True)
    assert _code(lambda: guard.admit("spawn", "2", spawns_session=True)) == "REPLICATION_DETECTED"


def test_three_strikes_halt_the_session_and_every_later_call_is_refused():
    clock = FakeClock()
    guard = _guard(clock, max_calls_per_window=1, window_s=100.0)
    guard.admit("t", "h0")
    for i in range(3):
        assert _code(lambda i=i: guard.admit("t", f"x{i}")) == "VELOCITY_EXCEEDED"
    assert guard.halted
    clock.t += 10_000  # time alone never lifts a halt
    assert _code(lambda: guard.admit("other", "fresh")) == "SESSION_HALTED"


def test_only_a_named_owner_can_clear_a_halt_and_the_clear_is_recorded():
    clock = FakeClock()
    guard = _guard(clock, max_calls_per_window=1, max_strikes=1)
    guard.admit("t", "h0")
    assert _code(lambda: guard.admit("t", "h1")) == "VELOCITY_EXCEEDED"
    assert guard.halted
    for bad in ("", "  ", "service", "system", "agent"):
        with pytest.raises(ValueError):
            guard.clear_halt(bad, note="I say so")
    with pytest.raises(ValueError):
        guard.clear_halt("isaac", note="  ")
    assert guard.halted
    record = guard.clear_halt("isaac", note="reviewed the strike trail; budget reset by the owner")
    assert record["owner"] == "isaac" and record["strikes"]
    assert not guard.halted
    assert guard.anomaly_state()["clears"][0]["owner"] == "isaac"


def test_halted_sessions_are_not_evicted_and_a_full_registry_refuses_newcomers(monkeypatch):
    monkeypatch.setattr(eb, "MAX_SESSIONS", 2)
    clock = FakeClock()
    halt_limits = Limits(max_strikes=1, max_calls_per_window=1)
    for key in ("s1", "s2"):
        guard = eb.guard_for(key, limits=halt_limits, clock=clock)
        guard.admit("t", "a")
        with pytest.raises(BoundViolation):
            guard.admit("t", "b")  # velocity strike, halts the session
        assert guard.halted
    # Both slots hold halted sessions, so a newcomer is refused rather than displacing a halt.
    with pytest.raises(BoundViolation) as exc:
        eb.guard_for("s3", clock=clock)
    assert exc.value.code == "SESSION_REGISTRY_FULL"
    # Churn cannot clear a halt: the halted session is the same object after the refusal.
    assert eb.guard_for("s1", clock=clock).halted


def test_oldest_unhalted_session_is_evicted_first(monkeypatch):
    monkeypatch.setattr(eb, "MAX_SESSIONS", 2)
    clock = FakeClock()
    halted = eb.guard_for("halted", limits=Limits(max_strikes=1, max_calls_per_window=1), clock=clock)
    halted.admit("t", "a")
    with pytest.raises(BoundViolation):
        halted.admit("t", "b")
    eb.guard_for("s2", clock=clock)
    eb.guard_for("s3", clock=clock)  # evicts s2, not the halted session
    assert eb.guard_for("halted", clock=clock) is halted


def test_module_clear_halt_targets_one_session():
    clock = FakeClock()
    guard = eb.guard_for("only", limits=Limits(max_strikes=1, max_calls_per_window=1), clock=clock)
    guard.admit("t", "a")
    with pytest.raises(BoundViolation):
        guard.admit("t", "b")
    assert eb.clear_halt("only", "isaac", note="owner reviewed the trail")["owner"] == "isaac"
    assert not guard.halted
    with pytest.raises(KeyError):
        eb.clear_halt("absent", "isaac", note="x")


# ---- gateway integration -------------------------------------------------------------------

from services.langgraph.agency.council.gateway import GatewayDenied, invoke  # noqa: E402
from services.langgraph.tests.council_support import council, gated_mission  # noqa: E402,F401 - fixture


def test_gateway_refuses_a_halted_mission_with_423(monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    ctx = {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"],
           "mission_id": mission["mission_id"], "user_id": "tester"}
    key = (ctx["tenant_id"], ctx["project_id"], ctx["mission_id"])
    guard = eb.guard_for(key)
    guard.admit("workspace.list_files", "seed", depth=1)  # a strike-free admission
    for _ in range(3):
        guard._strike("GOAL_DRIFT")
    assert guard.halted
    with pytest.raises(GatewayDenied) as exc:
        invoke("workspace.list_files", {"path": "."}, ctx=ctx, seat="george", mission=mission)
    assert exc.value.code == "SESSION_HALTED"
    assert exc.value.status == 423
