"""Brand book service: approved genome -> page packages -> rendered, checked, stored book. Incremental, never authority.

Authority stays where it is: the approved genome (resolved per scope by
``vnexus.service``) plus explicitly referenced approved assets. The book is a
readable projection; pages and prompts are derived artifacts stored through
``foundry.studio.store`` (Project OS artifacts, content addressed, versioned).
Approval reuses ``open_artifact_approval`` and ``/approvals/{id}/decide``; release
reuses ``artifact_release_verdict`` and adds a freshness check against the genome.

Incremental build
-----------------
Each page has a dependency hash (its declared keys' states, the style keys, the
canonical mark, template/compiler/renderer versions, mode, locale). A page whose
stored head carries the same dependency hash and renderer version is reused
without compiling, rendering or measuring it again; its checks are reused only if
they were recorded for the same dependency hash and validator version. Contents
and release pages depend on every page and are rebuilt whenever any page changes.
Writes go page by page and the build record is written last, so an interrupted
build resumes from the pages it already stored. The build record is always rebound
to the current genome version even when every page's bytes were reused.

A process-local cache of compiled page packages is keyed by
``(tenant, project, dependency hash)`` and consulted only after authorization.
It holds pure compiler output, never approvals or release decisions.
"""

from __future__ import annotations

import hashlib
import json
import resource
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.security.auth import Principal

from .. import service as genome_service
from ..genome import Scope
from . import checks as checksmod
from . import compiler, render
from .assets import AssetKind, MarkAsset, resolve_mark
from .fields import EvidenceRecord, IntakeRecord, field_state
from .manifest import DEFAULT_MANIFEST, Mode, PageManifest

APPROVAL_POLICY = "amc-vnexus-brandbook/v1"
RUN_PIPELINE = "vnexus.brandbook"
SUBJECT_TYPE = "VNEXUS_BRAND_BOOK"
CACHE_LIMIT = 2048
# Exactly what the foundry composer reads for the mark (bridge.foundry_brief + typography_hook): palette, grammar
# weights, the mark id, the wordmark and the two faces. Clear space, minimum size and the rest never touch its bytes.
MARK_PREFIXES = ("visual.color.", "visual.shape_grammar.")
MARK_EXACT = frozenset({"visual.logo.mark", "visual.logo.wordmark", "visual.typography.display", "visual.typography.body"})

# store name suffix -> (N3 role, N1 artifact type, mime)
OUTPUTS: dict[str, tuple[str, str, str]] = {
    "page": ("brand_architect", "brand_guidelines_doc", "application/json"),
    "book": ("brand_architect", "brand_guidelines_doc", "text/html"),
    "pdf": ("brand_architect", "brand_guidelines_doc", "application/pdf"),
    "package": ("brand_architect", "brand_guidelines_doc", "application/json"),
    "preview": ("creative_director", "media_asset", "image/png"),
    "build": ("brand_safety_reviewer", "qa_report", "application/json"),
    "intake": ("brand_architect", "brand_guidelines_doc", "application/json"),
    "release": ("release_manager", "release_record", "application/json"),
}

_cache: "OrderedDict[tuple[str, str, str], compiler.PagePackage]" = OrderedDict()
_cache_lock = threading.Lock()


class BrandBookBlocked(ValueError):
    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


# --------------------------------------------------------------------------- storage helpers


def _adapter():
    from services.langgraph.api.routes._project_common import storage_adapter

    return storage_adapter()


def _scope_slug(brand_id: str, scope: Scope, scope_ref: str) -> str:
    return hashlib.sha256(f"{brand_id}|{scope.value}|{scope_ref}".encode()).hexdigest()[:12]


def _base(brand_id: str, scope: Scope, scope_ref: str, mode: Mode) -> str:
    # Project OS slugs artifact keys to 64 characters, so keys are a short digest of (brand, scope, ref, mode).
    digest = hashlib.sha256(f"{brand_id}|{scope.value}|{scope_ref}|{mode.value}".encode()).hexdigest()[:16]
    return f"vbb-{digest}"


def _intake_name(brand_id: str) -> str:
    return f"vbb-{hashlib.sha256(brand_id.encode()).hexdigest()[:16]}-intake"


def _artifact_id(project_id: str, name: str) -> str:
    from services.langgraph.persistence.projects import project_artifact_id

    return project_artifact_id(project_id, f"foundry-{name}")


