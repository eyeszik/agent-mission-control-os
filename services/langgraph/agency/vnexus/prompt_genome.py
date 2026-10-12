"""VNEXUS prompt genome: versioned, constraint-inheriting prompt definitions over the existing prompt compiler.

A prompt genome does not compile prompts itself. It projects the approved
brand genome into the compiler's ``BrandCore`` (refusing, with the missing
keys listed, when the genome does not carry what the compiler needs), maps
its own fields onto an ``AssetRequirement``, and runs the unchanged five-pass
``compile_prompt_packages``. The terminal state stays ``PROMPT_PACKAGE_READY``;
nothing here calls a provider.

Original source prompts are imported byte for byte with a SHA-256 of the
exact text. The project references 14 originals that are not in this
repository; the inventory reports how many were actually imported and never
fills the gap.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any, Optional

from pydantic import Field, field_validator

from services.langgraph.agency.artifacts.brand import BrandCore
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.prompt_compiler import (
    AssetRequirement,
    CompilerState,
    ProductionSpec,
    PromptCompilerRequest,
    PromptFamily,
    ProviderCapabilityName,
    ReferenceRole,
    ReferenceSpec,
    compile_prompt_packages,
)

from .bridge import GenomeProjection
from .genome import _Strict

PROMPT_GENOME_SCHEMA = "amc-vnexus-prompt-genome/v1"
EXPECTED_ORIGINAL_SOURCES = 14  # referenced by the project brief; none are present in the repository


class SourceKind(str, Enum):
    ORIGINAL_IMPORT = "ORIGINAL_IMPORT"
    DERIVED = "DERIVED"
    AUTHORED = "AUTHORED"


class ReferenceBinding(_Strict):
    ref_id: str = Field(min_length=1, max_length=200)
    role: ReferenceRole
    priority: int = Field(default=1, ge=1, le=10)


class EvaluationRecord(_Strict):
    at_version: int
    package_hash: Optional[str]
    final_state: str
    checks: dict[str, bool]


class PromptGenomeDocument(_Strict):
    schema_version: str = PROMPT_GENOME_SCHEMA
    intent: str = Field(min_length=1, max_length=1000)
    family: PromptFamily
    asset_type: str = Field(min_length=1, max_length=120)
    audience: str = Field(default="", max_length=300)
    channel: str = Field(default="web", max_length=60)
    destination: str = Field(default="unspecified", max_length=200)
    constraints: tuple[str, ...] = Field(default=(), max_length=40)          # negative constraints this prompt adds
    quality_rules: tuple[str, ...] = Field(default=(), max_length=40)        # validation rules
    exact_text: tuple[str, ...] = Field(default=(), max_length=10)           # must survive verbatim
    creative_dna: tuple[str, ...] = Field(default=(), max_length=60)         # genome keys this prompt depends on
    references: tuple[ReferenceBinding, ...] = Field(default=(), max_length=12)
    capabilities: tuple[ProviderCapabilityName, ...] = ()
    output: dict[str, Any] = Field(default_factory=dict)                     # ProductionSpec fields
    template_of: Optional[str] = None                                        # prompt_id this one derives from
    source_text: Optional[str] = Field(default=None, max_length=50_000)      # byte-preserved original, when imported

    @field_validator("output")
    @classmethod
    def _output(cls, value: dict[str, Any]) -> dict[str, Any]:
        ProductionSpec.model_validate(value)
        return value

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def brand_core_from(p: GenomeProjection) -> tuple[Optional[BrandCore], list[str]]:
    """The compiler's BrandCore from approved genome values only. Missing keys are returned, never defaulted."""
    p = p.fresh()
    need = {"strategy.positioning.statement": p.get("strategy.positioning.statement"), "verbal.voice.tone": p.get("verbal.voice.tone"),
            "visual.typography.display": p.get("visual.typography.display"), "visual.imagery.style": p.get("visual.imagery.style"),
            "visual.motion.pace": p.get("visual.motion.pace"), "visual.motion.reduced_motion": p.get("visual.motion.reduced_motion"),
            "visual.logo.min_size": p.get("visual.logo.min_size"), "visual.logo.clear_space": p.get("visual.logo.clear_space"),
            "visual.motion.emphasis": p.get("visual.motion.emphasis")}
    missing = sorted(k for k, v in need.items() if v in (None, "", []))
    palette = p.palette()
    if palette is None:
        missing.append("visual.color.{ink,paper,accent,accent_2,muted}")
    if missing:
        return None, missing
    try:
        core = _brand_core(p, need, palette)
    except ValueError as exc:  # pydantic ValidationError subclasses ValueError
        return None, [f"BRAND_CORE_REJECTED: {str(exc).splitlines()[1].strip() if len(str(exc).splitlines()) > 1 else exc}"]
    return core, []


