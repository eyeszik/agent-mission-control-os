"""Five presentation systems, rendered through the website line (not a second renderer).

A presentation system is a set of content slots and layout variants. ``compose_board``
fills the slots into a ``WebsiteBrief``; from there the board is an ordinary UCPO site:
requirements, PSEM genome and tokens, site IR, source, sandboxed build, browser QA,
coverage and release proof. Versioning, preview, comparison and export are the site's.
The operator supplies all copy; a missing required slot is an error, never filler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ImageAsset, Item, PageBrief, SectionBrief, WebsiteBrief
from .requirements import compile_requirements, diff_requirements


@dataclass(frozen=True)
class Slot:
    slot_id: str
    kind: str             # SectionKind used to render it
    required: bool
    max_items: int = 0    # >0: the slot takes items
    image: bool = False


@dataclass(frozen=True)
class PresentationSystem:
    system_id: str
    name: str
    purpose: str
    slots: tuple[Slot, ...]
    variants: dict[str, tuple[str, ...]]   # variant -> slot order

    def describe(self) -> dict:
        return {"system_id": self.system_id, "name": self.name, "purpose": self.purpose,
                "slots": [s.__dict__ for s in self.slots], "variants": {k: list(v) for k, v in self.variants.items()},
                "supports": ["content slots", "genome/tokens", "layout variants", "assets", "responsive behaviour", "preview",
                             "validation", "comparison", "versioning", "export"]}


SYSTEMS: dict[str, PresentationSystem] = {s.system_id: s for s in (
    PresentationSystem("visual_identity_board", "Visual Identity Board", "Mark, palette, type and usage on one board.",
                       (Slot("identity", "hero", True, image=True), Slot("palette", "index", True, max_items=6),
                        Slot("typography", "editorial", True), Slot("usage", "index", False, max_items=6),
                        Slot("rationale", "statement", False)),
                       {"default": ("identity", "palette", "typography", "usage", "rationale"),
                        "type_first": ("identity", "typography", "palette", "usage", "rationale")}),
    PresentationSystem("editorial_design_system", "Editorial Design System", "Grid, hierarchy and editorial components.",
                       (Slot("cover", "hero", True), Slot("grid", "editorial", True), Slot("hierarchy", "index", True, max_items=6),
                        Slot("components", "index", False, max_items=8), Slot("principles", "statement", False)),
                       {"default": ("cover", "grid", "hierarchy", "components", "principles")}),
    PresentationSystem("conceptual_photography_board", "Conceptual Photography Board",
                       "Plates with captions and technical annotations; photographs must be licensed or owned.",
                       (Slot("lead_plate", "hero", True, image=True), Slot("series", "gallery", True, image=True),
                        Slot("annotations", "index", True, max_items=8), Slot("statement", "statement", False)),
                       {"default": ("lead_plate", "series", "annotations", "statement"),
                        "annotations_first": ("lead_plate", "annotations", "series", "statement")}),
    PresentationSystem("experimental_graphics_collection", "Experimental Graphics Collection",
                       "A numbered collection of graphic studies.",
                       (Slot("opening", "hero", True, image=True), Slot("studies", "gallery", True, image=True),
                        Slot("index", "index", True, max_items=12), Slot("method", "editorial", False)),
                       {"default": ("opening", "studies", "index", "method")}),
    PresentationSystem("digital_experience_board", "Digital Experience/UI Board", "Flows, states and UI principles.",
                       (Slot("overview", "hero", True), Slot("flows", "index", True, max_items=8),
                        Slot("states", "index", True, max_items=10), Slot("accessibility", "editorial", True),
                        Slot("next", "contact", False)),
                       {"default": ("overview", "flows", "states", "accessibility", "next")}),
)}


class BoardError(ValueError):
    pass


def compose_board(system_id: str, *, organization: str, title: str, description: str, slots: dict[str, dict[str, Any]],
                  variant: str = "default", images: tuple[dict, ...] = (), seed: int | None = None) -> WebsiteBrief:
    system = SYSTEMS.get(system_id)
    if system is None:
        raise BoardError(f"unknown presentation system {system_id}")
    if variant not in system.variants:
        raise BoardError(f"unknown variant {variant} for {system_id}")
    defined = {s.slot_id: s for s in system.slots}
    unknown = sorted(set(slots) - set(defined))
    if unknown:
        raise BoardError(f"unknown slots {unknown}")
    missing = sorted(s.slot_id for s in system.slots if s.required and s.slot_id not in slots)
    if missing:
        raise BoardError(f"required slots not filled: {missing}")
    sections = []
    for n, slot_id in enumerate(s for s in system.variants[variant] if s in slots):
        slot, value = defined[slot_id], slots[slot_id]
        items = tuple(Item.model_validate(i) for i in value.get("items", ()))
        if slot.max_items and not items and slot.required:
            raise BoardError(f"slot {slot_id} needs items")
        if len(items) > max(slot.max_items, 0):
            raise BoardError(f"slot {slot_id} takes at most {slot.max_items} items")
        if value.get("image") and not slot.image:
            raise BoardError(f"slot {slot_id} does not take an image")
        sections.append(SectionBrief(kind=slot.kind, heading=value["heading"], body=value.get("body", ""),
                                     label=value.get("label", f"{n + 1:02d} {slot_id.upper().replace('_', ' ')}"[:40]),
                                     items=items, image=value.get("image"), anchor=slot_id.replace("_", "-")))
    return WebsiteBrief(organization=organization, pages=(PageBrief(slug="index", title=title, description=description,
                                                                    sections=tuple(sections)),),
                        images=tuple(ImageAsset.model_validate(i) for i in images), seed=seed,
                        tagline=f"{SYSTEMS[system_id].name}: {description}"[:140])


def compare_boards(a: WebsiteBrief, b: WebsiteBrief) -> dict[str, list[str]]:
    return diff_requirements(compile_requirements(a, project_ref="compare"), compile_requirements(b, project_ref="compare"))


EXAMPLES: dict[str, dict[str, Any]] = {
    "visual_identity_board": {
        "organization": "Halden Fen", "title": "Identity board", "description": "The fictional Halden Fen identity on one page.",
        "images": ({"asset_id": "mark-study", "alt": "A red circle and grey hairlines on a charcoal ground", "motif_seed": 2},),
        "slots": {
            "identity": {"heading": "One circle, one line", "body": "The mark is a kiln seen from above: a single circle over a horizon.",
                         "image": "mark-study"},
            "palette": {"heading": "Six colours", "items": [{"title": "Charcoal", "body": "Ground for every accent."},
                                                           {"title": "Paper", "body": "Ground for long reading."},
                                                           {"title": "Signal red", "body": "One accent, only on charcoal."}]},
            "typography": {"heading": "Neo-grotesk, set large", "body": "Headlines are set tight and large; body text stays at a comfortable reading size."},
        }},
    "editorial_design_system": {
        "organization": "Halden Fen", "title": "Editorial system", "description": "Grid and hierarchy rules for the fictional studio.",
        "slots": {
            "cover": {"heading": "A twelve-column page", "body": "Every page is built on twelve columns with protected margins."},
            "grid": {"heading": "Columns and gutters", "body": "Headlines span nine columns; reading text sits in seven, offset by three."},
            "hierarchy": {"heading": "Three levels", "items": [{"title": "Macro", "body": "One headline per section."},
                                                              {"title": "Meso", "body": "Body text and lists."},
                                                              {"title": "Micro", "body": "Serial numbers and labels."}]},
        }},
    "conceptual_photography_board": {
        "organization": "Halden Fen", "title": "Plate studies", "description": "Procedural plates standing in for licensed photography.",
        "images": ({"asset_id": "plate-a", "alt": "A red circle above grey lines on charcoal", "motif_seed": 5},
                   {"asset_id": "plate-b", "alt": "Short paper-white bars below grey lines on charcoal", "motif_seed": 9}),
        "slots": {
            "lead_plate": {"heading": "The kiln at dusk", "body": "Procedural study. No photograph is generated here.", "image": "plate-a"},
            "series": {"heading": "Second plate", "body": "A quieter variation on the same motif.", "image": "plate-b"},
            "annotations": {"heading": "Annotations", "items": [{"title": "Plate A", "body": "Accent placed in the upper third."},
                                                               {"title": "Plate B", "body": "No accent; paper bars only."}]},
        }},
    "experimental_graphics_collection": {
        "organization": "Halden Fen", "title": "Graphic studies", "description": "Numbered studies of one motif.",
        "images": ({"asset_id": "study-one", "alt": "Hairlines and one red circle on charcoal", "motif_seed": 11},
                   {"asset_id": "study-two", "alt": "Hairlines and short bars on charcoal", "motif_seed": 12}),
        "slots": {
            "opening": {"heading": "Studies in one circle", "body": "Each study changes one axis at a time.", "image": "study-one"},
            "studies": {"heading": "Study two", "body": "The circle is removed; the bars carry the rhythm.", "image": "study-two"},
            "index": {"heading": "Index", "items": [{"title": "Study one", "body": "Circle, three lines."},
                                                   {"title": "Study two", "body": "Bars, three lines."}]},
        }},
    "digital_experience_board": {
        "organization": "Halden Fen", "title": "Visit booking UI", "description": "Flows and states for booking a studio visit.",
        "slots": {
            "overview": {"heading": "Booking a visit", "body": "One short flow: choose a day, leave a name, receive a confirmation."},
            "flows": {"heading": "Flows", "items": [{"title": "Choose a day", "body": "Saturdays are listed first."},
                                                    {"title": "Confirm", "body": "A summary before anything is sent."}]},
            "states": {"heading": "States", "items": [{"title": "Empty", "body": "No dates yet: say when the next ones open."},
                                                      {"title": "Error", "body": "Say what failed and how to retry."}]},
            "accessibility": {"heading": "Accessibility", "body": "Every control is reachable by keyboard and has a visible focus ring."},
        }},
}


def example_brief(system_id: str) -> WebsiteBrief:
    ex = EXAMPLES[system_id]
    return compose_board(system_id, organization=ex["organization"], title=ex["title"], description=ex["description"],
                         slots=ex["slots"], images=ex.get("images", ()), seed=7)


__all__ = ["EXAMPLES", "SYSTEMS", "BoardError", "PresentationSystem", "Slot", "compare_boards", "compose_board", "example_brief"]
