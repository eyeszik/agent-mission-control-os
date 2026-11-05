"""STATE_VERIFICATION_CONTRACT: integrity-checked state handoffs between agents.

Every handoff is a ``Payload``. The receiver recomputes the content digest with the
repo's canonical protocol (AMC-CANON-1, ``agency.execution.canonical.canonical_hash``)
and compares it with ``content_hash``. On any failure the chain fails closed:

* ``PayloadIntegrityError`` is raised and the rejected payload is quarantined;
* the chain head is NOT advanced, so the state rolls back to payload_{N-1};
* a producer may re-derive payload_N from the rolled-back head and submit it again.

The module never retries on its own and never edits a stored payload.

Scope limits (documented, not hidden): the digest covers ``content`` only, as the
contract specifies. ``mutations_applied`` and ``access_log`` are not covered by the
digest. The chain is process-local; a multi-worker deployment needs a persisted head.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.langgraph.agency.execution.canonical import canonical_hash

PAYLOAD_ID_RE = re.compile(r"^payload_([a-z][a-z0-9_-]{0,39})_(0|[1-9][0-9]{0,8})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Markers that mean "not finished". Matched as whole tokens or bracketed template slots,
# so ordinary prose such as "todo list" or "the placeholder store" is not flagged.
_PLACEHOLDER_PATTERNS = (
    # Upper-case markers only: lower-case prose such as "todo list" is not a placeholder.
    re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b"),
    re.compile(r"\[INSERT[^\]]*\]"),
    re.compile(r"<INSERT[^>]*>"),
    re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}"),
    re.compile(r"\bPLACEHOLDER_[A-Z0-9_]+\b"),
    re.compile(r"\bNotImplementedError\b"),
    re.compile(r"lorem ipsum", re.IGNORECASE),
)


class PayloadIntegrityError(Exception):
    """Content does not match its declared hash. The head has been left at the prior valid payload."""

    def __init__(self, payload_id: str, expected: str, actual: str, rolled_back_to: Optional[str]) -> None:
        self.payload_id = payload_id
        self.expected = expected
        self.actual = actual
        self.rolled_back_to = rolled_back_to
        super().__init__(f"PAYLOAD_INTEGRITY: {payload_id} declared {expected[:12]}… computed {actual[:12]}…; "
                         f"state rolled back to {rolled_back_to or 'genesis'}")


class PayloadSequenceError(ValueError):
    """Counter is not the next expected one (replay, duplicate, or skipped payload)."""


class PlaceholderError(ValueError):
    """Content still contains a placeholder marker. Zero placeholders are required."""

    def __init__(self, locations: list[str]) -> None:
        self.locations = locations
        super().__init__(f"PLACEHOLDER_CONTENT at {locations[:5]}")


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_id: str
    agent_origin: str = Field(min_length=1, max_length=80)
    timestamp_utc: str
    content_hash: str
    schema_ref: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]
    mutations_applied: list[Any] = Field(default_factory=list)
    access_log: list[Any] = Field(default_factory=list)

    @field_validator("payload_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not PAYLOAD_ID_RE.match(value):
            raise ValueError("payload_id must match payload_{agent}_{counter}")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def _utc(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp_utc must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("timestamp_utc must carry a UTC offset of zero")
        return value

    @field_validator("content_hash")
    @classmethod
    def _hash(cls, value: str) -> str:
        if not SHA256_RE.match(value):
            raise ValueError("content_hash must be 64 lowercase hex characters")
        return value

    @field_validator("content")
    @classmethod
    def _nonempty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("content must not be empty")
        return value

    @property
    def counter(self) -> int:
        return int(PAYLOAD_ID_RE.match(self.payload_id).group(2))  # type: ignore[union-attr]


def content_digest(content: dict[str, Any]) -> str:
    """SHA-256 over the canonical AMC-CANON-1 encoding of ``content``."""
    return canonical_hash(content)


def find_placeholders(value: Any, path: str = "content") -> list[str]:
    """Return the JSON-pointer-like locations of every string that still holds a placeholder."""
    found: list[str] = []
    if isinstance(value, str):
        if any(p.search(value) for p in _PLACEHOLDER_PATTERNS):
            found.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(find_placeholders(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(find_placeholders(item, f"{path}[{index}]"))
    return found


def make_payload(*, agent: str, counter: int, content: dict[str, Any], schema_ref: str,
                 now: Optional[datetime] = None, mutations: Optional[list[Any]] = None,
                 access_log: Optional[list[Any]] = None) -> Payload:
    """Producer side: build a payload whose ``content_hash`` is computed, never typed by hand."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return Payload(
        payload_id=f"payload_{agent}_{counter}",
        agent_origin=agent,
        timestamp_utc=moment.isoformat().replace("+00:00", "Z"),
        content_hash=content_digest(content),
        schema_ref=schema_ref,
        content=content,
        mutations_applied=list(mutations or []),
        access_log=list(access_log or []),
    )


