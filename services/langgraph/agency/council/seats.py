"""George, Fable/Cipher and Arty: prompts, output validation, timeouts and bounded retries.

Engines differ in how they orchestrate the seats; they share these prompts and
these validators, so every engine yields the same contracts. A seat call that
times out or returns output that does not validate is retried up to
``COUNCIL_SEAT_MAX_ATTEMPTS``; a missing or degraded model is not retried.
"""

from __future__ import annotations

import concurrent.futures
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from .contracts import RiskAssessment, Scaffold, Strategy
from .model import ModelUnavailable, SeatModel, extract_json, render_prompt
from .policy import merge_model_findings

ROLES = {
    "george": ("George - Mission Commander", "Synthesize raw ideas into structured blueprint architectures",
               "Strategic visionary specializing in enterprise system design and goal decomposition."),
    "fable": ("Fable/Cipher - Sentinel Guard", "Identify security vulnerabilities, secret exposure, and compliance failures",
              "Uncompromising security auditor and risk analyst enforcing strict approval boundaries."),
    "arty": ("Arty - Product Maker", "Design intuitive frontends, Framer Motion transitions, and clean code scaffolding",
             "Master creative developer focused on user experience, design systems, and rapid prototyping."),
}

INSTRUCTIONS = {
    "george": ("Decompose the idea into goals, an architecture outline and a task dependency graph. JSON keys: "
               "summary (string), goals (string[]), architecture (string[]), tasks ([{id, title, seat in george|fable|arty, "
               "depends_on (task ids), acceptance}]). Task ids are lowercase-kebab; the graph must be acyclic."),
    "fable": ("Review the strategy for security, permission, secret-handling and compliance risks. The policy scan in the "
              "context is authoritative; you may only add findings. JSON keys: narrative (string), additional_findings "
              "([{code, severity in LOW|MEDIUM|HIGH|CRITICAL, detail}])."),
    "arty": ("Produce a UI/code scaffold for the approved strategy using the repository design tokens. JSON keys: summary, "
             "components ([{name PascalCase, purpose, props}]), design_tokens (string[]), files ([{path relative .tsx|.ts|"
             ".css|.md|.json, content}])."),
}


class SeatFailed(RuntimeError):
    def __init__(self, seat: str, code: str, attempts: int, message: str = "") -> None:
        super().__init__(message or f"{seat} failed: {code}")
        self.seat, self.code, self.attempts = seat, code, attempts


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except ValueError:
        return default


def seat_timeout_seconds() -> int:
    return _env_int("COUNCIL_SEAT_TIMEOUT_SECONDS", 60, 1, 600)


def seat_max_attempts() -> int:
    return _env_int("COUNCIL_SEAT_MAX_ATTEMPTS", 2, 1, 5)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seat_prompt(seat: str, context: Mapping[str, Any]) -> str:
    return render_prompt(seat, INSTRUCTIONS[seat], context)


def validate_output(seat: str, text: str, *, policy: RiskAssessment | None = None) -> dict:
    """Parse untrusted model text into the seat's contract, or raise ValueError/ValidationError."""
    data = extract_json(text)
    if seat == "george":
        return Strategy.model_validate(data).model_dump(mode="json")
    if seat == "fable":
        if policy is None:
            raise ValueError("fable output needs the policy assessment it extends")
        return merge_model_findings(policy, data).model_dump(mode="json")
    if seat == "arty":
        return Scaffold.model_validate(data).model_dump(mode="json")
    raise ValueError(f"unknown seat {seat}")


def _call_with_timeout(model: SeatModel, prompt: str, timeout: int) -> str:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="council-seat")
    try:
        return pool.submit(model.complete, prompt).result(timeout=timeout)
    finally:
        # Do not wait for a hung provider call; its result is discarded.
        pool.shutdown(wait=False, cancel_futures=True)


def run_seat(model: SeatModel, seat: str, context: Mapping[str, Any], *,
             policy: RiskAssessment | None = None) -> tuple[dict, int]:
    """Call the model for one seat; returns (validated output, attempts)."""
    prompt = seat_prompt(seat, context)
    attempts, last = 0, "SEAT_OUTPUT_INVALID"
    for _ in range(seat_max_attempts()):
        attempts += 1
        try:
            text = _call_with_timeout(model, prompt, seat_timeout_seconds())
        except concurrent.futures.TimeoutError:
            last = "SEAT_TIMEOUT"
            continue
        except ModelUnavailable as exc:
            raise SeatFailed(seat, exc.code, attempts, str(exc)) from exc
        try:
            return validate_output(seat, text, policy=policy), attempts
        except (ValueError, ValidationError):
            last = "SEAT_OUTPUT_INVALID"
    raise SeatFailed(seat, last, attempts)


__all__ = ["INSTRUCTIONS", "ROLES", "SeatFailed", "now", "run_seat", "seat_max_attempts", "seat_prompt",
           "seat_timeout_seconds", "validate_output"]
