"""Brand book compiler: authorized brand projection + page manifest -> per-page packages and readable prompts.

Pure and deterministic: identical pinned inputs give identical packages and
hashes. No provider, renderer, storage or publication call happens here.

* Visible copy is separated from instructions. A copy block carries the exact
  value from the genome (Unicode, punctuation and case untouched) or a template
  string, and names its source.
* ``NONE`` / ``NOT_APPLICABLE`` decisions print as labelled annotations, never as copy.
* Drafts label gaps; ``PRODUCTION`` refuses any page with a blocking gap and any
  unresolved template token.
* Each page carries its dependency hash: the values of the keys it declares, the
  style keys, the canonical asset hashes it places, the template/compiler versions,
  mode and locale. Unchanged dependency hashes are what the incremental build reuses.
* Exported standalone prompts are self-contained; inside the package the shared
  rules are referenced by hash.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .assets import AssetKind, MarkAsset
from .fields import (EvidenceRecord, FieldState, FieldStatus, Gap, UNRESOLVED_TOKEN, all_paths, field_state, page_gaps)
from .manifest import DEFAULT_MANIFEST, STYLE_PATHS, Mode, PageManifest, PageSpec, _Strict

COMPILER_VERSION = "amc-brandbook-compiler/1.0.0"
COLOR_ROLES = ("ink", "paper", "accent", "accent_2", "muted")
SHARED_RULES = (
    "Use only the values and assets listed for this page; never invent names, slogans, dates, clients, contacts or claims.",
    "Render exact copy verbatim: same characters, punctuation and case; do not translate, abbreviate or restyle it.",
    "Place the canonical master by its hash; never redraw, regenerate, recolour or retype the logo.",
    "Misuse specimens are labelled examples, never masters.",
    "Meaning is never carried by colour alone; every status has a text label.",
    "If content does not fit: remove decoration, then optional annotations, then continue on a new page. Never shrink text "
    "below the minimum size and never drop required content silently.",
)
SHARED_RULES_HASH = canonical_hash(list(SHARED_RULES))


class BookContext(_Strict):
    brand_id: str
    brand_name: str
    genome_ref: str
    resolution_hash: str
    approved: dict[str, Any]
    sources: dict[str, str] = Field(default_factory=dict)
    proposed: dict[str, Any] = Field(default_factory=dict)
    proposal_ref: Optional[str] = None
    evidence: tuple[EvidenceRecord, ...] = ()
    mode: Mode
    locale: str = "en"
    mark: MarkAsset
    manifest: PageManifest = DEFAULT_MANIFEST

    @property
    def context_hash(self) -> str:
        return canonical_hash({"brand_id": self.brand_id, "brand_name": self.brand_name, "genome_ref": self.genome_ref,
                               "resolution_hash": self.resolution_hash, "proposal_ref": self.proposal_ref,
                               "proposed": self.proposed, "evidence": [e.model_dump(mode="json") for e in self.evidence],
                               "mode": self.mode.value, "locale": self.locale, "mark": self.mark.public(),
                               "manifest": self.manifest.manifest_hash, "compiler": COMPILER_VERSION})


class PagePackage(_Strict):
    page_id: str
    order: int
    title: str
    status: Literal["READY", "DRAFT", "BLOCKED", "NOT_APPLICABLE", "NOT_IN_MODE"]
    blocks: tuple[dict[str, Any], ...]
    copy_blocks: tuple[dict[str, Any], ...]        # exact visible copy: {copy_id, text, source, proposed}
    fields: tuple[FieldState, ...]
    gaps: tuple[Gap, ...]
    assets: tuple[dict[str, Any], ...]
    dependency_hash: str
    instructions: str
    package_hash: str = ""


class BookPackage(_Strict):
    schema_version: Literal["amc-vnexus-brandbook-package/v1"] = "amc-vnexus-brandbook-package/v1"
    brand_id: str
    brand_name: str
    genome_ref: str
    resolution_hash: str
    mode: Mode
    locale: str
    template_id: str
    template_version: str
    manifest_hash: str
    compiler_version: str = COMPILER_VERSION
    shared_rules_hash: str = SHARED_RULES_HASH
    context_hash: str
    mark: dict[str, Any]
    pages: tuple[PagePackage, ...]
    gaps: tuple[Gap, ...]
    status: Literal["READY", "DRAFT", "BLOCKED", "SPEC_ONLY"]
    package_hash: str = ""


# --------------------------------------------------------------------------- helpers


def label(path: str) -> str:
    tail = path.split(".")[1:]
    words = " ".join(tail[-2:] if len(tail) > 1 else tail).replace("_", " ")
    return words[:1].upper() + words[1:]


class _Page:
    """Accumulates blocks and copy for one page; copy ids are stable within the page."""

    def __init__(self, spec: PageSpec, states: dict[str, FieldState], mode: Mode):
        self.spec, self.states, self.mode = spec, states, mode
        self.blocks: list[dict[str, Any]] = []
        self.copy: list[dict[str, Any]] = []

    def text(self, text: str, *, role: str = "text", source: str = "template", proposed: bool = False) -> dict[str, Any]:
        cid = f"{self.spec.id}-c{len(self.copy) + 1:02d}"
        entry = {"copy_id": cid, "text": text, "source": source, "proposed": proposed}
        self.copy.append(entry)
        block = {"t": "copy", "role": role, "copy_id": cid, "text": text, "proposed": proposed}
        self.blocks.append(block)
        return block

    def caption(self, text: str) -> dict[str, Any]:
        """Copy that a figure block renders itself (so figures stay grouped)."""
        entry = {"copy_id": f"{self.spec.id}-c{len(self.copy) + 1:02d}", "text": text, "source": "template", "proposed": False}
        self.copy.append(entry)
        return entry

    def note(self, text: str, *, optional: bool = True) -> None:
        self.blocks.append({"t": "note", "text": text, "optional": optional})

    def field(self, path: str, *, as_list: bool = False, heading: Optional[str] = None) -> bool:
        """Print a key's value as copy, or its state as an annotation. Returns True when a value was printed."""
        s = self.states[path]
        self.blocks.append({"t": "label", "text": heading or label(path), "path": path})
        if s.printable:
            values = s.value if isinstance(s.value, list) else [s.value]
            for v in values if as_list or isinstance(s.value, list) else [s.value]:
                self.text(str(v), role="item" if len(values) > 1 else "text", source=path, proposed=not s.approved)
            if not s.approved:
                self.blocks.append({"t": "status", "status": "PROPOSED", "text": "Proposed, not approved"})
            return True
        if s.status is FieldStatus.NONE:
            self.blocks.append({"t": "status", "status": "NONE", "text": "Decided: none" + ("" if s.approved else " (proposed)")})
        elif s.status is FieldStatus.NOT_APPLICABLE:
            self.blocks.append({"t": "status", "status": "NOT_APPLICABLE", "text": f"Not applicable: {s.reason}" if s.reason
                                else "Not applicable"})
        elif self.mode is not Mode.PRODUCTION:
            self.blocks.append({"t": "gap", "path": path, "text": f"Gap: {path} is {s.status.value.lower()}"})
        return False

    def deco(self) -> None:
        self.blocks.append({"t": "deco"})