def _put(principal: Principal, project_id: str, name: str, data: bytes, kind: str, *, depends_on: tuple[str, ...] = (),
         expect_head_hash: Optional[str] = None) -> dict:
    from services.langgraph.agency.foundry.studio import store

    role, artifact_type, mime = OUTPUTS[kind]
    if len(f"foundry-{name}") > 64:
        raise ValueError(f"artifact key {name!r} would be truncated by Project OS and could collide")
    assert_role_may_produce(role, artifact_type)
    entry = store(principal, project_id, name, data, mime=mime, artifact_type=artifact_type, subtype=f"vnexus_brandbook_{kind}",
                  adapter=_adapter(), depends_on=depends_on, expect_head_hash=expect_head_hash)
    return {**entry, "sha256": hashlib.sha256(data).hexdigest()}


def _read(project_id: str, name: str) -> Optional[tuple[bytes, dict]]:
    from services.langgraph.agency.foundry.studio import observe

    try:
        return observe(_artifact_id(project_id, name), _adapter())
    except LookupError:
        return None


# --------------------------------------------------------------------------- context


def _authorized_master_loader(principal: Principal, allowed_projects: set[str]) -> Callable[[str], Optional[bytes]]:
    def load(ref: str) -> Optional[bytes]:
        from services.langgraph.agency.foundry.studio import observe
        from services.langgraph.persistence.agency_kernel import get_artifact

        head = get_artifact(ref)
        if head is None or head.get("project_id") not in allowed_projects:
            return None
        try:
            genome_service.authorize(principal, head["project_id"])
        except PermissionError:
            return None
        return observe(ref, _adapter())[0]
    return load


def _composer(values: dict[str, Any], brand_name: str, genome_ref: str, resolution_hash: str, project_id: str):
    from services.langgraph.agency.foundry import compose
    from services.langgraph.agency.foundry.genome import MARKS

    from ..bridge import GenomeProjection, creative_genome
    from ..identity import transparent_svg

    def compose_mark(mark_id: str) -> Optional[str]:
        if mark_id not in MARKS:
            return None
        # The mark reads only visual keys. Projecting just those (and hashing just those) keeps its bytes, and so every
        # logo page's dependency hash, stable when unrelated keys such as voice or strategy change.
        visual = {k: v for k, v in values.items() if k.startswith(MARK_PREFIXES) or k in MARK_EXACT}
        visual["visual.logo.mark"] = mark_id
        p = GenomeProjection.__new__(GenomeProjection)
        p.values, p.brand_name, p.genome_ref, p.resolution_hash, p.used, p.missing = (
            visual, brand_name, "brandbook-mark", canonical_hash(visual), {}, [])
        genome = creative_genome(p, project_id=project_id)
        ir = compose.mark(genome, size=512)
        return transparent_svg(compose.to_svg(ir, genome), ir, genome)
    return compose_mark


def load_intake(principal: Principal, brand_id: str) -> tuple[IntakeRecord, Optional[str]]:
    brand = genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, brand["owner_project_id"])
    stored = _read(brand["owner_project_id"], _intake_name(brand_id))
    if stored is None:
        return IntakeRecord(), None
    return IntakeRecord.model_validate(json.loads(stored[0])), hashlib.sha256(stored[0]).hexdigest()