def _brand_core(p: GenomeProjection, need: dict[str, Any], palette: dict[str, str]) -> BrandCore:
    tone = need["verbal.voice.tone"]
    tones = tone if isinstance(tone, list) else [t.strip() for t in str(tone).split(",") if t.strip()]
    dos, donts = p.get("verbal.voice.dos"), p.get("verbal.voice.donts")
    emphasis = need["visual.motion.emphasis"]
    return BrandCore(
        brand_name=p.brand_name, positioning_essence=str(need["strategy.positioning.statement"]),
        voice={"tone_attributes": tones, "writing_dos": list(dos) if isinstance(dos, list) else ([dos] if dos else []),
               "writing_donts": list(donts) if isinstance(donts, list) else ([donts] if donts else [])},
        color_story=[{"role": role, "description": f"{role} colour from the approved brand genome", "reference_hex": value}
                     for role, value in palette.items()],
        typography_direction=f"Display {need['visual.typography.display']}; body {p.text('visual.typography.body', 'as approved')}",
        imagery_style=str(need["visual.imagery.style"]),
        motion={"pace": str(need["visual.motion.pace"]),
                "emphasis_moments": list(emphasis) if isinstance(emphasis, list) else [str(emphasis)],
                "reduced_motion_fallback": str(need["visual.motion.reduced_motion"])},
        logo_lockups=[{"lockup_id": "primary", "lockup_type": "primary", "usage_context": "Default digital and print mark.",
                       "minimum_size": str(need["visual.logo.min_size"]), "clear_space_rule": str(need["visual.logo.clear_space"]),
                       "placement_notes": p.text("visual.logo.placement", "No placement notes in the approved genome."),
                       "generation_reference": f"Approved mark '{p.text('visual.logo.mark', 'primary')}' rendered from vector; never regenerated"}],
    )


def inherited_constraints(resolution_constraints: list[dict[str, Any]]) -> list[str]:
    """Brand constraints as plain-language negative constraints the compiler carries into every package."""
    out = []
    for c in resolution_constraints:
        if c["kind"] == "IMMUTABLE":
            out.append(f"Do not alter {c['key']} (approved and locked)")
        elif c["kind"] == "ALLOWED_VALUES":
            out.append(f"{c['key']} must be one of {c['params']['values']}")
        elif c["kind"] == "MIN_CONTRAST":
            out.append(f"Keep {c['key']} against {c['params']['against']} at or above {c['params']['ratio']}:1")
    return sorted(set(out))


def compile_genome_prompt(p: GenomeProjection, prompt_id: str, doc: PromptGenomeDocument, *,
                          brand_constraints: list[dict[str, Any]]) -> dict[str, Any]:
    core, missing = brand_core_from(p)
    if core is None:
        state = "GENOME_REJECTED_BY_COMPILER" if any(m.startswith("BRAND_CORE_REJECTED") for m in missing) else "GENOME_INCOMPLETE"
        return {"final_state": state, "missing_genome_keys": missing, "package": None,
                "note": "the approved genome lacks what the prompt compiler requires; nothing was defaulted"}
    inherited = inherited_constraints(brand_constraints)
    requirement = AssetRequirement(
        asset_id=prompt_id, family=doc.family, asset_type=doc.asset_type, objective=doc.intent,
        audience=doc.audience or p.text("strategy.audience.primary", "unspecified audience"), channel=doc.channel,
        destination=doc.destination, required_capabilities=list(doc.capabilities), negative_constraints=list(doc.constraints) + inherited,
        quality_constraints=list(doc.quality_rules), exact_text=list(doc.exact_text),
        references=[ReferenceSpec(ref_id=r.ref_id, role=r.role, priority=r.priority) for r in doc.references],
        production=ProductionSpec(**doc.output))
    result = compile_prompt_packages(PromptCompilerRequest(project_name=f"{p.brand_name} / {prompt_id}", brand_core=core,
                                                           asset_requirements=[requirement], content=doc.intent))
    package = result.prompt_packages[0].model_dump(mode="json") if result.prompt_packages else None
    checks = {"terminal_state_ready": result.final_state is CompilerState.prompt_package_ready,
              "exact_text_preserved": all(t in (package or {}).get("generic_master_prompt", "") for t in doc.exact_text) if package else False,
              "inherited_constraints_carried": all(c in str(package) for c in inherited) if package else not inherited}
    return {"final_state": result.final_state.value, "package": package, "package_hash": package.get("prompt_hash") if package else None,
            "inherited_constraints": inherited, "checks": checks, "generation_firewall": result.generation_firewall,
            "gaps": [g.model_dump(mode="json") for g in result.gaps], "missing_genome_keys": []}