def _mark_block(p: _Page, mark: MarkAsset, *, variant: str = "master", size: int = 240, caption: Optional[str] = None) -> None:
    if mark.kind is AssetKind.MISSING:
        p.blocks.append({"t": "asset_missing", "text": "Master mark not approved: identity review required. Layout reserved; nothing drawn."})
        return
    p.blocks.append({"t": "asset", "asset": "mark", "sha256": mark.sha256, "variant": variant, "size": size,
                     "kind": mark.kind.value, "caption": caption or ""})


def _wordmark(p: _Page, brand_name: str) -> None:
    s = p.states["visual.logo.wordmark"]
    if s.printable:
        p.blocks.append({"t": "wordmark", "copy_id": p.text(str(s.value), role="wordmark", source="visual.logo.wordmark",
                                                              proposed=not s.approved)["copy_id"]})
    else:
        p.blocks.append({"t": "wordmark", "copy_id": p.text(brand_name, role="wordmark", source="brand.display_name")["copy_id"]})
        p.note("Wordmark text is the brand's registered display name; no separate wordmark is approved.")


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _palette(states: dict[str, FieldState]) -> dict[str, tuple[str, bool]]:
    """Only well-formed #rrggbb values are colours; anything else is printed as text by ``field`` and never styled."""
    return {role: (str(s.value).lower(), s.approved) for role in COLOR_ROLES
            if (s := states[f"visual.color.{role}"]).printable and isinstance(s.value, str) and _HEX.match(s.value)}


