"""DeliveryContract: what success means for one run.

A contract is a list of requirements a reviewer can read and a deterministic
critic can check. It defines success; it grants nothing. Who may produce work
is still N3, whether delivery may happen is still N2 plus human approval, and
artifact state is still ProjectOS/N4. ``contract_hash`` is the AMC-CANON-1 hash
of the validated contract, so the same contract always binds the same way.

Requirement kinds:

* ``FACT_PRESENT``: a fact must appear in the delivered content. The fact is a
  claim-evidence relation (``RequiredFact``), not timeless truth; stale evidence
  makes the check NOT_MEASURED and the contract ESCALATE.
* ``PHRASE_FORBIDDEN``: none of the phrases may appear, matched after Unicode
  normalization so punctuation or separator tricks do not evade it.
* ``PATTERN``: regular-expression checks. Accepted only when a pinned
  linear-time engine is installed; there is none today, so a contract with a
  PATTERN requirement is rejected rather than run on a backtracking engine.
* ``HUMAN_REVIEW``: always NOT_MEASURED until an authorized human decides. The
  run's release approval is that decision, because its subject binds the
  contract hash.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

CONTRACT_SCHEMA_VERSION = "amc-delivery-contract/v1"
RequirementKind = Literal["FACT_PRESENT", "PHRASE_FORBIDDEN", "PATTERN", "HUMAN_REVIEW"]

# A pattern engine is usable only if it is both importable and pinned in the
# service's declared dependencies. None is pinned, so PATTERN stays rejected.
PINNED_PATTERN_ENGINE: Optional[str] = None


class ContractValidationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RequiredFact(_Strict):
    fact_id: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=2000)
    verification_ref: str = Field(min_length=1, max_length=200)
    evidence_hash: str = Field(min_length=1, max_length=128)
    verified_at: AwareDatetime
    valid_until: Optional[AwareDatetime] = None
    source_refs: tuple[str, ...] = Field(default=(), max_length=50)


class ContractRequirement(_Strict):
    requirement_id: str = Field(min_length=1, max_length=120)
    kind: RequirementKind
    description: str = Field(default="", max_length=2000)
    blocking: bool = True
    fact: Optional[RequiredFact] = None
    must_appear_verbatim: bool = True
    # Opt-in for non-verbatim facts: normalized token-boundary equivalence.
    # Without it a non-verbatim fact is NOT_MEASURED, never guessed.
    equivalence: Optional[Literal["normalized_text"]] = None
    phrases: tuple[str, ...] = Field(default=(), max_length=200)
    pattern: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _shape(self) -> "ContractRequirement":
        if self.kind == "FACT_PRESENT" and self.fact is None:
            raise ValueError("FACT_PRESENT requires a fact")
        if self.kind != "FACT_PRESENT" and self.fact is not None:
            raise ValueError("only FACT_PRESENT carries a fact")
        if self.kind == "PHRASE_FORBIDDEN":
            if not self.phrases or any(not p.strip() for p in self.phrases):
                raise ValueError("PHRASE_FORBIDDEN requires non-empty phrases")
            if any(len(p) > 300 for p in self.phrases):
                raise ValueError("phrases are limited to 300 characters")
        elif self.phrases:
            raise ValueError("only PHRASE_FORBIDDEN carries phrases")
        if self.kind == "PATTERN" and not self.pattern:
            raise ValueError("PATTERN requires a pattern")
        if self.kind != "PATTERN" and self.pattern is not None:
            raise ValueError("only PATTERN carries a pattern")
        return self


class DeliveryContract(_Strict):
    schema_version: Literal["amc-delivery-contract/v1"] = CONTRACT_SCHEMA_VERSION
    contract_id: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=300)
    requirements: tuple[ContractRequirement, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_ids(self) -> "DeliveryContract":
        ids = [r.requirement_id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("requirement_id values must be unique")
        return self


def contract_hash(contract: DeliveryContract) -> str:
    return canonical_hash(contract.model_dump(mode="json"))


def pattern_engine_available() -> bool:
    if PINNED_PATTERN_ENGINE is None:
        return False
    try:
        __import__(PINNED_PATTERN_ENGINE)
    except ImportError:
        return False
    return True


def validate_contract_for_execution(contract: DeliveryContract) -> None:
    """Checks that depend on the runtime, not just the schema."""

    if any(r.kind == "PATTERN" for r in contract.requirements) and not pattern_engine_available():
        raise ContractValidationError(
            "REJECTED_PATTERN_ENGINE_UNAVAILABLE",
            "PATTERN requirements need a pinned linear-time regex engine; none is installed",
        )
