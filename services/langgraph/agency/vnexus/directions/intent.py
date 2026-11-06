"""Stages 1-2: intake decisions and the shared CreativeIntent, compiled through the existing prompt compiler.

Pure: no storage, no provider. The shared intent is compiled once per (genome resolution, brief, compiler version)
and carries two separate instruction sets:

* image instructions, one per bounded, conceptually distinct direction slot. Exact identity text is deliberately
  kept OUT of raster generation: generated lettering is never the source of truth for a name.
* vector instructions: palette roles, approved faces, the exact text to set from the approved type, geometry and
  safety rules for the reconstruction stage.

Brief text is data. Instruction-like text, external-effect requests and third-party marks are PROHIBITED and block
the intent (detection reuses the AVIC intent filters). ``None`` is a gap; ``"@none"`` is an intentional NONE.
"""

from __future__ import annotations

from typing import Any, Optional

from services.langgraph.agency.avic.intent import _EFFECTS, _INJECTION, _THIRD_PARTY, scan_forms
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.prompt_compiler import PromptFamily

from ..bridge import PALETTE_ROLES, GenomeProjection
from ..prompt_genome import PromptGenomeDocument, compile_genome_prompt
from .records import (INTENT_COMPILER_VERSION, NONE, AssetRole, CreativeIntent, DirectionBrief, FieldDecision, SlotInstruction,
                      record_id, vector_need)

# Generic, brand-free exploration axes used only when the genome's grammars and the brief give fewer directions than
# requested. They name an approach, never a brand's geometry, palette or composition.
GENERIC_AXES = ("reduction to the fewest distinct forms", "negative-space emphasis", "modular construction from repeated units",
                "single continuous gesture")
COMPOSE_ROLES = frozenset({AssetRole.LOGO_MARK, AssetRole.ICON})


def _prohibited(text: str) -> Optional[str]:
    for form in scan_forms(text):
        if _INJECTION.search(form):
            return "instruction-like content is data and cannot change policy"
        if _EFFECTS.search(form):
            return "external effects (publish, send, spend) are never inferred from a brief"
        if _THIRD_PARTY.search(form):
            return "reproducing a third-party mark or a named artist's style is not permitted"
    return None


def _decision(field: str, value: Any, consequence: str) -> FieldDecision:
    if value is None or value == [] or value == "":
        return FieldDecision(field=field, status="UNKNOWN", consequence=consequence)
    if value == NONE:
        return FieldDecision(field=field, status="NONE")
    return FieldDecision(field=field, status="VALUE")


def intake(brief: DirectionBrief) -> tuple[tuple[FieldDecision, ...], tuple[str, ...]]:
    decisions = (
        _decision("audience", brief.audience, "review cannot judge audience relevance (lens 01) without it"),
        _decision("category", brief.category, "category overlap (lens 10) stays UNKNOWN"),
        _decision("exact_text", brief.exact_text, "the exact identity text gate stays UNKNOWN; decide the text or @none"),
        _decision("rights_constraints", brief.rights_constraints, "rights evidence must come from each candidate's import record"),
        _decision("privacy_constraints", brief.privacy_constraints, "privacy review relies on the default [PII] rules only"),
        _decision("applications", brief.applications, "application fitness (lens 12) cannot be assessed"),
    )
    texts = [brief.objective, *(t for t in (brief.audience, brief.category, brief.rights_constraints, brief.privacy_constraints)
                                if isinstance(t, str) and t != NONE),
             *brief.directions, *brief.emotional_targets, *(brief.exact_text if isinstance(brief.exact_text, list) else []),
             *(brief.applications if isinstance(brief.applications, list) else [])]
    prohibited = sorted({why for t in texts if (why := _prohibited(t))})
    return decisions, tuple(prohibited)


