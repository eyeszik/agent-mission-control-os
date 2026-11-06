"""Fixed lexical-normalization experiment; no network or generated code.

Inputs can be simulated mechanism text. Measurements are actual local counts,
not semantic novelty, relevance, market evidence or timing benchmarks.
"""
from __future__ import annotations

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.langgraph.agency.execution.canonical import canonical_hash
from ..verifiers import Verdict

EXECUTOR_VERSION = "innovation.lexical-normalization/v1"
SKILL_ID = "innovation_lexical_measurement"
VALIDATOR_ID = "innovation_lexical_readback"


class LexicalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_ref: str = Field(min_length=1, max_length=300)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_provenance: str = Field(pattern=r"^SIMULATED_OFFLINE_FIXTURE$")
    mechanisms: list[Annotated[str, StringConstraints(min_length=1, max_length=2000)]] = Field(min_length=1, max_length=64)


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def calculate(inputs: LexicalInput) -> dict:
    baseline = list(dict.fromkeys(inputs.mechanisms))
    candidate = list(dict.fromkeys(normalize(value) for value in inputs.mechanisms))
    baseline_redundancy = len(baseline) - len({normalize(value) for value in baseline})
    candidate_redundancy = len(candidate) - len({normalize(value) for value in candidate})
    return {"case_count": len(inputs.mechanisms), "baseline_retained_items": len(baseline),
            "candidate_retained_items": len(candidate), "baseline_redundant_items": baseline_redundancy,
            "candidate_redundant_items": candidate_redundancy, "unit": "items"}


def lexical_measurement(payload: dict) -> dict:
    inputs = LexicalInput.model_validate(payload["inputs"])
    report = {"schema_version": EXECUTOR_VERSION, "execution_mode": "LOCAL_COMPUTATION",
              "input_provenance": inputs.input_provenance, "input_hash": canonical_hash(inputs),
              "source_ref": inputs.source_ref, "source_hash": inputs.source_hash,
              "measurements": calculate(inputs), "external_calls": 0,
              "limitations": ["Case/whitespace equivalence only; not semantic duplicate detection.",
                              "Disclosed synthetic variants; no market or originality inference."]}
    return {"content": json.dumps(report, sort_keys=True, separators=(",", ":")),
            "mime_type": "application/json", "subtype": "innovation_local_measurement"}


def verify_measurement(output: dict, payload: dict) -> Verdict:
    try:
        expected = json.loads(lexical_measurement(payload)["content"])
        actual = json.loads(output["content"])
        passed = actual == expected
    except (KeyError, TypeError, ValueError):
        passed = False
    return Verdict(VALIDATOR_ID, passed, "Independent bounded count/recompile comparison; lexical-only scope")