# --------------------------------------------------------------------------- page builders


def _page_content(p: _Page, ctx: BookContext, states: dict[str, FieldState]) -> None:
    pid, mark = p.spec.id, ctx.mark
    if pid == "p01":
        p.text(ctx.brand_name, role="title", source="brand.display_name")
        p.text("Brand guidelines", role="subtitle")
        p.text(f"Template {ctx.manifest.template_id} {ctx.manifest.template_version}", role="meta")
        p.text("Production build: approval is recorded on the build, not on this page" if ctx.mode is Mode.PRODUCTION
               else "Draft for review: not approved for release", role="meta")
        _mark_block(p, mark, size=200)
    elif pid == "p03":
        for path in ("strategy.positioning.statement", "strategy.audience.primary", "strategy.positioning.promise",
                     "strategy.audience.needs", "strategy.differentiation.statement", "strategy.values.list",
                     "strategy.competitive_territory.summary"):
            if path in p.spec.required_paths or states[path].status is not FieldStatus.UNKNOWN:
                p.field(path)
    elif pid == "p04":
        for path in ("verbal.voice.tone", "verbal.voice.register", "verbal.tone.channels", "verbal.vocabulary.prefer",
                     "verbal.vocabulary.avoid", "verbal.content_rules.claims"):
            if path in p.spec.required_paths or states[path].status is not FieldStatus.UNKNOWN:
                p.field(path, as_list=True)
        for path, head in (("verbal.messaging.write", "Write"), ("verbal.messaging.avoid", "Avoid")):
            if states[path].status is not FieldStatus.UNKNOWN:
                p.field(path, as_list=True, heading=head)
    elif pid == "p05":
        if not ctx.evidence:
            p.blocks.append({"t": "status", "status": "UNKNOWN", "text": "No intake evidence recorded for this brand."})
        rows = []
        for e in ctx.evidence:
            rows.append([e.source_id, e.locator, e.evidence_class.value, "; ".join(e.observations) or "-",
                         "; ".join(e.inferences) or "-", "; ".join(e.unknowns) or "-", e.reuse, e.privacy])
        if rows:
            p.blocks.append({"t": "table", "columns": ["Source", "Locator", "Class", "Observations", "Inferences", "Unknowns",
                                                       "Reuse", "Privacy"], "rows": rows})
        p.note("User-reported statements are not independent inspection. [PII] stays redacted; source compositions are evidence only.",
               optional=False)
    elif pid == "p06":
        _mark_block(p, mark, size=180)
        _wordmark(p, ctx.brand_name)
        pal = _palette(states)
        for role, (value, approved) in pal.items():
            p.blocks.append({"t": "swatch", "role": role, "value": value, "approved": approved})
        for path in ("visual.typography.display", "visual.typography.body"):
            p.field(path)
        p.note("Calibration page: approve this page first; later pages reuse its assets and layout.")
    elif pid == "p07":
        _mark_block(p, mark, size=320, caption="Master mark")
        p.blocks.append({"t": "asset_meta", "text": f"{mark.kind.value} · {mark.source}" + (f" · sha256 {mark.sha256[:16]}" if mark.sha256 else "")})
        _wordmark(p, ctx.brand_name)
        if states["visual.logo.placement"].status is not FieldStatus.UNKNOWN:
            p.field("visual.logo.placement")
    elif pid == "p08":
        _mark_block(p, mark, variant="construction", size=320)
        if states["visual.logo.construction"].status is not FieldStatus.UNKNOWN:
            p.field("visual.logo.construction")
        else:
            p.note("Shown: the master's canvas boundary and centre axes. Optical construction is not recorded in the approved genome.",
                   optional=False)
    elif pid == "p09":
        _wordmark(p, ctx.brand_name)
        for path in ("visual.logo.wordmark_case", "visual.logo.custom_lettering"):
            if states[path].status is not FieldStatus.UNKNOWN:
                p.field(path)
        p.note("Set in the approved display face as live text; custom lettering only if recorded above.")
    elif pid == "p10":
        if states["visual.logo.lockups"].printable:
            p.field("visual.logo.lockups", as_list=True)
        p.blocks.append({"t": "lockup", "arrangement": "horizontal"})
        p.blocks.append({"t": "lockup", "arrangement": "stacked"})
        _wordmark(p, ctx.brand_name)
        _mark_block(p, mark, size=120, caption="Symbol only")
    elif pid == "p11":
        printed = p.field("visual.logo.clear_space")
        _mark_block(p, mark, variant="clearspace" if printed else "master", size=220)
        if not printed:
            p.note("No clear-space rule is approved; no distance is shown or implied.", optional=False)
        p.blocks.append({"t": "example", "kind": "crowded", "text": "Incorrect: text crowding the mark"})
    elif pid == "p12":
        printed = p.field("visual.logo.min_size")
        if not printed:
            p.note("No minimum size is approved; sizes below are test renders, not a rule.", optional=False)
        for size in (16, 32, 64, 128):
            _mark_block(p, mark, variant="scale", size=size, caption=f"{size} px")
        p.note("Screen renders at CSS px. Physical-size print tests: NOT_RUN.", optional=False)
    elif pid == "p13":
        _mark_block(p, mark, variant="silhouette", size=160, caption="One colour")
        _mark_block(p, mark, variant="reverse", size=160, caption="Reverse")
        p.note("Silhouettes are rendered from the master by a colour filter; no separate one-colour master is approved.", optional=False)
    elif pid == "p14":
        if mark.kind is AssetKind.MISSING:
            _mark_block(p, mark)
        else:
            for transform, text in (("stretch", "Do not stretch or squash"), ("rotate", "Do not rotate"),
                                    ("recolor", "Do not recolour outside the palette"), ("effect", "Do not add effects"),
                                    ("busy", "Do not place on busy backgrounds"), ("crowd", "Do not crowd or rearrange")):
                cap = p.caption(f"Incorrect: {text}")
                p.blocks.append({"t": "misuse", "transform": transform, "sha256": mark.sha256, "copy_id": cap["copy_id"],
                                 "text": cap["text"]})
        p.note("Misuse specimens are derived views for teaching; they are never stored or used as masters.", optional=False)
    elif pid == "p15":
        pal = _palette(states)
        for role in COLOR_ROLES:
            path = f"visual.color.{role}"
            if role in pal:
                value, approved = pal[role]
                p.blocks.append({"t": "swatch", "role": role, "value": value, "approved": approved, "path": path})
            elif path in p.spec.required_paths or states[path].status is not FieldStatus.UNKNOWN:
                p.field(path)
        rows = []
        for fg in pal:
            for bg in pal:
                if fg == bg:
                    continue
                ratio = wcag_contrast_ratio(pal[fg][0], pal[bg][0])
                verdict = "AA text" if ratio >= 4.5 else ("AA large text only" if ratio >= 3 else "Fails AA: decoration only")
                rows.append([fg, bg, f"{ratio}:1", verdict])
        if rows:
            p.blocks.append({"t": "table", "columns": ["Foreground", "Background", "Contrast (WCAG 2.2)", "Use"], "rows": rows})
        for path in ("visual.color.names", "visual.color.usage"):
            if states[path].status is not FieldStatus.UNKNOWN:
                p.field(path, as_list=True)
    elif pid == "p16":
        for role, path in (("display", "visual.typography.display"), ("body", "visual.typography.body")):
            s = states[path]
            if s.printable:
                p.blocks.append({"t": "specimen", "role": role, "family": str(s.value), "approved": s.approved})
            p.field(path)
        for path in ("visual.typography.license", "visual.typography.fallback", "visual.typography.languages",
                     "visual.typography.scale"):
            if path == "visual.typography.license" or states[path].status is not FieldStatus.UNKNOWN:
                p.field(path)
        p.note("Font files are not embedded; previews use the installed face or a fallback, and say so in the release checks.",
               optional=False)
    elif pid in ("p17", "p18", "p19", "p20", "p21", "p22"):
        decision = states[p.spec.applicability_key]
        if decision.status is FieldStatus.NOT_APPLICABLE:
            p.blocks.append({"t": "status", "status": "NOT_APPLICABLE", "text": f"Not applicable: {decision.reason}"})
        for path in p.spec.optional_paths:
            if states[path].status is not FieldStatus.UNKNOWN:
                p.field(path, as_list=True)
        if pid == "p22" and states["visual.motion.reduced_motion"].status is FieldStatus.UNKNOWN \
                and decision.status is not FieldStatus.NOT_APPLICABLE:
            p.note("Reduced-motion rule not recorded.", optional=False)
    elif pid == "p23":
        p.note("Files below are the artifacts of this build; formats and licences come from the approved genome.", optional=False)
        for path in p.spec.optional_paths:
            p.field(path, as_list=True)
        rows = [["Master mark", mark.kind.value, mark.sha256[:16] if mark.sha256 else "missing", mark.source]]
        rows += [[f"Colour {role}", "token", value, "approved" if approved else "proposed"] for role, (value, approved) in _palette(states).items()]
        p.blocks.append({"t": "table", "columns": ["Item", "Kind", "Reference", "Status"], "rows": rows})
        p.blocks.append({"t": "handoff", "text": "Page artifacts and their hashes are listed in the build record."})