def save_intake(principal: Principal, brand_id: str, intake: IntakeRecord, *, expected_sha256: Optional[str]) -> dict:
    """Store intake evidence and proposals (CAS on the head the caller read). Never authority."""
    brand = genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, brand["owner_project_id"], write=True)
    data = (json.dumps(intake.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    entry = _put(principal, brand["owner_project_id"], _intake_name(brand_id), data, "intake",
                 expect_head_hash=expected_sha256)
    return {"artifact_id": entry["artifact_id"], "version": entry["version"], "sha256": entry["sha256"], "action": entry["action"]}


def propose_draft(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str) -> dict:
    """Turn intake proposals into a genome DRAFT at a scope (existing review and approval apply). Nothing is approved here."""
    from services.langgraph.persistence import vnexus as db

    from ..genome import GenomeDocument, document_from_flat

    intake, _ = load_intake(principal, brand_id)
    if not intake.proposals:
        raise ValueError("the intake has no proposals")
    approved = db.approved_version(brand_id, scope.value, scope_ref)
    base = GenomeDocument.model_validate(approved["document"]) if approved else GenomeDocument()
    doc = document_from_flat({**base.flatten(), **intake.proposals}, constraints=base.constraints, provenance=base.provenance)
    return genome_service.create_draft(principal, brand_id, scope=scope, scope_ref=scope_ref, document=doc)


def context(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str, mode: Mode,
            preview_version_id: Optional[str] = None, manifest: PageManifest = DEFAULT_MANIFEST) -> compiler.BookContext:
    brand = genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, project_id)
    resolution, layers = genome_service.resolve_scope(principal, brand_id, scope=scope, scope_ref=scope_ref)
    if mode is Mode.PRODUCTION:
        if preview_version_id:
            raise ValueError("production builds use approved genome versions only; drafts are previewed in PREVIEW mode")
        if not layers:
            raise BrandBookBlocked("no approved genome applies to this scope", {"scope": scope.value, "scope_ref": scope_ref})
        if resolution.blocking:
            raise BrandBookBlocked("the approved genome has blocking findings",
                                   {"blocking": [f.model_dump(mode="json") for f in resolution.blocking]})
    approved = dict(resolution.values) if layers else {}
    proposed: dict[str, Any] = {}
    proposal_ref = None
    intake, intake_sha = load_intake(principal, brand_id)
    if mode is not Mode.PRODUCTION:
        proposed.update({k: v for k, v in intake.proposals.items() if approved.get(k) != v})
        if intake.proposals:
            proposal_ref = f"intake:{intake_sha}"
        if preview_version_id:
            preview, _ = genome_service.resolve_scope(principal, brand_id, scope=scope, scope_ref=scope_ref,
                                                      preview_version_id=preview_version_id)
            proposed.update({k: v for k, v in preview.values.items() if approved.get(k) != v})
            proposal_ref = f"version:{preview_version_id}" + (f"+{proposal_ref}" if proposal_ref else "")
    genome_ref = layers[-1].version_id if layers else "no-approved-genome"
    resolution_hash = resolution.resolution_hash
    merged = {**approved, **proposed}
    states = {k: field_state(k, approved, proposed) for k in ("visual.logo.mark", "visual.logo.master_artifact", "visual.logo.master_sha256")}
    mark = resolve_mark(states, compose_mark=_composer(merged, brand["display_name"], genome_ref, resolution_hash, project_id),
                        load_master=_authorized_master_loader(principal, {project_id, brand["owner_project_id"]}))
    return compiler.BookContext(brand_id=brand_id, brand_name=brand["display_name"], genome_ref=genome_ref,
                                resolution_hash=resolution_hash, approved=approved, sources=dict(resolution.sources),
                                proposed=proposed, proposal_ref=proposal_ref, evidence=intake.evidence, mode=mode, mark=mark,
                                manifest=manifest)


# --------------------------------------------------------------------------- compile (no side effects)


def compile_package(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str, mode: Mode,
                    preview_version_id: Optional[str] = None) -> dict[str, Any]:
    """Compile the book package and readable prompts. Nothing is rendered, stored or sent."""
    ctx = context(principal, brand_id, scope=scope, scope_ref=scope_ref, project_id=project_id, mode=mode,
                  preview_version_id=preview_version_id)
    book = compiler.compile_book(ctx, reuse=_cached(principal, project_id))
    _remember(principal, project_id, book.pages)
    return {"package": book.model_dump(mode="json"),
            "prompts": {pg.page_id: compiler.standalone_prompt(pg) for pg in book.pages if pg.status != "NOT_IN_MODE"}}


def _cached(principal: Principal, project_id: str) -> dict[str, compiler.PagePackage]:
    with _cache_lock:
        return {dep: pkg for (tenant, project, dep), pkg in _cache.items() if tenant == principal.tenant_id and project == project_id}


def _remember(principal: Principal, project_id: str, pages: tuple[compiler.PagePackage, ...]) -> None:
    with _cache_lock:
        for pg in pages:
            _cache[(principal.tenant_id, project_id, pg.dependency_hash)] = pg
            _cache.move_to_end((principal.tenant_id, project_id, pg.dependency_hash))
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --------------------------------------------------------------------------- build


def _stored_page(project_id: str, base: str, page: compiler.PagePackage, *, measured: bool
                 ) -> tuple[Optional[list[tuple[str, str]]], Optional[list[dict[str, Any]]]]:
    """(sections, checks) of the stored page record. Sections count only if rendered from the same dependencies by this
    renderer version; checks only if also recorded by this validator version and measured whenever measuring is possible."""
    stored = _read(project_id, f"{base}-{page.page_id}")
    if stored is None:
        return None, None
    doc = json.loads(stored[0])
    if (doc.get("dependency_hash"), doc.get("renderer_version")) != (page.dependency_hash, render.RENDERER_VERSION):
        return None, None
    sections = [(k, html) for k, html in doc["sections"]]
    checks_ok = doc.get("validator_version") == checksmod.VALIDATOR_VERSION and (doc.get("measured") or not measured)
    return sections, (doc["checks"] if checks_ok else None)


def _page_record(page: compiler.PagePackage, sections: list[tuple[str, str]], checks: list[dict[str, Any]], measured: bool) -> bytes:
    """One versioned record per page: its rendered sections and the checks measured on exactly those sections."""
    doc = {"schema_version": "amc-vnexus-brandbook-page/v1", "page_id": page.page_id, "dependency_hash": page.dependency_hash,
           "package_hash": page.package_hash, "renderer_version": render.RENDERER_VERSION,
           "validator_version": checksmod.VALIDATOR_VERSION, "measured": measured,
           "sections": [[k, html] for k, html in sections], "sections_sha256": _sections_sha(sections), "checks": checks}
    return (json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode()


def _sections_sha(sections: list[tuple[str, str]]) -> str:
    return canonical_hash([[k, html] for k, html in sections])


def build(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str, mode: Mode,
          preview_version_id: Optional[str] = None, measure: bool = True, capture: Optional[bool] = None,
          interrupt_after: Optional[int] = None) -> dict[str, Any]:
    """Render, check and store the book. ``interrupt_after`` (tests) raises after that many page writes."""
    if mode in (Mode.SYSTEM_SPEC_ONLY, Mode.PROMPTS_ONLY):
        raise ValueError(f"{mode.value} compiles without rendering; use compile")
    genome_service.authorize(principal, project_id, write=True)
    t0 = time.perf_counter()
    stats: dict[str, Any] = {"browser_runs": 0, "pages_compiled": 0, "pages_reused": 0, "pages_rendered": 0, "pages_measured": 0,
                             "checks_reused": 0, "cache_hits": 0, "model_calls": 0, "stage_ms": {}}

    def lap(stage: str, since: float) -> float:
        now = time.perf_counter()
        stats["stage_ms"][stage] = round(stats["stage_ms"].get(stage, 0) + (now - since) * 1000, 1)
        return now

    ctx = context(principal, brand_id, scope=scope, scope_ref=scope_ref, project_id=project_id, mode=mode,
                  preview_version_id=preview_version_id)
    t = lap("context", t0)
    cached = _cached(principal, project_id)
    book = compiler.compile_book(ctx, reuse=cached)
    stats["cache_hits"] = sum(1 for pg in book.pages if pg.dependency_hash in cached)
    stats["pages_compiled"] = len(book.pages) - stats["cache_hits"]
    t = lap("compile", t)
    fields = render.style_values(book)
    fmt, width, height, provisional = render.page_format(fields)
    style = render.css(fields, width, height)
    palette, neutral = render.palette_for(fields)
    base = _base(brand_id, scope, scope_ref, mode)
    total = len(book.pages)
    capture = (mode is Mode.PREVIEW) if capture is None else capture
    from services.langgraph.agency.visual.browser import measure_layout, probe_browser

    can_measure = measure and probe_browser().get("available", False)
    writes = {"n": 0}

    def count_write() -> None:
        writes["n"] += 1
        if interrupt_after is not None and writes["n"] > interrupt_after:
            raise RuntimeError(f"interrupted after {interrupt_after} page writes")

    sections: dict[str, list[tuple[str, str]]] = {}
    page_checks: dict[str, list[dict[str, Any]]] = {}
    previews: dict[str, str] = {}

    def render_pages(pages: list[compiler.PagePackage], work: Path) -> None:
        """Render (or reuse) and check the given pages, running the overflow ladder on failures."""
        nonlocal t
        todo = []
        for pg in pages:
            stored, prior = _stored_page(project_id, base, pg, measured=can_measure)
            if stored is not None and prior is not None:
                sections[pg.page_id] = stored
                page_checks[pg.page_id] = prior
                stats["pages_reused"] += 1
                stats["checks_reused"] += 1
                continue
            todo.append(pg)
        t = lap("reuse_lookup", t)
        steps = {pg.page_id: 0 for pg in todo}
        pending = list(todo)
        for attempt in range(4):
            if not pending:
                break
            for pg in pending:
                step = steps[pg.page_id]
                sections[pg.page_id] = render.page_html(pg, mark=ctx.mark, brand_name=ctx.brand_name, fields=fields, width=width,
                                                        height=height, total=total, step=min(step, 2),
                                                        capacity=0.72 if step >= 3 else 1.0)
            stats["pages_rendered"] += len(pending)
            t = lap("render", t)
            measured: dict[str, list[dict[str, Any]]] = {pg.page_id: [] for pg in pending}
            if can_measure:
                html = render.book_html([s for pg in pending for _, s in sections[pg.page_id]], title="measure", style=style)
                run = measure_layout(html, width=width, height=height, out_dir=work / f"m{attempt}-{pending[0].page_id}",
                                     capture=capture and attempt == 0, min_font_px=render.MIN_FONT_PX)
                stats["browser_runs"] += 1
                stats["pages_measured"] += len(pending)
                measured = checksmod.measurement_for([pg.page_id for pg in pending], run["pages"])
                for key, file in run["captures"].items():
                    previews[key] = str(work / f"m{attempt}-{pending[0].page_id}" / file)
            t = lap("measure", t)
            still = []
            for pg in pending:
                result = checksmod.static_checks(pg, sections[pg.page_id], mode=mode, palette=palette, neutral=neutral)
                result += checksmod.measured_checks(pg, measured[pg.page_id], mark=ctx.mark, total=total)
                if steps[pg.page_id]:
                    result.append({"page_id": pg.page_id, "check": "overflow_ladder", "status": "PASSED", "severity": "WARNING",
                                   "detail": ["", "decoration hidden", "decoration and optional annotations hidden",
                                              "decoration and optional annotations hidden; content continued on more pages"][steps[pg.page_id]]})
                page_checks[pg.page_id] = result
                failed = any(c["check"] == "no_overflow" and c["status"] == "FAILED" for c in result)
                if failed and steps[pg.page_id] < 3:
                    steps[pg.page_id] += 1
                    still.append(pg)
            pending = still
        for pg in todo:
            page_entry = _put(principal, project_id, f"{base}-{pg.page_id}",
                              _page_record(pg, sections[pg.page_id], page_checks[pg.page_id], can_measure), "page")
            count_write()
            key = pg.page_id
            if key in previews and Path(previews[key]).is_file():
                _put(principal, project_id, f"{base}-{pg.page_id}-preview", Path(previews[key]).read_bytes(), "preview",
                     depends_on=(page_entry["artifact_id"],))
        t = lap("store", t)

    with tempfile.TemporaryDirectory(prefix="amc-brandbook-") as work_dir:
        work = Path(work_dir)
        body = [pg for pg in book.pages if not ctx.manifest.page(pg.page_id).reads_all_pages
                and pg.status not in ("NOT_IN_MODE",)]
        render_pages(body, work)
        body_checks = [c for pg in body for c in page_checks[pg.page_id]]
        book = compiler.compile_book(ctx, checks=body_checks, reuse={pg.dependency_hash: pg for pg in book.pages})
        summary = [pg for pg in book.pages if ctx.manifest.page(pg.page_id).reads_all_pages]
        render_pages(summary, work)
        _remember(principal, project_id, book.pages)
        ordered = [s for pg in book.pages for _, s in sections.get(pg.page_id, [])]
        book_html = render.book_html(ordered, title=f"{ctx.brand_name} brand guidelines", style=style)
        book_entry = _put(principal, project_id, f"{base}-book-html", book_html.encode(), "book")
        package_bytes = (json.dumps(book.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
        package_entry = _put(principal, project_id, f"{base}-package", package_bytes, "package",
                             depends_on=(book_entry["artifact_id"],))
        pdf = None
        if mode is Mode.PRODUCTION and can_measure:
            prior = _read(project_id, f"{base}-build")
            prior_doc = json.loads(prior[0]) if prior else {}
            if prior_doc.get("book", {}).get("sha256") == book_entry["sha256"] and prior_doc.get("pdf"):
                pdf = prior_doc["pdf"]
            else:
                from services.langgraph.agency.visual.browser import render_pdf

                run = render_pdf(book_html, width_px=width, height_px=height, out_dir=work / "pdf")
                stats["browser_runs"] += 1
                if run["status"] == "PASSED":
                    entry = _put(principal, project_id, f"{base}-book-pdf", Path(run["capture"]).read_bytes(), "pdf",
                                 depends_on=(book_entry["artifact_id"],))
                    pdf = {"artifact_id": entry["artifact_id"], "version": entry["version"], "sha256": entry["sha256"]}
        t = lap("assemble", t)
    all_checks = [c for pg in book.pages for c in page_checks.get(pg.page_id, [])]
    blocking_checks = checksmod.blocking(all_checks)
    if book.status == "BLOCKED" or (mode is Mode.PRODUCTION and blocking_checks):
        status = "BLOCKED"
    elif mode is Mode.PRODUCTION and book.status == "READY":
        status = "READY_FOR_APPROVAL"
    else:
        status = "PREVIEW_ONLY" if mode is Mode.PREVIEW else "DRAFT"
    record = {
        "schema_version": "amc-vnexus-brandbook-build/v1", "brand_id": brand_id, "scope": scope.value, "scope_ref": scope_ref,
        "project_id": project_id, "mode": mode.value, "locale": ctx.locale, "genome_ref": ctx.genome_ref,
        "resolution_hash": ctx.resolution_hash, "proposal_ref": ctx.proposal_ref, "template_id": ctx.manifest.template_id,
        "template_version": ctx.manifest.template_version, "manifest_hash": ctx.manifest.manifest_hash,
        "compiler_version": compiler.COMPILER_VERSION, "renderer_version": render.RENDERER_VERSION,
        "validator_version": checksmod.VALIDATOR_VERSION, "context_hash": ctx.context_hash,
        "page_format": {"name": fmt, "width": width, "height": height, "provisional": provisional},
        "palette": {"neutral": neutral}, "mark": ctx.mark.public(),
        "pages": [{"page_id": pg.page_id, "order": pg.order, "title": pg.title, "status": pg.status,
                   "dependency_hash": pg.dependency_hash, "package_hash": pg.package_hash,
                   "parts": [k for k, _ in sections.get(pg.page_id, [])],
                   "sections_sha256": _sections_sha(sections[pg.page_id]) if pg.page_id in sections else None,
                   "artifact_id": _artifact_id(project_id, f"{base}-{pg.page_id}") if pg.page_id in sections else None,
                   "gaps": [g.model_dump(mode="json") for g in pg.gaps],
                   "checks": checksmod.summarize(page_checks.get(pg.page_id, []))} for pg in book.pages],
        "gaps": [g.model_dump(mode="json") for g in book.gaps],
        "checks": {"summary": checksmod.summarize(all_checks), "measured": can_measure,
                   "blocking": blocking_checks[:50]},
        "book": {"artifact_id": book_entry["artifact_id"], "version": book_entry["version"], "sha256": book_entry["sha256"]},
        "package": {"artifact_id": package_entry["artifact_id"], "sha256": package_entry["sha256"], "package_hash": book.package_hash},
        "pdf": pdf, "status": status,
        "states": {"prompt": "READY", "rendered": "PASSED" if sections else "NOT_RUN",
                   "validated": ("NOT_RUN" if not can_measure else ("FAILED" if blocking_checks else "PASSED")),
                   "released": "NOT_RELEASED"},
    }
    record["build_hash"] = canonical_hash(record)
    build_entry = _put(principal, project_id, f"{base}-build", (json.dumps(record, sort_keys=True, indent=2) + "\n").encode(),
                       "build", depends_on=(book_entry["artifact_id"],))
    lap("record", t)
    stats["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    stats["peak_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {**record, "build_artifact": {"artifact_id": build_entry["artifact_id"], "version": build_entry["version"],
                                         "action": build_entry["action"]}, "telemetry": stats}


def get_build(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str, mode: Mode) -> dict[str, Any]:
    genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, project_id)
    stored = _read(project_id, f"{_base(brand_id, scope, scope_ref, mode)}-build")
    if stored is None:
        raise LookupError("no brand book build for this scope and mode")
    record = json.loads(stored[0])
    record["freshness"] = freshness(principal, record)
    return record


def read_output(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str, mode: Mode,
                kind: str, page_id: Optional[str] = None) -> tuple[bytes, str]:
    """Stored bytes of the book, a page preview or the PDF, after authorization."""
    genome_service.brand_for(principal, brand_id)
    genome_service.authorize(principal, project_id)
    base = _base(brand_id, scope, scope_ref, mode)
    name = {"book": f"{base}-book-html", "pdf": f"{base}-book-pdf",
            "preview": f"{base}-{page_id}-preview" if page_id else None}.get(kind)
    if name is None:
        raise LookupError(kind)
    stored = _read(project_id, name)
    if stored is None:
        raise LookupError(name)
    return stored[0], OUTPUTS["preview" if kind == "preview" else kind][2]


def freshness(principal: Principal, record: dict[str, Any]) -> dict[str, Any]:
    """Is the build still bound to the current approved genome and its stored bytes? Hashes prove identity, not approval."""
    reasons = []
    try:
        resolution, layers = genome_service.resolve_scope(principal, record["brand_id"], scope=Scope(record["scope"]),
                                                          scope_ref=record["scope_ref"])
        current_ref = layers[-1].version_id if layers else "no-approved-genome"
        if resolution.resolution_hash != record["resolution_hash"] or current_ref != record["genome_ref"]:
            reasons.append("GENOME_CHANGED")
    except genome_service.GenomeBlocked:
        reasons.append("GENOME_BLOCKED")
    stored = _read(record["project_id"], f"{_base(record['brand_id'], Scope(record['scope']), record['scope_ref'], Mode(record['mode']))}-book-html")
    if stored is None or hashlib.sha256(stored[0]).hexdigest() != record["book"]["sha256"]:
        reasons.append("BOOK_BYTES_CHANGED")
    return {"fresh": not reasons, "reasons": reasons}


def request_approval(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str) -> dict[str, Any]:
    """Open (or reuse) the approval bound to the production book's exact bytes. Decided only on /approvals/{id}/decide."""
    from services.langgraph.agency.intake.release import open_artifact_approval
    from services.langgraph.persistence.agency_kernel import get_artifact

    genome_service.authorize(principal, project_id, write=True)
    record = get_build(principal, brand_id, scope=scope, scope_ref=scope_ref, project_id=project_id, mode=Mode.PRODUCTION)
    reasons = list(record["freshness"]["reasons"])
    if record["status"] != "READY_FOR_APPROVAL":
        reasons.append(f"BUILD_{record['status']}")
    if reasons:
        return {"status": "BLOCKED", "reasons": reasons}
    head = get_artifact(record["book"]["artifact_id"])
    opened = open_artifact_approval(
        principal, tenant_id=principal.tenant_id, project_id=project_id,
        mission_id=f"{project_id}:vnexus-brandbook:{brand_id}:{_scope_slug(brand_id, scope, scope_ref)}",
        contract_hash=canonical_hash({"policy": APPROVAL_POLICY, "build_hash": record["build_hash"]}),
        artifact_id=head["artifact_id"], version=int(head["version"]), content_hash=head["content_hash"], run_pipeline=RUN_PIPELINE,
        policy_version=APPROVAL_POLICY, subject_type=SUBJECT_TYPE,
        reason=f"Approve brand book for {brand_id} ({scope.value}:{scope_ref}) built from genome {record['genome_ref']}",
        metadata={"brand_id": brand_id, "genome_ref": record["genome_ref"], "build_hash": record["build_hash"]})
    return {**opened, "status": "PENDING", "approval_status": opened.get("status")}


def release(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str,
            approval_id: Optional[str]) -> dict[str, Any]:
    """A local release record for an approved, still-fresh production book. No external effect."""
    from services.langgraph.agency.intake.release import artifact_release_verdict
    from services.langgraph.persistence.agency_kernel import get_artifact

    genome_service.authorize(principal, project_id, write=True)
    record = get_build(principal, brand_id, scope=scope, scope_ref=scope_ref, project_id=project_id, mode=Mode.PRODUCTION)
    head = get_artifact(record["book"]["artifact_id"])
    verdict = artifact_release_verdict(simulated=False, verification_passed=record["status"] == "READY_FOR_APPROVAL",
                                       artifact_id=record["book"]["artifact_id"], verified_version=int(head["version"]) if head else None,
                                       verified_hash=record["book"]["sha256"], approval_id=approval_id, tenant_id=principal.tenant_id,
                                       project_id=project_id)
    reasons = list(verdict.reasons) + list(record["freshness"]["reasons"])
    allowed = bool(verdict.allowed) and not record["freshness"]["reasons"]
    doc = {"brand_id": brand_id, "scope": scope.value, "scope_ref": scope_ref, "build_hash": record["build_hash"],
           "genome_ref": record["genome_ref"], "book_sha256": record["book"]["sha256"], "approval_id": approval_id,
           "release_allowed": allowed, "reasons": reasons, "external_effects": "none"}
    entry = _put(principal, project_id, f"{_base(brand_id, scope, scope_ref, Mode.PRODUCTION)}-release",
                 (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode(), "release", depends_on=(record["book"]["artifact_id"],))
    return {"status": "RELEASED_LOCAL" if allowed else "BLOCKED", "reasons": reasons, "release": doc,
            "artifact": {"artifact_id": entry["artifact_id"], "version": entry["version"]}}


def gaps_report(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, project_id: str,
                mode: Mode = Mode.PRODUCTION) -> dict[str, Any]:
    """Field-level gaps grouped into decisions: what to answer, why it matters, which pages it unblocks."""
    ctx = context(principal, brand_id, scope=scope, scope_ref=scope_ref, project_id=project_id,
                  mode=Mode.PREVIEW if mode is Mode.PRODUCTION else mode)
    spec = compiler.compile_book(ctx.model_copy(update={"mode": mode}) if mode is not Mode.PRODUCTION else
                                 ctx.model_copy(update={"mode": Mode.PRODUCTION, "proposed": {}}))
    by_path: dict[str, dict[str, Any]] = {}
    for g in spec.gaps:
        entry = by_path.setdefault(g.path, {"path": g.path, "status": g.status.value, "severity": g.severity, "pages": [],
                                            "consequence": g.consequence, "next_action": g.next_action})
        entry["pages"].append(g.page_id)
        if g.severity == "BLOCKING":
            entry["severity"] = "BLOCKING"
    decisions = sorted(by_path.values(), key=lambda d: (d["severity"] != "BLOCKING", -len(d["pages"]), d["path"]))
    return {"mode": mode.value, "genome_ref": ctx.genome_ref, "decisions": decisions,
            "mark": ctx.mark.public(), "evidence_records": len(ctx.evidence)}


def guidelines_for_identity(values: dict[str, Any], *, brand_name: str, brand_id: str, genome_ref: str, resolution_hash: str,
                            mark_svg: Optional[str]) -> tuple[str, int, int, str]:
    """The identity system's guidelines deliverable, rendered from the same compiler (approved values only).

    Returns (html, width, height, status). Replaces the old fixed five-section renderer: no hardcoded clear space or
    minimum size, the page format comes from the genome, and nothing is clipped.
    """
    mark = MarkAsset(kind=AssetKind.VECTOR, sha256=hashlib.sha256(mark_svg.encode()).hexdigest(), svg=mark_svg, approved=True,
                     source="identity production master") if mark_svg else MarkAsset(kind=AssetKind.MISSING, source="no master")
    ctx = compiler.BookContext(brand_id=brand_id, brand_name=brand_name, genome_ref=genome_ref, resolution_hash=resolution_hash,
                               approved=values, mode=Mode.PREVIEW, mark=mark)
    book = compiler.compile_book(ctx)
    fields = render.style_values(book)
    _, width, height, _ = render.page_format(fields)
    sections = [s for pg in book.pages for _, s in render.page_html(pg, mark=mark, brand_name=brand_name, fields=fields, width=width,
                                                                    height=height, total=len(book.pages))]
    return render.book_html(sections, title=f"{brand_name} brand guidelines", style=render.css(fields, width, height)), width, height, \
        book.status


__all__ = ["APPROVAL_POLICY", "BrandBookBlocked", "EvidenceRecord", "IntakeRecord", "OUTPUTS", "build", "clear_cache",
           "compile_package", "context", "freshness", "gaps_report", "get_build", "guidelines_for_identity", "load_intake",
           "propose_draft", "read_output", "release", "request_approval", "save_intake"]