def adapt(package: dict[str, Any], *, target: str) -> dict[str, Any]:
    """Provider-family rendering of a compiled package. Formatting only: no provider is called or assumed available."""
    master = package.get("generic_master_prompt", "")
    spec = package.get("asset_spec", {})
    production = spec.get("production", {}) if isinstance(spec, dict) else {}
    negatives = [n for n in (spec.get("negative_constraints") or [])] if isinstance(spec, dict) else []
    params = {k: production.get(k) for k in ("width", "height", "aspect_ratio", "duration_seconds", "fps") if production.get(k)}
    if target == "generic_text_to_image":
        body = {"prompt": master, "negative_prompt": "; ".join(negatives), "parameters": params}
    elif target == "generic_text_to_video":
        body = {"prompt": master, "negative_prompt": "; ".join(negatives), "parameters": params,
                "note": "camera and timing come from the package's storyboard stages"}
    elif target == "structured_json":
        body = {"instruction": master, "constraints": negatives, "output": params}
    else:
        raise ValueError(f"unknown adaptation target {target}")
    return {"target": target, "body": body, "adapted_hash": canonical_hash(body), "provider_called": False}


_WORD = re.compile(r"[a-z0-9]+")


def compare(a: PromptGenomeDocument, b: PromptGenomeDocument) -> dict[str, Any]:
    """Field-level differences plus a lexical overlap of the intents (labelled as lexical, not as meaning)."""
    da, db = a.model_dump(mode="json"), b.model_dump(mode="json")
    changed = sorted(k for k in set(da) | set(db) if da.get(k) != db.get(k))
    wa, wb = set(_WORD.findall(a.intent.lower())), set(_WORD.findall(b.intent.lower()))
    overlap = len(wa & wb) / len(wa | wb) if wa | wb else 1.0
    return {"changed_fields": changed, "intent_lexical_overlap": round(overlap, 4),
            "constraints_added": sorted(set(b.constraints) - set(a.constraints)),
            "constraints_removed": sorted(set(a.constraints) - set(b.constraints)),
            "note": "lexical overlap of words, not a judgement of meaning"}


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inventory(imported: list[dict[str, Any]]) -> dict[str, Any]:
    originals = [r for r in imported if r["source_kind"] == SourceKind.ORIGINAL_IMPORT.value]
    ids = sorted({r["prompt_id"] for r in originals})
    missing = max(0, EXPECTED_ORIGINAL_SOURCES - len(ids))
    return {"expected_originals": EXPECTED_ORIGINAL_SOURCES, "imported_originals": len(ids), "imported_ids": ids, "missing": missing,
            "status": "COMPLETE" if missing == 0 else ("PARTIAL_IMPORT" if ids else "SOURCE_REQUIRED"),
            "note": "missing originals are never reconstructed; import the exact source text to fill a slot"}


__all__ = ["EXPECTED_ORIGINAL_SOURCES", "EvaluationRecord", "PROMPT_GENOME_SCHEMA", "PromptGenomeDocument", "ReferenceBinding",
           "SourceKind", "adapt", "brand_core_from", "compare", "compile_genome_prompt", "inherited_constraints", "inventory",
           "source_hash"]
