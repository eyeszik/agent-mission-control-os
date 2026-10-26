"""ACE HASH_INTENT + FILTER: a PromptIR ``AssetRequirement`` -> ``IntentIR``. Deterministic, no model call.

Brief text is data. Instruction-like content ("ignore previous instructions",
"approve automatically", "publish this") is classified PROHIBITED and never changes
policy; capabilities the codebase does not have (photographic generation, 3D, video,
tracing a third-party mark) are UNSUPPORTED, never quietly approximated.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.prompt_compiler import AssetRequirement, PromptFamily

from .contracts import Classification, IntentIR, IntentItem, OutputProfile

DEFAULT_SIZE = (1200, 1500)
SUPPORTED_FAMILIES = {PromptFamily.image, PromptFamily.print}

_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)|system prompt|you are now|developer mode|"
    r"disregard (the )?(policy|rules)|<\s*script|javascript:|(auto(matically)?[- ]?approve|skip (the )?approval|"
    r"bypass (the )?(approval|review|policy))", re.I)
# Effect requests, not topics: "publish this", "email it to", "spend budget" -- but "an email signup line" is content.
_EFFECTS = re.compile(r"\b(publish(ed|ing)?\b(?! date)|post (it |this |them )?(to|on)|deploy|upload (it |this |them )?to|"
                      r"send (it |this |them )?to|email (it|this|them)\b|tweet (it|this)|purchase|buy (ads?|media)|"
                      r"spend (money|budget|\$))", re.I)
_THIRD_PARTY = re.compile(r"\b(trace|copy|replicate|recreate|clone)\b.{0,40}\b(logo|trademark|brand mark|artwork by|poster by)\b|"
                          r"\bin the style of [A-Z][a-z]+ [A-Z][a-z]+", re.I)
_UNSUPPORTED = (
    (re.compile(r"\b(photo(graph)?(ic|real(istic)?)? (generation|image)|photoreal(istic)?|text[- ]to[- ]image|diffusion)\b", re.I),
     "photographic generation has no provider adapter (PROVIDER_GAP)"),
    (re.compile(r"\b(3d (model|render|mesh)|path[- ]trac(ed|ing)|physically (based|accurate))\b", re.I),
     "3D/physically based rendering is not an AVIC backend"),
    (re.compile(r"\b(video|animation|animated|motion graphics?)\b", re.I),
     "motion belongs to the cinematic/motion capabilities, not the AVIC still compiler"),
)


# Letters from other scripts that render like Latin ones. Used only to build the copy the filters scan.
_CONFUSABLES = str.maketrans({
    **dict(zip("авекмнорстух", "abekmhopctyx")), **dict(zip("АВЕКМНОРСТХ", "ABEKMHOPCTX")),
    **dict(zip("іјѕһԁԛ", "ijsh" "dq")), **dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX")),
    **dict(zip("αινορτυχ", "aivoptux")),
})


# Glyphs that look like two Latin letters depending on the font: the filters scan the alternate reading as well.
_ALTERNATE = str.maketrans({"у": "u", "У": "U", "υ": "u", "Υ": "U"})


def scan_forms(text: str) -> tuple[str, ...]:
    primary = scan_form(text)
    alt = scan_form(text.translate(_ALTERNATE))
    return (primary,) if alt == primary else (primary, alt)


def scan_form(text: str) -> str:
    """The text as the filters see it: NFKC, invisible/format characters removed, unicode spaces collapsed, common
    lookalike letters folded to Latin. The stored text is never changed; this is only the copy that is matched."""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) not in {"Cf", "Cc", "Co", "Cn"} or ch in "\n\t")
    t = t.translate(_CONFUSABLES)
    return re.sub(r"\s+", " ", t)


def _classify(text: str) -> tuple[Classification, str]:
    forms = scan_forms(text)
    verdicts = [_classify_form(f) for f in forms]
    return next((v for v in verdicts if v[0] != Classification.VERIFIED), verdicts[0])


def _classify_form(text: str) -> tuple[Classification, str]:
    if _INJECTION.search(text):
        return Classification.PROHIBITED, "instruction-like content is data and cannot change policy"
    if _EFFECTS.search(text):
        return Classification.PROHIBITED, "external effects (publish, send, spend) are never inferred from a brief"
    if _THIRD_PARTY.search(text):
        return Classification.PROHIBITED, "reproducing a third-party mark or a named artist's style is not permitted"
    for pattern, why in _UNSUPPORTED:
        if pattern.search(text):
            return Classification.UNSUPPORTED, why
    return Classification.VERIFIED, ""


def _profile(req: AssetRequirement, requested: Optional[OutputProfile]) -> tuple[OutputProfile, Classification, str]:
    if requested is not None:
        return requested, Classification.VERIFIED, "requested explicitly"
    fmt = (req.production.format or "").lower()
    if fmt in {"png", "jpg", "jpeg", "webp"}:
        return OutputProfile.RASTER_FINAL, Classification.INFERRED, f"production.format={fmt}"
    return OutputProfile.NATIVE_EDITABLE_VECTOR, Classification.PROPOSED, "default for editorial vector work"


def compile_intent(req: AssetRequirement, *, style_profile: str, output_profile: Optional[OutputProfile] = None) -> IntentIR:
    items: list[IntentItem] = []

    def add(item_id: str, kind: str, text: str, source: str, *, base: Optional[Classification] = None, reason: str = ""):
        cls, why = _classify(text)
        if base is not None and cls == Classification.VERIFIED:
            cls, why = base, reason
        items.append(IntentItem(item_id=item_id, kind=kind, text=text[:600], classification=cls, source=source,
                                reason=(why or reason)[:300]))

    add("goal.objective", "goal", req.objective, "objective")
    add("goal.audience", "goal", req.audience, "audience")
    for i, text in enumerate(req.content_requirements):
        add(f"req.content.{i}", "hard_requirement", text, f"content_requirements[{i}]")
    for i, text in enumerate(req.quality_constraints):
        add(f"acc.quality.{i}", "acceptance", text, f"quality_constraints[{i}]")
    for i, text in enumerate(req.negative_constraints):
        add(f"neg.{i}", "negative", text, f"negative_constraints[{i}]")
    exact: list[str] = []
    for i, text in enumerate(req.exact_text):
        # Exact text is rendered verbatim as escaped SVG text. Injection-like wording stays text, but is flagged.
        cls, why = _classify(text)
        if cls == Classification.PROHIBITED and any(_INJECTION.search(f) for f in scan_forms(text)):
            items.append(IntentItem(item_id=f"text.{i}", kind="exact_text", text=text[:600], classification=cls,
                                    source=f"exact_text[{i}]", reason=why))
            continue
        exact.append(text)
        items.append(IntentItem(item_id=f"text.{i}", kind="exact_text", text=text[:600], classification=Classification.VERIFIED,
                                source=f"exact_text[{i}]", reason="must survive character-for-character"))
    if req.family not in SUPPORTED_FAMILIES:
        items.append(IntentItem(item_id="profile.family", kind="output_profile", text=req.family.value,
                                classification=Classification.UNSUPPORTED, source="family",
                                reason="AVIC compiles still IMAGE/PRINT assets only"))
    profile, pcls, preason = _profile(req, output_profile)
    if profile in {OutputProfile.RASTER_FINAL, OutputProfile.HYBRID_SVG}:
        pcls, preason = Classification.UNSUPPORTED, f"{profile.value}: no raster generation provider; never substituted"
    items.append(IntentItem(item_id="profile.output", kind="output_profile", text=profile.value, classification=pcls,
                            source="production.format" if output_profile is None else "request", reason=preason))
    items.append(IntentItem(item_id="mutable.palette", kind="mutable", text="palette roles from the brand projection",
                            classification=Classification.PROPOSED, source="compiler", reason="brand-governed default"))
    items.append(IntentItem(item_id="mutable.layout", kind="mutable", text="grid layout from the style profile",
                            classification=Classification.PROPOSED, source="compiler", reason="style-profile default"))
    w = req.production.width or DEFAULT_SIZE[0]
    h = req.production.height or DEFAULT_SIZE[1]
    return IntentIR(asset_id=req.asset_id, requirement_hash=canonical_hash(req.model_dump(mode="json")), output_profile=profile,
                    style_profile=style_profile, width=int(w), height=int(h), items=tuple(items), exact_text=tuple(exact))


__all__ = ["SUPPORTED_FAMILIES", "compile_intent", "scan_form", "scan_forms"]
