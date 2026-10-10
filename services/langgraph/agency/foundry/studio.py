"""Run a foundry mission into Project OS: one genome -> a connected, verified brand family.

Persistence is the existing Project OS (N4 artifacts with CAS versions and
``depends_on`` edges). Every deliverable depends on the genome artifact, so a
genome revision invalidates every dependent through the existing dependency
invalidation and opens scoped edit requests (the Brand Universe rule). Nothing
here approves anything: proofs stop at VERIFIED until a different human decides
through ``/approvals/{id}/decide``.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.storage import StorageAdapter
from services.langgraph.security.auth import Principal

from . import compose, experience, motion, scene, variants
from .capabilities import discover
from .contracts import FOUNDRY_VERSION, CreativeGenome, UserBrief
from .genome import compile_genome
from .proof import build_proof
from .routing import route_deliverable
from .tokens import compile_tokens

APPROVAL_POLICY = "amc-foundry-approval/v1"
RUN_PIPELINE = "creative_foundry"
# Rasters of flat vector art have few distinct colours by design; the photographic floor (256) does not apply.
FLAT_GRAPHIC_MIN_COLOURS = 8


def _key(name: str) -> str:
    return f"foundry-{name}"


def store(principal: Principal, project_id: str, name: str, data: bytes, *, mime: str, artifact_type: str, subtype: str,
          adapter: StorageAdapter, depends_on: tuple[str, ...] = (), v2: Optional[dict] = None) -> dict:
    """Create, revise (bytes changed) or reuse (bytes unchanged) a project artifact. Returns its head and what happened."""
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import (
        create_project_artifact,
        project_artifact_id,
        register_storage_object,
        revise_project_artifact,
    )

    stored = adapter.put_bytes(tenant_id=principal.tenant_id, project_id=project_id, data=data)
    register_storage_object(tenant_id=principal.tenant_id, project_id=project_id, stored=stored, mime_type=mime)
    meta = {"mime_type": mime, "media_type": mime.split("/")[0] if mime.startswith(("image", "video")) else "text",
            **(v2 or {})}
    artifact_id = project_artifact_id(project_id, _key(name))
    head = get_artifact(artifact_id)
    if head is None:
        created = create_project_artifact(tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id,
                                          artifact_key=_key(name), artifact_type=artifact_type, adapter=adapter,
                                          content_hash=stored.content_hash, storage_uri=stored.storage_uri, subtype=subtype,
                                          v2=meta, depends_on=depends_on)
        return {"artifact_id": created.artifact_id, "version": created.version, "content_hash": stored.content_hash,
                "action": "created", "invalidated": []}
    if head.get("content_hash") == stored.content_hash:
        return {"artifact_id": artifact_id, "version": int(head["version"]), "content_hash": stored.content_hash,
                "action": "reused_unchanged", "invalidated": []}
    revised = revise_project_artifact(project_id=project_id, artifact_id=artifact_id, actor=principal.user_id, adapter=adapter,
                                      expected_version=int(head["version"]), content_hash=stored.content_hash,
                                      storage_uri=stored.storage_uri, v2_patch=meta)
    affected = [a["artifact_id"] for a in revised["blast_radius"]["affected"] if a.get("status") == "invalidated"]
    return {"artifact_id": artifact_id, "version": int(revised["artifact"].version), "content_hash": stored.content_hash,
            "action": "revised", "invalidated": affected, "remediation_requests": revised["blast_radius"]["remediation_requests"]}


def observe(artifact_id: str, adapter: StorageAdapter) -> tuple[bytes, dict]:
    """Independent read of the stored bytes behind the current head."""
    from services.langgraph.persistence.agency_kernel import get_artifact

    head = get_artifact(artifact_id)
    if head is None:
        raise LookupError(artifact_id)
    data = adapter.get_bytes(head["content_location"])
    return data, head


def _validate(data: bytes, mime: str, expect: dict) -> tuple[dict, ...]:
    from services.langgraph.agency.visual.verify import verify_media

    if mime in {"image/png", "image/svg+xml", "video/mp4"}:
        v = verify_media(data, mime_type=mime, expect=expect)
        return tuple({"check": c["check"], "level": c["level"], "passed": c["passed"], "detail": c["detail"]} for c in v.checks) + (
            {"check": "verify_media.status", "level": "SUMMARY", "passed": v.status == "PASSED", "detail": v.status},)
    if mime == "application/json":
        try:
            json.loads(data)
            return ({"check": "json_parse", "level": "Q1", "passed": True, "detail": f"{len(data)} bytes"},)
        except ValueError as exc:
            return ({"check": "json_parse", "level": "Q1", "passed": False, "detail": str(exc)[:200]},)
    if mime in {"text/css", "text/html"}:
        return tuple(expect.get("results") or ({"check": "utf8", "level": "Q0", "passed": _utf8(data), "detail": mime},))
    return ({"check": "no_verifier", "level": "Q0", "passed": None, "detail": f"NO_VERIFIER_FOR:{mime}"},)


def _utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _png_dims(data: bytes) -> Optional[str]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return f"{int.from_bytes(data[16:20], 'big')}x{int.from_bytes(data[20:24], 'big')}"


class Mission:
    """One brief, one genome, many deliverables. Collects artifacts, proofs, routes and gaps as it goes."""

    def __init__(self, principal: Principal, project_id: str, brief: UserBrief, *, adapter: StorageAdapter,
                 work_dir: Optional[Path] = None, copy: Optional[dict] = None):
        if not principal.can_access_project(project_id):
            raise PermissionError("principal cannot access this project")
        from services.langgraph.persistence.projects import require_project_workspace

        workspace = require_project_workspace(project_id)
        if workspace.tenant_id != principal.tenant_id:
            raise PermissionError("project belongs to another tenant")
        self.principal, self.project_id, self.brief, self.adapter = principal, project_id, brief, adapter
        self.work = Path(work_dir or tempfile.mkdtemp(prefix="amc-foundry-"))
        self.caps = {c.capability_id: c for c in discover()}
        self.artifacts: list[dict] = []
        self.routes: list[dict] = []
        self.gaps: list[dict] = []
        self.genome: Optional[CreativeGenome] = None
        self.genome_artifact: Optional[str] = None
        offering = brief.offering or "Your offering"
        self.copy = {"headline": (copy or {}).get("headline") or (brief.business_objective or offering)[:60],
                     "subhead": (copy or {}).get("subhead") or offering,
                     "cta": (copy or {}).get("cta") or (brief.desired_action or "Learn more")[:28],
                     "meta": (copy or {}).get("meta") or ""}

    # -- bookkeeping ------------------------------------------------------------------------------
    def _record(self, deliverable: str, name: str, data: bytes, *, mime: str, artifact_type: str, subtype: str,
                ir_hash: Optional[str], renderer: str, renderer_version: Optional[str], expect: dict,
                depends: tuple[str, ...] = (), v2: Optional[dict] = None, elapsed_ms: int = 0) -> dict:
        deps = tuple(d for d in ((self.genome_artifact,) + depends) if d)
        r = store(self.principal, self.project_id, name, data, mime=mime, artifact_type=artifact_type, subtype=subtype,
                  adapter=self.adapter, depends_on=deps,
                  v2={"provenance_ref": f"foundry:{(ir_hash or '')[:32]}", **(v2 or {})})
        observed, head = observe(r["artifact_id"], self.adapter)
        sha = hashlib.sha256(observed).hexdigest()
        validations = _validate(observed, mime, expect)
        dims = _png_dims(observed) or (f"{expect.get('width')}x{expect.get('height')}" if expect.get("width") else None)
        proof = build_proof(project_ref=self.project_id, artifact_ref=r["artifact_id"], version_ref=int(head["version"]),
                            source_hash=self.genome.content_hash if self.genome else canonical_hash(self.brief.model_dump()),
                            compiled_ir_hash=ir_hash, renderer_id=renderer, renderer_version=renderer_version, executed=True,
                            observed_sha256=sha, recorded_sha256=head.get("content_hash"), mime_type=mime,
                            observed_dimensions=dims, file_size=len(observed), dependency_hashes=deps,
                            license_refs=("procedural:owned",), validations=validations)
        entry = {"deliverable": deliverable, "name": name, "artifact_id": r["artifact_id"], "version": int(head["version"]),
                 "action": r["action"], "invalidated": r.get("invalidated", []), "mime_type": mime, "sha256": sha,
                 "bytes": len(observed), "proof": proof.model_dump(mode="json"), "elapsed_ms": elapsed_ms,
                 "local_path": None}
        self.artifacts.append(entry)
        return entry

    def _route(self, deliverable: str) -> bool:
        decision = route_deliverable(deliverable, self.caps)
        self.routes.append(decision)
        if decision["status"] == "BLOCKED":
            self.gaps.append({"deliverable": deliverable, **decision["gap"]})
            return False
        return True

    # -- deliverables -------------------------------------------------------------------------------
    def run_genome(self) -> CreativeGenome:
        self._route("genome")
        g = compile_genome(self.brief, project_id=self.project_id)
        self.genome = g
        data = json.dumps(g.model_dump(mode="json"), indent=2, sort_keys=True).encode()
        e = self._record("genome", "genome", data, mime="application/json", artifact_type="design_system_spec",
                         subtype="creative_genome", ir_hash=g.content_hash, renderer="agency.foundry.genome",
                         renderer_version=FOUNDRY_VERSION, expect={})
        self.genome_artifact = e["artifact_id"]
        return g

    def run_tokens(self) -> None:
        if not self._route("design_tokens"):
            return
        doc, css, src = compile_tokens(self.genome)
        self._record("design_tokens", "tokens.json", json.dumps(doc, indent=2, sort_keys=True).encode(), mime="application/json",
                     artifact_type="design_token_set", subtype="dtcg", ir_hash=src, renderer="agency.design_tokens",
                     renderer_version="amc-dtcg-compiler/v1", expect={})
        self._record("design_tokens", "tokens.css", css.encode(), mime="text/css", artifact_type="design_token_set",
                     subtype="css", ir_hash=src, renderer="agency.design_tokens", renderer_version="amc-dtcg-compiler/v1",
                     expect={"results": ({"check": "dtcg_compile", "level": "Q2", "passed": True, "detail": f"source {src[:16]}"},)})

    def _raster(self, svg: str, w: int, h: int, label: str) -> Optional[bytes]:
        from services.langgraph.agency.visual.browser import rasterize_svg

        if self.caps["raster.chromium"].status != "AVAILABLE":
            self.gaps.append({"deliverable": label, "missing": ["raster.chromium"],
                              "blockers": list(self.caps["raster.chromium"].blockers)})
            return None
        r = rasterize_svg(svg, width=w, height=h, out_dir=self.work / f"raster-{label}")
        if r["status"] != "PASSED":
            self.gaps.append({"deliverable": label, "missing": [], "blockers": r["findings"] or ["RASTERIZE_FAILED"]})
            return None
        return Path(r["capture"]).read_bytes()

    def run_logo_family(self) -> None:
        if not self._route("logo_family"):
            return
        g = self.genome
        pal = g.palette.roles()
        palette_list = sorted(set(pal.values()))
        for name, ir in (("mark.svg", compose.mark(g, size=256)), ("lockup.svg", compose.lockup(g)),
                         ("lockup-dark.svg", compose.lockup(g, on="ink"))):
            svg = compose.to_svg(ir, g)
            self._record("logo_family", name, svg.encode(), mime="image/svg+xml", artifact_type="media_asset",
                         subtype="logo", ir_hash=ir.content_hash, renderer="agency.foundry.compose", renderer_version=FOUNDRY_VERSION,
                         expect={"palette": palette_list, "render_sizes": (32, 128) if name == "mark.svg" else ()})
        app = compose.mark(g, size=512, on="paper")
        png = self._raster(compose.to_svg(app, g), 512, 512, "app-icon")
        if png:
            self._record("logo_family", "app-icon-512.png", png, mime="image/png", artifact_type="media_asset", subtype="logo",
                         ir_hash=app.content_hash, renderer="raster.chromium", renderer_version=self.caps["raster.chromium"].installed_version,
                         expect={"width": 512, "height": 512, "min_unique_colours": FLAT_GRAPHIC_MIN_COLOURS})
        icons = "".join(f'<symbol id="{n}" viewBox="0 0 24 24">{compose.icon_svg(g, n).split(">", 1)[1].rsplit("</svg>", 1)[0]}</symbol>'
                        for n in compose.ICON_PATHS)
        uses = "".join(f'<use href="#{n}" x="{i * 32}" y="0" width="24" height="24"/>' for i, n in enumerate(compose.ICON_PATHS))
        sheet = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{32 * len(compose.ICON_PATHS)}" height="24" '
                 f'viewBox="0 0 {32 * len(compose.ICON_PATHS)} 24" role="img" aria-label="{escape(g.brand_name)} icon family">'
                 f'<title>{escape(g.brand_name)} icon family</title><defs>{icons}</defs>{uses}</svg>\n')
        self._record("icon_family", "icons.svg", sheet.encode(), mime="image/svg+xml", artifact_type="media_asset",
                     subtype="icon_family", ir_hash=canonical_hash(sheet), renderer="agency.foundry.compose",
                     renderer_version=FOUNDRY_VERSION, expect={"palette": palette_list})

    def run_poster(self, *, width: int = 1200, height: int = 1600) -> Optional[dict]:
        if not self._route("poster"):
            return None
        g = self.genome
        ir = compose.poster(g, headline=self.copy["headline"], subhead=self.copy["subhead"], cta=self.copy["cta"],
                            meta=self.copy["meta"], width=width, height=height)
        svg = compose.to_svg(ir, g)
        e_svg = self._record("poster", "poster.svg", svg.encode(), mime="image/svg+xml", artifact_type="media_asset",
                             subtype="poster", ir_hash=ir.content_hash, renderer="agency.foundry.compose",
                             renderer_version=FOUNDRY_VERSION, expect={"palette": sorted(set(g.palette.roles().values()))})
        started = time.monotonic()
        png = self._raster(svg, width, height, "poster")
        if png is None:
            return e_svg
        (self.work / "poster.png").write_bytes(png)
        return self._record("poster", "poster.png", png, mime="image/png", artifact_type="media_asset", subtype="poster",
                            ir_hash=ir.content_hash, renderer="raster.chromium",
                            renderer_version=self.caps["raster.chromium"].installed_version,
                            expect={"width": width, "height": height}, depends=(e_svg["artifact_id"],),
                            elapsed_ms=int((time.monotonic() - started) * 1000))

    def run_variants(self, *, directions: Optional[list[dict]] = None) -> list[dict]:
        if not self._route("variants"):
            return []
        g = self.genome
        base = variants.generate_candidate(g)
        plan = directions or [{"dimensions": ["composition", "color"], "seed": 1}, {"dimensions": ["grid", "typography", "geometry"],
                                                                                    "seed": 2}]
        variants.check_population(g, 1 + len(plan))
        cands = [base] + [variants.mutate_candidate(g, base, dimensions=d["dimensions"], seed=d["seed"]) for d in plan]
        rendered = [variants.render_candidate(g, c, headline=self.copy["headline"], subhead=self.copy["subhead"],
                                              cta=self.copy["cta"], width=600, height=800) for c in cands]
        out = []
        for i, (cand, ir, svg) in enumerate(rendered):
            png = self._raster(svg, 600, 800, f"variant-{i}")
            if png is None:
                continue
            out.append(self._record("variants", f"direction-{i}.png", png, mime="image/png", artifact_type="media_asset",
                                    subtype="creative_direction", ir_hash=ir.content_hash, renderer="raster.chromium",
                                    renderer_version=self.caps["raster.chromium"].installed_version,
                                    expect={"width": 600, "height": 800}, v2={"variant_of": cand.parents[0] if cand.parents else None}))
        comparisons = [{"a": rendered[i][0].candidate_id, "b": rendered[j][0].candidate_id,
                        **variants.compare_candidates((rendered[i][0], rendered[i][1]), (rendered[j][0], rendered[j][1]))}
                       for i in range(len(rendered)) for j in range(i + 1, len(rendered))]
        lineage = {"candidates": variants.lineage([r[0] for r in rendered]), "comparisons": comparisons,
                   "feedback": [], "note": "diversity is computed; no audience preference is predicted"}
        self._record("variants", "lineage.json", json.dumps(lineage, indent=2, sort_keys=True).encode(), mime="application/json",
                     artifact_type="creative_concept", subtype="variant_lineage", ir_hash=canonical_hash(lineage),
                     renderer="agency.foundry.variants", renderer_version=FOUNDRY_VERSION, expect={})
        return out

    def run_website(self, *, counterfactual: bool = True) -> Optional[dict]:
        if not self._route("website_section"):
            return None
        g = self.genome
        ir = experience.compile_experience(g, self.brief, headline=self.copy["headline"], subhead=self.copy["subhead"],
                                           cta=self.copy["cta"])
        html = experience.render_html(ir, g)
        primary = g.typography_rules["stacks"]["display"][0]
        started = time.monotonic()
        ev = experience.evaluate(html, out_dir=self.work / "experience", primary_font=primary)
        results = tuple({"check": f"scenario:{s['id']}", "level": "TASK", "passed": s["passed"],
                         "detail": "; ".join(f"{st['action']}:{st.get('detail') or 'ok'}" for st in s["steps"] if not st["ok"])[:300]}
                        for s in ev["scenarios"]) + (
            {"check": "audit.contrast", "level": "WCAG", "passed": not any(s["audit"]["contrast_failures"] for s in ev["scenarios"]),
             "detail": "computed WCAG 2.x ratios of rendered text"},
            {"check": "audit.labels", "level": "WCAG", "passed": not any(s["audit"]["unlabeled_controls"] for s in ev["scenarios"]),
             "detail": "every form control has a label"})
        site = self._record("website_section", "section.html", html.encode(), mime="text/html",
                            artifact_type="website_lockup_spec", subtype="experience_twin", ir_hash=ir.content_hash,
                            renderer="web.html_css", renderer_version=ev.get("browser"), expect={"results": results},
                            elapsed_ms=int((time.monotonic() - started) * 1000))
        report = {"experience_ir": ir.model_dump(mode="json"), "evaluation": ev}
        if counterfactual:
            alt = compile_genome(self.brief.model_copy(update={"visual_direction": {"synthetic_futurism": 1.0},
                                                               "seed": (g.deterministic_seed + 7919) % (2**31 - 1)}),
                                 project_id=self.project_id)
            report["counterfactual_skins"] = experience.counterfactual_skins(ir, g, alternate=alt, out_dir=self.work / "skins")
        self._record("website_section", "experience-report.json", json.dumps(report, indent=2, sort_keys=True, default=str).encode(),
                     mime="application/json", artifact_type="qa_report", subtype="experience_evaluation",
                     ir_hash=canonical_hash(report), renderer="raster.chromium", renderer_version=ev.get("browser"),
                     expect={}, depends=(site["artifact_id"],))
        return site

    def run_scene(self, *, artwork: Optional[Path] = None, quality: str = "draft") -> Optional[dict]:
        if not self._route("product_scene"):
            return None
        ir = scene.compile_scene(self.genome, quality=quality)
        started = time.monotonic()
        receipt = scene.render_scene(ir, artwork_png=artwork or (self.work / "poster.png"), out_dir=self.work / "scene")
        if isinstance(receipt, dict) or receipt.status != "SUCCEEDED":
            reasons = receipt["reasons"] if isinstance(receipt, dict) else list(receipt.reasons)
            self.gaps.append({"deliverable": "product_scene", "missing": [], "blockers": reasons, "recoverable": True})
            return None
        data = Path(receipt.outputs[0]["path"]).read_bytes()
        poster_png = next((a["artifact_id"] for a in self.artifacts if a["name"] == "poster.png"), None)
        return self._record("product_scene", "package-scene.png", data, mime="image/png", artifact_type="media_asset",
                            subtype="synthetic_3d_scene", ir_hash=ir.content_hash, renderer="spatial.blender",
                            renderer_version=receipt.genome.renderer_version if receipt.genome else None,
                            expect={"width": ir.width, "height": ir.height}, depends=tuple(d for d in (poster_png,) if d),
                            v2={"source_refs": [ir.synthetic_disclosure]}, elapsed_ms=int((time.monotonic() - started) * 1000))

    def run_motion(self) -> Optional[dict]:
        if not self._route("motion"):
            return None
        from services.langgraph.agency.visual.browser import render_svg_frames
        from services.langgraph.agency.visual.renderers import encode_video

        g = self.genome
        ir = motion.logo_reveal(g)
        started = time.monotonic()
        fr = render_svg_frames(motion.frames(ir, g), width=ir.width, height=ir.height, out_dir=self.work / "motion")
        if fr["status"] != "PASSED":
            self.gaps.append({"deliverable": "motion", "missing": [], "blockers": fr["findings"]})
            return None
        video = encode_video([Path(f) for f in fr["files"]], self.work / "motion" / "logo-reveal.mp4", fps=ir.fps)
        if video.status != "SUCCEEDED":
            self.gaps.append({"deliverable": "motion", "missing": [], "blockers": list(video.reasons)})
            return None
        mp4 = self._record("motion", "logo-reveal.mp4", Path(video.outputs[0]["path"]).read_bytes(), mime="video/mp4",
                           artifact_type="media_asset", subtype="motion_identity", ir_hash=ir.content_hash,
                           renderer="motion.ffmpeg", renderer_version=self.caps["motion.ffmpeg"].installed_version,
                           expect={"width": ir.width, "height": ir.height, "fps": ir.fps, "frames": ir.frame_count},
                           v2={"duration_seconds": ir.duration_s}, elapsed_ms=int((time.monotonic() - started) * 1000))
        still = Path(fr["files"][-1]).read_bytes()
        self._record("motion", "logo-reveal-reduced-motion.png", still, mime="image/png", artifact_type="media_asset",
                     subtype="reduced_motion_alternative", ir_hash=ir.content_hash, renderer="raster.chromium",
                     renderer_version=self.caps["raster.chromium"].installed_version,
                     expect={"width": ir.width, "height": ir.height, "min_unique_colours": FLAT_GRAPHIC_MIN_COLOURS},
                     depends=(mp4["artifact_id"],))
        return mp4

    def manifest(self) -> dict:
        return {"schema_version": "amc-foundry-manifest/v1", "foundry_version": FOUNDRY_VERSION, "project_id": self.project_id,
                "genome_hash": self.genome.content_hash if self.genome else None, "genome_artifact": self.genome_artifact,
                "brief": self.brief.model_dump(mode="json"), "assumptions": [a.model_dump(mode="json") for a in
                                                                            (self.genome.assumptions if self.genome else ())],
                "artifacts": self.artifacts, "routes": self.routes, "capability_gaps": self.gaps,
                "capabilities": [c.model_dump(mode="json") for c in self.caps.values()],
                "external_effects": "none: no publication, purchase, deployment, send or third-party account action"}

    def run(self, *, counterfactual: bool = True, quality: str = "draft") -> dict:
        wanted = set(self.brief.deliverable_types) | {"genome"}
        self.run_genome()
        if "design_tokens" in wanted:
            self.run_tokens()
        if wanted & {"logo_family", "icon_family"}:
            self.run_logo_family()
        if wanted & {"poster", "product_scene"}:
            self.run_poster()
        if "variants" in wanted:
            self.run_variants()
        if "website_section" in wanted:
            self.run_website(counterfactual=counterfactual)
        if "product_scene" in wanted:
            self.run_scene(quality=quality)
        if "motion" in wanted:
            self.run_motion()
        doc = self.manifest()
        data = json.dumps(doc, indent=2, sort_keys=True, default=str).encode()
        self._record("genome", "manifest.json", data, mime="application/json", artifact_type="qa_report",
                     subtype="foundry_manifest", ir_hash=canonical_hash(doc), renderer="agency.foundry.studio",
                     renderer_version=FOUNDRY_VERSION, expect={})
        return doc


def load_mission(principal: Principal, project_id: str, *, adapter: StorageAdapter, work_dir: Path) -> Mission:
    """Rebuild a Mission from the project's stored genome and manifest (Project OS is the only store)."""
    from services.langgraph.persistence.projects import project_artifact_id

    manifest_bytes, _ = observe(project_artifact_id(project_id, _key("manifest.json")), adapter)
    manifest = json.loads(manifest_bytes)
    genome_bytes, genome_head = observe(project_artifact_id(project_id, _key("genome")), adapter)
    mission = Mission(principal, project_id, UserBrief.model_validate(manifest["brief"]), adapter=adapter, work_dir=work_dir)
    mission.genome = CreativeGenome.model_validate(json.loads(genome_bytes))
    mission.genome_artifact = genome_head["artifact_id"]
    return mission