def _contents(p: _Page, pages: list[PagePackage], ctx: BookContext) -> None:
    status = {pg.page_id: pg.status for pg in pages}
    rows = [[f"{spec.order:02d}", spec.title, status.get(spec.id, "ASSEMBLED")] for spec in ctx.manifest.pages]
    p.blocks.append({"t": "table", "columns": ["Page", "Section", "Status"], "rows": rows})
    p.blocks.append({"t": "legend", "items": [["READY", "all required values approved"], ["DRAFT", "labelled gaps or proposals"],
                                              ["BLOCKED", "a required value is missing"], ["NOT_APPLICABLE", "approved decision"]]})
    p.text(f"Scope: genome {ctx.genome_ref}", role="meta", source="build.genome_ref")


def _release(p: _Page, pages: list[PagePackage], ctx: BookContext, checks: Optional[list[dict[str, Any]]]) -> None:
    gaps = [g for pg in pages for g in pg.gaps]
    p.blocks.append({"t": "table", "columns": ["Page", "Key", "Severity", "Next action"],
                     "rows": [[g.page_id, g.path, g.severity, g.next_action] for g in gaps] or [["-", "-", "-", "No open gaps"]]})
    if checks is None:
        p.blocks.append({"t": "status", "status": "NOT_RUN", "text": "Checks: NOT_RUN (nothing rendered in this mode)"})
    else:
        failed = [c for c in checks if c["status"] == "FAILED"]
        p.blocks.append({"t": "table", "columns": ["Page", "Check", "Status", "Detail"],
                         "rows": [[c["page_id"], c["check"], c["status"], c["detail"][:120]] for c in checks if c["status"] != "PASSED"]
                         or [["all", f"{len(checks)} checks", "PASSED", "no failing or unrun checks"]]})
        p.note(f"{len(checks)} checks, {len(failed)} failed.", optional=False)
    p.text(f"Genome {ctx.genome_ref}", role="meta", source="build.genome_ref")
    p.text(f"Resolution {ctx.resolution_hash[:16]}", role="meta", source="build.resolution_hash")
    p.note("Approval and release are recorded on the build, not printed here: a printed page is not an approval.", optional=False)