def directions(brief: DirectionBrief, p: GenomeProjection) -> list[str]:
    out = list(dict.fromkeys(d.strip() for d in brief.directions if d.strip()))
    for grammar, _ in sorted(p.grammar_weights().items(), key=lambda kv: (-kv[1], kv[0])):
        if len(out) >= brief.candidate_count:
            break
        out.append(f"led by the approved {grammar.replace('_', ' ')} grammar")
    for axis in GENERIC_AXES:
        if len(out) >= brief.candidate_count:
            break
        if axis not in out:
            out.append(axis)
    return out[:brief.candidate_count]


def _marks_for(brief_hash: str, count: int, approved_mark: Optional[str]) -> list[str]:
    from services.langgraph.agency.foundry.genome import MARKS

    # Deterministic rotation by the brief hash; the approved mark (if any) is not re-proposed as a "new" direction.
    pool = [m for m in MARKS if m != approved_mark] or list(MARKS)
    start = int(brief_hash[:8], 16) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(count)]


def compile_intent(*, tenant_id: str, project_id: str, brand_id: str, scope: str, scope_ref: str, projection: GenomeProjection,
                   brand_constraints: list[dict[str, Any]], brief: DirectionBrief) -> CreativeIntent:
    p = projection
    decisions, prohibited = intake(brief)
    brief_hash = canonical_hash(brief.model_dump(mode="json"))
    dependency_hash = canonical_hash({"resolution": p.resolution_hash, "genome_ref": p.genome_ref, "brief": brief_hash,
                                      "compiler": INTENT_COMPILER_VERSION})
    palette = {r: p.values.get(f"visual.color.{r}") for r in PALETTE_ROLES if isinstance(p.values.get(f"visual.color.{r}"), str)}
    exact = list(brief.exact_text) if isinstance(brief.exact_text, list) else []
    negatives = ["no lettering, letters, words or numerals in the image: identity text is set later from the approved type",
                 "no third-party logos, trademarks or recognisable real people", "no photographs of identifiable individuals",
                 "no embedded signatures or watermarks"]
    if brief.asset_role in (AssetRole.LOGO_MARK, AssetRole.ICON):
        negatives.append("flat shapes only: no gradients, textures or photographic detail")
    doc = PromptGenomeDocument(intent=brief.objective, family=PromptFamily.image, asset_type=brief.asset_role.value.lower(),
                               audience=brief.audience if isinstance(brief.audience, str) and brief.audience != NONE else "",
                               constraints=tuple(negatives), exact_text=(),
                               output={"width": brief.width, "height": brief.height})
    compiled = compile_genome_prompt(p, f"direction-{brief.asset_role.value.lower()}", doc, brand_constraints=brand_constraints)
    blockers = list(prohibited)
    if compiled["final_state"] != "PROMPT_PACKAGE_READY":
        blockers.append(f"PROMPT_COMPILER_{compiled['final_state']}: " + ", ".join(compiled.get("missing_genome_keys") or []))
    master = (compiled.get("package") or {}).get("generic_master_prompt", "")
    dirs = directions(brief, p)
    marks = _marks_for(brief_hash, len(dirs), p.values.get("visual.logo.mark")) if brief.asset_role in COMPOSE_ROLES else []
    slots = []
    if not blockers:
        for i, direction in enumerate(dirs):
            prompt = f"{master}\n\nDirection {i + 1} of {len(dirs)}: {direction}. Keep this direction conceptually distinct from the others."
            negative = "; ".join(negatives)
            params = {"width": brief.width, "height": brief.height, "seed": None, "count": 1}
            slots.append(SlotInstruction(slot=i + 1, direction=direction, prompt=prompt, negative_prompt=negative, parameters=params,
                                         prompt_hash=canonical_hash({"prompt": prompt, "negative": negative, "parameters": params}),
                                         compose_mark=marks[i] if marks else None))
    face = p.values.get("visual.typography.display")
    vector = {
        "need": vector_need(brief.asset_role).value,
        "palette_roles": palette,
        "fills": "approved palette role colours only; no gradients unless the genome approves them",
        "exact_text": exact,
        "exact_text_rule": ("set each string verbatim from the approved display face as editable <text>; never trace generated lettering"
                            if exact else ("text decided NONE" if brief.exact_text == NONE else "exact text UNKNOWN: decide it before release")),
        "approved_faces": {"display": face, "body": p.values.get("visual.typography.body")},
        "geometry": ["native shapes or paths only; an embedded raster is never vector", "explicit viewBox; no clipping of the mark",
                     "closed counters stay open at the smallest application size", "no scripts, external references or foreignObject"],
        "minimum_sizes": [a for a in (brief.applications if isinstance(brief.applications, list) else []) if any(c.isdigit() for c in a)],
        "protected": sorted({c["key"] for c in brand_constraints if c["kind"] == "IMMUTABLE"}),
    }
    shared = {"objective": brief.objective, "audience": brief.audience, "category": brief.category,
              "applications": brief.applications, "emotional_targets": brief.emotional_targets or _tone(p),
              "emotional_targets_source": "brief" if brief.emotional_targets else "genome verbal.voice.tone",
              "imagery_style": p.values.get("visual.imagery.style"), "candidate_count": len(dirs), "budget_minor": brief.budget_minor,
              "references": [r.model_dump(mode="json") for r in brief.references]}
    return CreativeIntent(intent_id=record_id("vdi", {"tenant": tenant_id, "project": project_id, "brand": brand_id, "scope": scope,
                                                      "scope_ref": scope_ref, "dep": dependency_hash}),
                          tenant_id=tenant_id, project_id=project_id, brand_id=brand_id, scope=scope, scope_ref=scope_ref,
                          genome_ref=p.genome_ref, resolution_hash=p.resolution_hash, asset_role=brief.asset_role,
                          vector_need=vector_need(brief.asset_role), brief=brief, brief_hash=brief_hash, field_decisions=decisions,
                          prohibited=prohibited, status="BLOCKED_INPUT" if blockers else "READY", blockers=tuple(blockers),
                          shared=shared,
                          prompt_compiler={"final_state": compiled["final_state"], "package_hash": compiled.get("package_hash"),
                                           "missing_genome_keys": compiled.get("missing_genome_keys") or [],
                                           "generation_firewall": compiled.get("generation_firewall")},
                          image_instructions=tuple(slots), vector_instructions=vector, dependency_hash=dependency_hash)