class Quarantined(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    payload_id: str
    reason: str
    expected_hash: str
    actual_hash: str
    rolled_back_to: Optional[str]


class PayloadChain:
    """Ordered, verified handoff history. The head only ever advances on a verified payload."""

    def __init__(self) -> None:
        self._accepted: list[Payload] = []
        self._quarantine: list[Quarantined] = []

    @property
    def head(self) -> Optional[Payload]:
        return self._accepted[-1] if self._accepted else None

    @property
    def accepted(self) -> tuple[Payload, ...]:
        return tuple(self._accepted)

    @property
    def quarantine(self) -> tuple[Quarantined, ...]:
        return tuple(self._quarantine)

    def _expected_counter(self) -> int:
        return 0 if self.head is None else self.head.counter + 1

    def accept(self, payload: Payload) -> Payload:
        """Verify and append ``payload``. Raises and leaves the chain unchanged on any failure."""
        rolled_back_to = self.head.payload_id if self.head else None
        expected_counter = self._expected_counter()
        if payload.counter != expected_counter:
            raise PayloadSequenceError(
                f"{payload.payload_id} has counter {payload.counter}; expected {expected_counter}")
        actual = content_digest(payload.content)
        if actual != payload.content_hash:
            self._quarantine.append(Quarantined(payload_id=payload.payload_id, reason="HASH_MISMATCH",
                                                expected_hash=payload.content_hash, actual_hash=actual,
                                                rolled_back_to=rolled_back_to))
            raise PayloadIntegrityError(payload.payload_id, payload.content_hash, actual, rolled_back_to)
        placeholders = find_placeholders(payload.content)
        if placeholders:
            self._quarantine.append(Quarantined(payload_id=payload.payload_id, reason="PLACEHOLDER_CONTENT",
                                                expected_hash=payload.content_hash, actual_hash=actual,
                                                rolled_back_to=rolled_back_to))
            raise PlaceholderError(placeholders)
        self._accepted.append(payload)
        return payload

    def verify_head(self) -> Optional[Payload]:
        """Re-verify the stored head. On mismatch, roll back to payload_{N-1} and raise."""
        head = self.head
        if head is None:
            return None
        actual = content_digest(head.content)
        if actual == head.content_hash:
            return head
        self._accepted.pop()
        rolled_back_to = self.head.payload_id if self.head else None
        self._quarantine.append(Quarantined(payload_id=head.payload_id, reason="HEAD_CORRUPTED",
                                            expected_hash=head.content_hash, actual_hash=actual,
                                            rolled_back_to=rolled_back_to))
        raise PayloadIntegrityError(head.payload_id, head.content_hash, actual, rolled_back_to)

    def recompute(self, producer: Callable[[Optional[Payload]], Payload]) -> Payload:
        """Ask the producer to re-derive the next payload from the rolled-back head, then verify it."""
        return self.accept(producer(self.head))


__all__ = [
    "Payload", "PayloadChain", "PayloadIntegrityError", "PayloadSequenceError", "PlaceholderError",
    "Quarantined", "content_digest", "find_placeholders", "make_payload",
]