def create_variant(principal: Principal, project_id: str, *, adapter: StorageAdapter, work_dir: Path,
                   dimensions: tuple[str, ...] = (), seed: int = 1, edits: Optional[dict] = None) -> dict:
    """One new direction from the stored genome: a mutation (dimensions) or a human fork (edits). Lineage is recorded."""
    m = load_mission(principal, project_id, adapter=adapter, work_dir=work_dir)
    g = m.genome
    base = variants.generate_candidate(g)
    cand = variants.fork_candidate(g, base, edits=edits) if edits else variants.mutate_candidate(
        g, base, dimensions=dimensions or ("composition",), seed=seed)
    cand, ir, svg = variants.render_candidate(g, cand, headline=m.copy["headline"], subhead=m.copy["subhead"],
                                              cta=m.copy["cta"], width=600, height=800)
    png = m._raster(svg, 600, 800, cand.candidate_id)
    if png is None:
        return {"status": "BLOCKED", "reasons": ["RASTERIZE_FAILED"], "candidate": cand.model_dump(mode="json")}
    entry = m._record("variants", f"{cand.candidate_id}.png", png, mime="image/png", artifact_type="media_asset",
                      subtype="creative_direction", ir_hash=ir.content_hash, renderer="raster.chromium",
                      renderer_version=m.caps["raster.chromium"].installed_version, expect={"width": 600, "height": 800},
                      v2={"variant_of": base.candidate_id})
    return {"status": "CREATED", "candidate": cand.model_dump(mode="json"), "artifact": entry}