def _tone(p: GenomeProjection) -> list[str]:
    tone = p.values.get("verbal.voice.tone")
    if isinstance(tone, list):
        return [str(t) for t in tone][:6]
    return [t.strip() for t in str(tone).split(",") if t.strip()][:6] if tone else []


def handoff_package(intent: CreativeIntent) -> dict[str, Any]:
    """The manual route: everything an operator needs to generate elsewhere under their own authorization, and what
    to send back. Nothing here calls a provider."""
    return {"intent_id": intent.intent_id, "genome_ref": intent.genome_ref, "asset_role": intent.asset_role.value,
            "status": intent.status, "blockers": list(intent.blockers),
            "slots": [{"slot": s.slot, "direction": s.direction, "prompt": s.prompt, "negative_prompt": s.negative_prompt,
                       "parameters": s.parameters, "prompt_hash": s.prompt_hash} for s in intent.image_instructions],
            "vector_instructions": intent.vector_instructions,
            "return": {"formats": ["image/png", "image/svg+xml"], "max_bytes": 12_000_000,
                       "record": ["provider", "model", "model_version", "seed", "parameters", "generated_at", "job_ref", "receipt_ref",
                                  "cost_minor", "currency", "rights_basis", "reference_ids"],
                       "provenance": "USER_REPORTED: the importer's statement; this server verifies only the bytes it stores"},
            "rules": ["use only an account and terms you are authorized to use; this package grants no entitlement",
                      "do not include identity text in generated images", "do not upload private or [PII] material to a provider"]}


__all__ = ["COMPOSE_ROLES", "GENERIC_AXES", "compile_intent", "directions", "handoff_package", "intake"]