# --------------------------------------------------------------------------- compile


def _instructions(spec: PageSpec, page: _Page, ctx: BookContext, gaps: list[Gap]) -> str:
    lines = [f"PAGE {spec.id} · {spec.title} ({spec.order} of {len(ctx.manifest.pages)}) — brand book for {ctx.brand_name}",
             f"Template {ctx.manifest.template_id} {ctx.manifest.template_version}; mode {ctx.mode.value}; genome {ctx.genome_ref}",
             f"Objective: {spec.objective}", "Exact copy (verbatim, in this order):"]
    lines += [f'  - [{c["copy_id"]}] "{c["text"]}"' + (" (proposed)" if c["proposed"] else "") for c in page.copy] or ["  (none)"]
    placed = [b for b in page.blocks if b["t"] in ("asset", "misuse")]
    if placed:
        lines.append(f"Assets: canonical master mark {ctx.mark.kind.value} sha256:{ctx.mark.sha256} ({ctx.mark.source}); "
                     f"{len(placed)} placement(s). Place it; do not redraw it.")
    if spec.prohibitions:
        lines.append("Prohibitions: " + "; ".join(spec.prohibitions))
    if gaps:
        lines.append("Gaps (label them; do not fill them): " + "; ".join(f"{g.path} {g.status.value}" for g in gaps))
    lines.append(f"Layout: {spec.layout}. Checks: {', '.join(spec.checks)}.")
    return "\n".join(lines)