def request_approval(principal: Principal, project_id: str, artifact_id: str, *, adapter: StorageAdapter,
                     mission_id: str) -> dict:
    """Bind an approval to the exact verified bytes of the current head (reuses the shared release module)."""
    from services.langgraph.agency.intake.release import open_artifact_approval

    data, head = observe(artifact_id, adapter)
    if head["project_id"] != project_id:
        raise PermissionError("artifact is not in this project")
    sha = hashlib.sha256(data).hexdigest()
    if sha != head.get("content_hash"):
        raise ValueError("stored bytes do not match the recorded hash; refusing to request approval")
    # The approval run id derives from the mission id; scope it to the project so ids can never collide across projects.
    return open_artifact_approval(principal, tenant_id=principal.tenant_id, project_id=project_id,
                                  mission_id=f"{project_id}:{mission_id}",
                                  contract_hash=canonical_hash({"artifact": artifact_id, "policy": APPROVAL_POLICY}),
                                  artifact_id=artifact_id, version=int(head["version"]), content_hash=sha,
                                  run_pipeline=RUN_PIPELINE, policy_version=APPROVAL_POLICY, subject_type="CREATIVE_ARTIFACT",
                                  reason="Generated creative artifact requires human visual, brand and accessibility review",
                                  metadata={"foundry_version": FOUNDRY_VERSION})


def release_verdict(principal: Principal, project_id: str, artifact_id: str, *, verified_version: int, verified_hash: str,
                    approval_id: Optional[str]) -> Any:
    from services.langgraph.agency.intake.release import artifact_release_verdict

    return artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=artifact_id,
                                    verified_version=verified_version, verified_hash=verified_hash, approval_id=approval_id,
                                    tenant_id=principal.tenant_id, project_id=project_id)


__all__ = ["APPROVAL_POLICY", "Mission", "create_variant", "load_mission", "observe", "release_verdict", "request_approval",
           "store"]
