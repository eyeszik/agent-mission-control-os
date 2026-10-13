"""ACE v100 opt-in REQUEST/ACCUT controls; no external effects."""
from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

class QualityContractError(ValueError):
    """Invalid input or quality policy; the caller must not publish."""

def canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise QualityContractError("input is not canonical JSON") from exc
    return sha256(encoded.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class RequestIntent:
    reason: str
    entities: tuple[str, ...]
    questions: tuple[str, ...]
    units: tuple[str, ...]
    events: tuple[str, ...]
    scope: str
    tradeoffs: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RequestIntent":
        if not isinstance(raw, Mapping):
            raise QualityContractError("REQUEST must be an object")
        def scalar(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value.strip():
                raise QualityContractError(f"{name} must be nonempty text")
            return value.strip()
        def items(name: str) -> tuple[str, ...]:
            value = raw.get(name)
            if not isinstance(value, (list, tuple)) or not value or any(
                not isinstance(item, str) or not item.strip() for item in value
            ):
                raise QualityContractError(f"{name} must be nonempty text array")
            return tuple(item.strip() for item in value)
        return cls(scalar("reason"), items("entities"), items("questions"),
                   items("units"), items("events"), scalar("scope"),
                   items("tradeoffs"))

    def envelope(self) -> dict[str, Any]:
        payload = asdict(self)
        return {"schema_version": "ace.request.v1", "intent": payload,
                "intent_digest": canonical_digest(payload)}

@dataclass(frozen=True)
class AccutPolicy:
    required_fields: tuple[str, ...]
    unique_key: str
    max_age_seconds: int
    min_accuracy: float = 1.0
    min_correctness: float = 1.0
    min_completeness: float = 1.0
    min_uniqueness: float = 1.0
    min_timeliness: float = 1.0

    def __post_init__(self) -> None:
        if not self.unique_key or not self.required_fields or self.max_age_seconds < 0:
            raise QualityContractError("invalid ACCUT policy")
        for value in (self.min_accuracy, self.min_correctness,
                      self.min_completeness, self.min_uniqueness, self.min_timeliness):
            if not 0 <= value <= 1:
                raise QualityContractError("ACCUT thresholds must be within [0,1]")

def validate_accut(rows: Sequence[Mapping[str, Any]], policy: AccutPolicy,
                   *, observed_at: datetime, timestamp_field: str = "observed_at",
                   valid_row=None) -> dict[str, Any]:
    """Quarantine row-level failures. Accuracy is UNKNOWN without an external oracle."""
    if observed_at.tzinfo is None:
        raise QualityContractError("observed_at must be timezone-aware")
    if not isinstance(rows, (list, tuple)):
        raise QualityContractError("rows must be an ordered array")
    if any(not isinstance(row, Mapping) for row in rows):
        raise QualityContractError("each row must be an object")
    if valid_row is not None and not callable(valid_row):
        raise QualityContractError("valid_row must be callable")
    n = len(rows)
    keys = [row.get(policy.unique_key) for row in rows]
    counts = Counter(str(key) for key in keys if key is not None)
    problems: list[dict[str, Any]] = []
    complete = correct = timely = unique = 0
    for i, row in enumerate(rows):
        reasons: list[str] = []
        filled = all(row.get(field) is not None and row.get(field) != ""
                     for field in policy.required_fields)
        complete += int(filled)
        if not filled:
            reasons.append("MISSING_REQUIRED")
        key = keys[i]
        is_unique = key is not None and counts[str(key)] == 1
        unique += int(is_unique)
        if not is_unique:
            reasons.append("DUPLICATE_OR_MISSING_KEY")
        try:
            stamp = row.get(timestamp_field)
            if not isinstance(stamp, str):
                raise ValueError("timestamp missing")
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("naive timestamp")
            age = (observed_at - parsed.astimezone(timezone.utc)).total_seconds()
            is_timely = 0 <= age <= policy.max_age_seconds
        except (ValueError, TypeError, OverflowError):
            is_timely = False
        timely += int(is_timely)
        if not is_timely:
            reasons.append("STALE_OR_INVALID_TIMESTAMP")
        try:
            is_correct = bool(valid_row(row)) if valid_row is not None else filled
        except Exception:
            is_correct = False
        correct += int(is_correct)
        if not is_correct:
            reasons.append("INVALID_DOMAIN_VALUE")
        if reasons:
            problems.append({"row_index": i, "reasons": sorted(set(reasons))})
    ratios = {"completeness": complete / n if n else 0.0,
              "correctness": correct / n if n else 0.0,
              "uniqueness": unique / n if n else 0.0,
              "timeliness": timely / n if n else 0.0,
              "accuracy": None}
    thresholds = {"completeness": policy.min_completeness,
                  "correctness": policy.min_correctness,
                  "uniqueness": policy.min_uniqueness,
                  "timeliness": policy.min_timeliness,
                  "accuracy": policy.min_accuracy}
    violations = sorted(k for k, threshold in thresholds.items()
                        if threshold > 0 and (ratios[k] is None or ratios[k] < threshold))
    return {"schema_version": "ace.accut.v1", "row_count": n,
            "metrics": ratios, "violations": violations, "quarantine": problems,
            "decision": "BLOCK" if violations else "ACCEPT",
            "source_digest": canonical_digest(rows)}

def compare_shadow(expected: Mapping[str, Any], shadow: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only differential check; no promotion or external mutation."""
    if not isinstance(expected, Mapping) or not isinstance(shadow, Mapping):
        raise QualityContractError("shadow comparisons require objects")
    before, after = canonical_digest(expected), canonical_digest(shadow)
    return {"schema_version": "ace.shadow.v1", "matches": before == after,
            "baseline_digest": before, "shadow_digest": after,
            "promotion_authorized": False}