def standalone_prompt(page: PagePackage) -> str:
    """A self-contained prompt for one page: the shared rules inlined, nothing that depends on conversation memory."""
    return page.instructions + "\nRules:\n" + "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(SHARED_RULES))


def _states(ctx: BookContext) -> dict[str, FieldState]:
    proposed = ctx.proposed if ctx.mode is not Mode.PRODUCTION else {}
    return {path: field_state(path, ctx.approved, proposed, ctx.sources) for path in all_paths(ctx.manifest, STYLE_PATHS)}


def page_dependency_hash(spec: PageSpec, ctx: BookContext, states: dict[str, FieldState], *, extra: Any = None) -> str:
    paths = sorted(set(spec.dependency_paths) | set(STYLE_PATHS) | ({"visual.logo.wordmark"} if spec.asset_refs else set()))
    return canonical_hash({
        "template": [ctx.manifest.template_id, ctx.manifest.template_version], "spec": spec.model_dump(mode="json"),
        "compiler": COMPILER_VERSION, "mode": ctx.mode.value, "locale": ctx.locale, "brand_name": ctx.brand_name,
        "fields": {p: states[p].model_dump(mode="json") for p in paths},
        "mark": ctx.mark.public() if spec.asset_refs else None,
        "evidence": [e.model_dump(mode="json") for e in ctx.evidence] if spec.evidence_refs else None,
        "extra": extra,
    })


def _finish(spec: PageSpec, page: _Page, ctx: BookContext, gaps: list[Gap], dep: str) -> PagePackage:
    states = page.states
    if ctx.mode is Mode.PRODUCTION and any(UNRESOLVED_TOKEN.search(c["text"]) for c in page.copy):
        gaps.append(Gap(page_id=spec.id, path="copy", status=FieldStatus.UNKNOWN, severity="BLOCKING",
                        consequence="unresolved template token in copy", source="compiler", next_action="resolve the token"))
    decided_na = spec.gap_behavior == "DECIDE" and states[spec.applicability_key].status is FieldStatus.NOT_APPLICABLE and \
        (states[spec.applicability_key].approved or ctx.mode is not Mode.PRODUCTION)
    if decided_na:
        status = "NOT_APPLICABLE"
    elif any(g.severity == "BLOCKING" for g in gaps):
        status = "BLOCKED"
    elif gaps or any(c["proposed"] for c in page.copy) or (spec.asset_refs and ctx.mark.kind is not AssetKind.VECTOR):
        status = "DRAFT"
    else:
        status = "READY"
    fields = tuple(states[p] for p in spec.dependency_paths)
    assets = ({"asset": "mark", **ctx.mark.public()},) if spec.asset_refs else ()
    pkg = PagePackage(page_id=spec.id, order=spec.order, title=spec.title, status=status, blocks=tuple(page.blocks),
                      copy_blocks=tuple(page.copy), fields=fields, gaps=tuple(gaps), assets=assets, dependency_hash=dep,
                      instructions=_instructions(spec, page, ctx, gaps))
    return pkg.model_copy(update={"package_hash": canonical_hash(pkg.model_dump(mode="json", exclude={"package_hash"}))})


def compile_page(spec: PageSpec, ctx: BookContext, states: dict[str, FieldState]) -> PagePackage:
    if ctx.mode not in spec.output_modes:
        dep = page_dependency_hash(spec, ctx, states)
        return PagePackage(page_id=spec.id, order=spec.order, title=spec.title, status="NOT_IN_MODE", blocks=(), copy_blocks=(),
                           fields=(), gaps=(), assets=(), dependency_hash=dep, instructions="", package_hash=dep)
    page = _Page(spec, states, ctx.mode)
    gaps = page_gaps(spec, states, ctx.mode)
    if spec.asset_refs and "mark" in spec.asset_refs and ctx.mark.kind is AssetKind.MISSING and spec.gap_behavior == "BLOCK" \
            and not any(g.path == "visual.logo.mark" for g in gaps):
        gaps.append(Gap(page_id=spec.id, path="visual.logo.mark", status=FieldStatus.UNKNOWN,
                        severity="BLOCKING" if ctx.mode is Mode.PRODUCTION else "MAJOR",
                        consequence="no master to place", source="asset resolution",
                        next_action="route to identity review: approve a master mark"))
    _page_content(page, ctx, states)
    return _finish(spec, page, ctx, gaps, page_dependency_hash(spec, ctx, states))


def compile_book(ctx: BookContext, *, checks: Optional[list[dict[str, Any]]] = None,
                 reuse: Optional[dict[str, PagePackage]] = None) -> BookPackage:
    """Compile every page. ``reuse`` maps dependency hash -> an already compiled package (identical inputs, so identical
    output); ``checks`` feeds the release page with rendered check results (absent: NOT_RUN)."""
    states = _states(ctx)
    if ctx.mode is Mode.SYSTEM_SPEC_ONLY:
        gaps = tuple(g for spec in ctx.manifest.pages for g in page_gaps(spec, states, ctx.mode))
        book = BookPackage(brand_id=ctx.brand_id, brand_name=ctx.brand_name, genome_ref=ctx.genome_ref,
                           resolution_hash=ctx.resolution_hash, mode=ctx.mode, locale=ctx.locale,
                           template_id=ctx.manifest.template_id, template_version=ctx.manifest.template_version,
                           manifest_hash=ctx.manifest.manifest_hash, context_hash=ctx.context_hash, mark=ctx.mark.public(),
                           pages=(), gaps=gaps, status="SPEC_ONLY")
        return book.model_copy(update={"package_hash": canonical_hash(book.model_dump(mode="json", exclude={"package_hash"}))})
    reuse = reuse or {}
    body: list[PagePackage] = []
    for spec in ctx.manifest.pages:
        if spec.reads_all_pages:
            continue
        dep = page_dependency_hash(spec, ctx, states)
        body.append(reuse.get(dep) or compile_page(spec, ctx, states))
    pages: list[PagePackage] = list(body)
    for spec in ctx.manifest.pages:
        if not spec.reads_all_pages:
            continue
        others = sorted(body, key=lambda pg: pg.order)
        extra = {"pages": [[pg.page_id, pg.dependency_hash, pg.status] for pg in others],
                 "checks": canonical_hash(checks) if checks is not None and spec.id == "p24" else None}
        dep = page_dependency_hash(spec, ctx, states, extra=extra)
        if dep in reuse:
            pages.append(reuse[dep])
            continue
        page = _Page(spec, states, ctx.mode)
        gaps = page_gaps(spec, states, ctx.mode)
        if spec.id == "p02":
            _contents(page, others, ctx)
        elif spec.id == "p24":
            _release(page, others, ctx, checks)
        else:
            _page_content(page, ctx, states)
        pages.append(_finish(spec, page, ctx, gaps, dep))
    pages.sort(key=lambda pg: pg.order)
    gaps = tuple(g for pg in pages for g in pg.gaps)
    if any(pg.status == "BLOCKED" for pg in pages):
        status = "BLOCKED"
    elif any(pg.status == "DRAFT" for pg in pages) or ctx.mode is not Mode.PRODUCTION:
        status = "DRAFT"
    else:
        status = "READY"
    book = BookPackage(brand_id=ctx.brand_id, brand_name=ctx.brand_name, genome_ref=ctx.genome_ref, resolution_hash=ctx.resolution_hash,
                       mode=ctx.mode, locale=ctx.locale, template_id=ctx.manifest.template_id,
                       template_version=ctx.manifest.template_version, manifest_hash=ctx.manifest.manifest_hash,
                       context_hash=ctx.context_hash, mark=ctx.mark.public(), pages=tuple(pages), gaps=gaps, status=status)
    return book.model_copy(update={"package_hash": canonical_hash(book.model_dump(mode="json", exclude={"package_hash"}))})


__all__ = ["BookContext", "BookPackage", "COLOR_ROLES", "COMPILER_VERSION", "PagePackage", "SHARED_RULES", "SHARED_RULES_HASH",
           "compile_book", "compile_page", "label", "page_dependency_hash", "standalone_prompt"]
