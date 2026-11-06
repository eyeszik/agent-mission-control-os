"""Semantic lineage: does every requirement survive IR -> source -> rendered DOM?

Each stage is checked against what that stage actually produced:

* ``ir``       -- the WebsiteIR / SiteArchitecture (and ``site.check_colour_plan``);
* ``source``   -- the generated tree: ``content/site.json`` plus the manifest's per-file ``req_refs``;
* ``rendered`` -- the BrowserVerification's DOM evidence (``data-req`` elements) and typed checks.

Statuses are computed, never asserted. A stage that was not evaluated is ``NOT_RUN`` and
leaves the requirement ``UNRESOLVED``; NOT_RUN never counts as preserved. A loss is
``OMITTED`` (missing) or ``UNAPPROVED_CHANGE`` (present but different), with the first stage
that lost it. ``APPROVED_CHANGE`` needs an approval reference supplied by the caller from a
decided approval; this module never grants one.

``IntentLinker`` answers TRACE / INSPECT / COMPARE / FIND_OMISSIONS / IMPACT_ANALYSIS /
PROPOSE_REPAIR from the same evidence. It proposes; it never applies a repair.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .contracts import (
    BrowserVerification,
    CoverageEntry,
    Requirement,
    RequirementsPackage,
    SemanticCoverageReport,
    SemanticDebtEntry,
    SiteArchitecture,
    SourceTreeManifest,
    WebsiteIR,
)
from .requirements import diff_requirements
from .site import check_colour_plan, ir_texts

Verdict = tuple[str, str]  # ("PASS" | "FAIL" | "NOT_RUN" | "N/A", detail); FAIL detail starts "missing" or "changed"
STAGES = ("ir", "source", "rendered")
REPAIR_OWNER = {"ir": "design_lead", "source": "implementation_lead", "rendered": "implementation_lead",
                None: "brand_safety_reviewer"}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _match(found: list[str], expected: str) -> Verdict:
    if not found:
        return "FAIL", "missing"
    if norm(expected) in (norm(f) for f in found):
        return "PASS", ""
    return "FAIL", f"changed: expected {expected!r}, found {found[:2]!r}"


# ------------------------------------------------------------------------------ ir


def _ir_section(ir: WebsiteIR, req_id: str):
    for page in ir.pages:
        for s in page.sections:
            for field, ref in s.req_refs.items():
                if ref == req_id:
                    return page, s, field
    return None, None, None


def ir_stage(pkg: RequirementsPackage, arch: Optional[SiteArchitecture], ir: Optional[WebsiteIR]) -> dict[str, Verdict]:
    out: dict[str, Verdict] = {}
    if ir is None:
        return {r.req_id: ("NOT_RUN" if "ir" in r.stages else "N/A", "no WebsiteIR") for r in pkg.requirements}
    texts = [t.lower() for t in ir_texts(ir)]
    pages = {p.page_id: p for p in ir.pages}
    images = {i.asset_id: i for i in ir.images}
    colour_errors = check_colour_plan(ir)
    for r in pkg.requirements:
        if "ir" not in r.stages:
            out[r.req_id] = ("N/A", "")
            continue
        subj = r.subject
        if r.kind == "LANG":
            out[r.req_id] = ("PASS", "") if ir.locale == subj["text"] else ("FAIL", f"changed: locale {ir.locale}")
        elif r.kind == "BRAND_ON_PAGE":
            out[r.req_id] = _match([ir.organization], subj["text"])
        elif r.kind == "PAGE_EXISTS":
            p = pages.get(subj["page"])
            out[r.req_id] = ("FAIL", "missing") if p is None else (
                ("PASS", "") if p.title == subj["text"] and p.route == subj["route"] else ("FAIL", f"changed: {p.title} {p.route}"))
        elif r.kind == "NAV_LINK":
            nav = arch.navigation if arch else ()
            out[r.req_id] = ("PASS", "") if subj["page"] in nav and subj["page"] in pages else ("FAIL", "missing")
        elif r.kind in {"SECTION_HEADING", "SECTION_BODY", "LABEL_TEXT", "ITEM_TEXT", "CTA"}:
            _, s, field = _ir_section(ir, r.req_id)
            if s is None:
                out[r.req_id] = ("FAIL", "missing")
            elif r.kind == "ITEM_TEXT":
                index = int(field.split(":")[1])
                if index >= len(s.items):
                    out[r.req_id] = ("FAIL", "missing: item not in IR")
                    continue
                item = s.items[index]
                out[r.req_id] = ("PASS", "") if (item.title, item.body) == (subj["text"], subj["body"]) else (
                    "FAIL", f"changed: {item.title!r}")
            elif r.kind == "CTA":
                out[r.req_id] = ("PASS", "") if s.cta == {"label": subj["text"], "href": subj["href"]} else (
                    "FAIL", f"changed: {s.cta}")
            else:
                out[r.req_id] = _match([getattr(s, field)], subj["text"])
        elif r.kind == "IMAGE_ALT":
            img = images.get(subj["asset_id"])
            out[r.req_id] = ("FAIL", "missing") if img is None else _match([img.alt], subj["text"])
        elif r.kind == "IMAGE_RIGHTS":
            img = images.get(subj["asset_id"])
            out[r.req_id] = ("FAIL", "missing") if img is None else (
                ("PASS", "") if img.rights == subj["rights"] and (img.license_ref or "") == subj["license_ref"]
                else ("FAIL", "changed: rights"))
        elif r.kind == "REQUIRED_PHRASE":
            out[r.req_id] = ("PASS", "") if any(subj["text"].lower() in t for t in texts) else ("FAIL", "missing")
        elif r.kind == "FORBIDDEN_PHRASE":
            hit = [t for t in texts if subj["text"].lower() in t]
            out[r.req_id] = ("FAIL", f"changed: forbidden phrase present in {hit[0][:80]!r}") if hit else ("PASS", "")
        elif r.kind == "PSEM_COLOUR":
            out[r.req_id] = ("FAIL", "changed: " + "; ".join(colour_errors)) if colour_errors else ("PASS", "")
        else:
            out[r.req_id] = ("NOT_RUN", f"no ir evaluator for {r.kind}")
    return out


# ------------------------------------------------------------------------------ source


def source_stage(pkg: RequirementsPackage, files: Optional[dict[str, bytes]],
                 manifest: Optional[SourceTreeManifest]) -> dict[str, Verdict]:
    if files is None or manifest is None or "content/site.json" not in files:
        return {r.req_id: ("NOT_RUN" if "source" in r.stages else "N/A", "no source tree") for r in pkg.requirements}
    content = json.loads(files["content/site.json"])
    bound = {ref for f in manifest.files for ref in f.req_refs}
    sections = {ref: (s, field) for page in content["pages"].values() for s in page["sections"]
                for field, ref in s["req_refs"].items()}
    blob = files["content/site.json"].decode("utf-8").lower()
    out: dict[str, Verdict] = {}
    for r in pkg.requirements:
        if "source" not in r.stages:
            out[r.req_id] = ("N/A", "")
            continue
        subj = r.subject
        if r.req_id not in bound and r.kind not in {"REQUIRED_PHRASE", "FORBIDDEN_PHRASE"}:
            out[r.req_id] = ("FAIL", "missing: no source file binds this requirement")
            continue
        if r.kind == "LANG":
            out[r.req_id] = _match([content["locale"]], subj["text"])
        elif r.kind == "BRAND_ON_PAGE":
            out[r.req_id] = _match([content["organization"]], subj["text"])
        elif r.kind == "PAGE_EXISTS":
            page = content["pages"].get(subj["page"])
            path = "app/page.tsx" if subj["page"] == "index" else f"app/{subj['page']}/page.tsx"
            out[r.req_id] = ("FAIL", "missing") if page is None or path not in files else _match([page["title"]], subj["text"])
        elif r.kind == "NAV_LINK":
            nav = {n["page_id"]: n for n in content["nav"]}
            n = nav.get(subj["page"])
            out[r.req_id] = ("FAIL", "missing") if n is None else (
                ("PASS", "") if (n["title"], n["href"]) == (subj["text"], subj["href"]) else ("FAIL", f"changed: {n}"))
        elif r.kind in {"SECTION_HEADING", "SECTION_BODY", "LABEL_TEXT", "ITEM_TEXT", "CTA"}:
            hit = sections.get(r.req_id)
            if hit is None:
                out[r.req_id] = ("FAIL", "missing")
                continue
            s, field = hit
            if r.kind == "ITEM_TEXT":
                index = int(field.split(":")[1])
                if index >= len(s["items"]):
                    out[r.req_id] = ("FAIL", "missing: item not in content")
                    continue
                item = s["items"][index]
                out[r.req_id] = ("PASS", "") if (item["title"], item["body"]) == (subj["text"], subj["body"]) else (
                    "FAIL", "changed")
            elif r.kind == "CTA":
                out[r.req_id] = ("PASS", "") if s["cta"] == {"label": subj["text"], "href": subj["href"]} else ("FAIL", "changed")
            else:
                out[r.req_id] = _match([s[field]], subj["text"])
        elif r.kind in {"IMAGE_ALT", "IMAGE_RIGHTS"}:
            img = content["images"].get(subj["asset_id"])
            asset = f"public/assets/{subj['asset_id']}.svg"
            if img is None or asset not in files:
                out[r.req_id] = ("FAIL", "missing")
            elif r.kind == "IMAGE_ALT":
                out[r.req_id] = _match([img["alt"]], subj["text"])
            else:
                out[r.req_id] = ("PASS", "") if img["rights"] == subj["rights"] and (img["license_ref"] or "") == subj[
                    "license_ref"] else ("FAIL", "changed: rights")
        elif r.kind == "REQUIRED_PHRASE":
            out[r.req_id] = ("PASS", "") if subj["text"].lower() in blob else ("FAIL", "missing")
        elif r.kind == "FORBIDDEN_PHRASE":
            out[r.req_id] = ("FAIL", "changed: forbidden phrase in content") if subj["text"].lower() in blob else ("PASS", "")
        else:
            out[r.req_id] = ("NOT_RUN", f"no source evaluator for {r.kind}")
    return out


# ------------------------------------------------------------------------------ rendered


def rendered_stage(pkg: RequirementsPackage, v: Optional[BrowserVerification]) -> dict[str, Verdict]:
    if v is None or v.status in {"BLOCKED", "NOT_RUN"} and not v.dom_evidence:
        why = "no browser verification" if v is None else f"browser verification {v.status}"
        return {r.req_id: ("NOT_RUN" if "rendered" in r.stages else "N/A", why) for r in pkg.requirements}
    ev = v.dom_evidence
    routes = sorted(ev)
    every = lambda req_id, expected: (  # noqa: E731 - every route must evidence it
        ("FAIL", "missing: no routes rendered") if not routes else next(
            ((verdict, f"{route}: {d}") for route in routes for verdict, d in [_match(_visible(ev[route].get(req_id, [])), expected)]
             if verdict != "PASS"), ("PASS", "")))
    out: dict[str, Verdict] = {}
    for r in pkg.requirements:
        if "rendered" not in r.stages:
            out[r.req_id] = ("N/A", "")
            continue
        subj = r.subject
        if r.kind == "LANG":
            out[r.req_id] = every("req.lang", subj["text"])
        elif r.kind == "BRAND_ON_PAGE":
            out[r.req_id] = every("req.brand", subj["text"] + " -> /")
        elif r.kind == "NAV_LINK":
            out[r.req_id] = every(r.req_id, f"{subj['text']} -> {subj['href']}")
        elif r.kind == "PAGE_EXISTS":
            page = ev.get(subj["route"])
            if page is None:
                out[r.req_id] = ("FAIL", "missing: route not rendered")
            else:
                title = (page.get("__title__") or [""])[0]
                out[r.req_id] = ("PASS", "") if subj["text"] in title and page.get(r.req_id) else ("FAIL", f"changed: title {title!r}")
        elif r.kind in {"SECTION_HEADING", "SECTION_BODY", "LABEL_TEXT", "CTA", "ITEM_TEXT"}:
            found = _visible(ev.get(subj["route"], {}).get(r.req_id, []))
            if r.kind == "CTA":
                out[r.req_id] = _match(found, f"{subj['text']} -> {subj['href']}")
            elif r.kind == "ITEM_TEXT":
                want = norm(subj["text"]) + (f" | {norm(subj['body'])}" if subj["body"] else "")
                out[r.req_id] = _match(found, want)
            else:
                out[r.req_id] = _match(found, subj["text"])
        elif r.kind == "IMAGE_ALT":
            found = [t for route in routes for t in _visible(ev[route].get(r.req_id, []))]
            out[r.req_id] = _match(found, subj["text"])
        elif r.kind in {"REQUIRED_PHRASE", "FORBIDDEN_PHRASE"}:
            hay = " ".join((ev[route].get("__text__") or [""])[0].lower() for route in routes)
            hay += " " + " ".join(t.lower() for route in routes for k, ts in ev[route].items() if k.startswith("req.image.") for t in ts)
            present = subj["text"].lower() in hay
            if r.kind == "REQUIRED_PHRASE":
                out[r.req_id] = ("PASS", "") if present else ("FAIL", "missing")
            else:
                out[r.req_id] = ("FAIL", "changed: forbidden phrase rendered") if present else ("PASS", "")
        else:
            related = [c for c in v.checks if r.req_id in c.req_refs]
            results = {c.result for c in related}
            if not related:
                out[r.req_id] = ("NOT_RUN", "no check evidences this requirement")
            elif "FAIL" in results:
                bad = next(c for c in related if c.result == "FAIL")
                out[r.req_id] = ("FAIL", f"changed: {bad.check} {bad.route or ''} {bad.viewport or ''}: {bad.detail[:200]}")
            elif results == {"PASS"}:
                out[r.req_id] = ("PASS", f"{len(related)} checks")
            else:
                out[r.req_id] = ("NOT_RUN", f"checks {sorted(results)}")
    return out


def _visible(texts: list[str]) -> list[str]:
    return [t for t in texts if not t.startswith("__hidden__:")]


# ------------------------------------------------------------------------------ coverage + debt


def _proposal(r: Requirement, stage: Optional[str], detail: str) -> str:
    if stage is None:
        return "Run the missing stage (build and browser verification in the sandbox); nothing is assumed preserved."
    if r.kind in {"SECTION_HEADING", "SECTION_BODY", "LABEL_TEXT", "ITEM_TEXT", "CTA", "IMAGE_ALT", "NAV_LINK", "PAGE_EXISTS",
                  "BRAND_ON_PAGE", "LANG"}:
        return f"Regenerate from the brief at {r.source_ref}; the {stage} stage must carry the text verbatim with data-req={r.req_id}."
    if r.kind == "REQUIRED_PHRASE":
        return f"Add {r.subject['text']!r} to the brief copy (an operator edit), then regenerate. The compiler never writes copy."
    if r.kind == "FORBIDDEN_PHRASE":
        return f"Remove {r.subject['text']!r} from the brief copy, then regenerate."
    if r.kind == "PSEM_COLOUR":
        return "Use only legal PSEM pairings: accents only on charcoal; fog on paper only for large text or graphics."
    return f"Fix the template behaviour behind {r.kind} ({detail[:120]}), regenerate and re-verify."


def coverage_report(pkg: RequirementsPackage, stage_results: dict[str, dict[str, Verdict]], *,
                    approved_changes: Optional[dict[str, str]] = None,
                    artifacts: Optional[dict[str, str]] = None) -> SemanticCoverageReport:
    approved = approved_changes or {}
    entries: list[CoverageEntry] = []
    debt: list[SemanticDebtEntry] = []
    for r in pkg.requirements:
        stages = {s: stage_results.get(s, {}).get(r.req_id, ("NOT_RUN", "stage not evaluated"))
                  if s in r.stages else ("N/A", "") for s in STAGES}
        loss = next((s for s in STAGES if stages[s][0] == "FAIL"), None)
        if loss:
            status = "OMITTED" if stages[loss][1].startswith("missing") else "UNAPPROVED_CHANGE"
            if r.req_id in approved and status == "UNAPPROVED_CHANGE":
                status = "APPROVED_CHANGE"
            detail = stages[loss][1]
        elif any(stages[s][0] == "NOT_RUN" for s in STAGES):
            status, detail = "UNRESOLVED", "; ".join(f"{s}: {stages[s][1]}" for s in STAGES if stages[s][0] == "NOT_RUN")
        else:
            status, detail = "PRESERVED", ""
        if not r.mandatory and status not in {"PRESERVED", "APPROVED_CHANGE"}:
            status = "NOT_APPLICABLE" if status == "UNRESOLVED" else status
        entries.append(CoverageEntry(req_id=r.req_id, kind=r.kind, mandatory=r.mandatory, status=status,
                                     stages={s: v[0] for s, v in stages.items()}, loss_stage=loss, detail=detail[:400]))
        if r.mandatory and status not in {"PRESERVED", "APPROVED_CHANGE"}:
            debt.append(SemanticDebtEntry(
                req_id=r.req_id, origin_revision=pkg.content_hash, loss_stage=loss,
                affected_artifacts=tuple(sorted(v for k, v in (artifacts or {}).items() if loss is None or k == loss)),
                severity="blocking", repair_owner=REPAIR_OWNER[loss], repair_proposal=_proposal(r, loss, detail),
                verification=f"re-run the {loss or 'missing'} stage and the rendered verification; status must be PRESERVED"))
    applicable = [e for e in entries if e.mandatory]
    resolved = [e for e in applicable if e.status in {"PRESERVED", "APPROVED_CHANGE"}]
    return SemanticCoverageReport(
        requirements_ref=pkg.content_hash, entries=tuple(entries), mandatory_resolved=len(resolved),
        mandatory_applicable=len(applicable),
        coverage=round(len(resolved) / len(applicable), 4) if applicable else "NOT_APPLICABLE",
        debt=tuple(debt), release_blocked=bool(debt))


def evaluate(pkg: RequirementsPackage, *, arch: Optional[SiteArchitecture] = None, ir: Optional[WebsiteIR] = None,
             files: Optional[dict[str, bytes]] = None, manifest: Optional[SourceTreeManifest] = None,
             verification: Optional[BrowserVerification] = None, approved_changes: Optional[dict[str, str]] = None,
             artifacts: Optional[dict[str, str]] = None) -> tuple[SemanticCoverageReport, dict[str, dict[str, Verdict]]]:
    stages = {"ir": ir_stage(pkg, arch, ir), "source": source_stage(pkg, files, manifest),
              "rendered": rendered_stage(pkg, verification)}
    return coverage_report(pkg, stages, approved_changes=approved_changes, artifacts=artifacts), stages


# ------------------------------------------------------------------------------ intent linker


class IntentLinker:
    """Read-only questions over one production line's evidence."""

    def __init__(self, pkg: RequirementsPackage, report: SemanticCoverageReport, *, ir: Optional[WebsiteIR] = None,
                 manifest: Optional[SourceTreeManifest] = None, verification: Optional[BrowserVerification] = None):
        if report.requirements_ref != pkg.content_hash:
            raise ValueError("coverage report belongs to a different requirements package")
        self.pkg, self.report, self.ir, self.manifest, self.verification = pkg, report, ir, manifest, verification
        self._reqs = pkg.by_id()
        self._entries = {e.req_id: e for e in report.entries}

    def _require(self, req_id: str) -> Requirement:
        if req_id not in self._reqs:
            raise KeyError(f"unknown requirement {req_id}")
        return self._reqs[req_id]

    def trace(self, req_id: str) -> dict[str, Any]:
        r = self._require(req_id)
        ir_nodes = []
        if self.ir:
            for page in self.ir.pages:
                if req_id in page.req_refs.values():
                    ir_nodes.append(f"page:{page.page_id}")
                for s in page.sections:
                    ir_nodes += [f"section:{s.section_id}.{field}" for field, ref in s.req_refs.items() if ref == req_id]
        files = [f.path for f in self.manifest.files if req_id in f.req_refs] if self.manifest else []
        rendered = {route: texts for route, ev in (self.verification.dom_evidence if self.verification else {}).items()
                    for k, texts in [(req_id, ev.get(req_id))] if texts}
        checks = [c.model_dump(mode="json") for c in (self.verification.checks if self.verification else ()) if req_id in c.req_refs]
        return {"requirement": r.model_dump(mode="json"), "status": self._entries[req_id].model_dump(mode="json"),
                "ir": ir_nodes, "source": files, "rendered": rendered, "checks": checks}

    def inspect(self, target: str) -> dict[str, Any]:
        """Requirements bound to a section id, a source path or a route."""
        bound: set[str] = set()
        if self.ir:
            for page in self.ir.pages:
                if target in {page.page_id, page.route}:
                    bound |= set(page.req_refs.values()) | {ref for s in page.sections for ref in s.req_refs.values()}
                for s in page.sections:
                    if s.section_id == target:
                        bound |= set(s.req_refs.values())
        if self.manifest:
            for f in self.manifest.files:
                if f.path == target:
                    bound |= set(f.req_refs)
        if self.verification and target in self.verification.dom_evidence:
            bound |= {k for k in self.verification.dom_evidence[target] if k.startswith("req.")}
        return {"target": target, "requirements": [
            {"req_id": k, "status": self._entries[k].status} for k in sorted(bound) if k in self._entries]}

    @staticmethod
    def compare(old: RequirementsPackage, new: RequirementsPackage) -> dict[str, Any]:
        d = diff_requirements(old, new)
        a, b = old.by_id(), new.by_id()
        return {**d, "details": {k: {"before": a[k].subject, "after": b[k].subject} for k in d["changed"]}}

    def find_omissions(self) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in self.report.entries
                if e.status in {"OMITTED", "UNAPPROVED_CHANGE", "UNRESOLVED"}]

    def impact_analysis(self, req_ids: list[str]) -> dict[str, Any]:
        """What a change to these requirements touches, and what must be regenerated and re-verified."""
        for req_id in req_ids:
            self._require(req_id)
        traces = [self.trace(r) for r in req_ids]
        stages = sorted({s for r in req_ids for s in self._reqs[r].stages})
        return {"requirements": req_ids, "ir_nodes": sorted({n for t in traces for n in t["ir"]}),
                "source_files": sorted({f for t in traces for f in t["source"]}),
                "routes": sorted({route for t in traces for route in t["rendered"]}),
                "checks": sorted({c["check"] for t in traces for c in t["checks"]}),
                "regenerate": ["requirements", "site_ir", "source", "build", "browser_qa", "coverage", "release_proof"],
                "stages_to_reverify": stages,
                "invalidates": "approvals and release proofs bound to earlier revisions become stale"}

    def propose_repair(self, req_id: str) -> dict[str, Any]:
        self._require(req_id)
        entry = next((d for d in self.report.debt if d.req_id == req_id), None)
        if entry is None:
            return {"req_id": req_id, "proposal": None, "reason": f"no open debt; status {self._entries[req_id].status}"}
        return {"req_id": req_id, "proposal": entry.repair_proposal, "owner": entry.repair_owner,
                "verification": entry.verification, "applied": False}


__all__ = ["IntentLinker", "STAGES", "coverage_report", "evaluate", "ir_stage", "norm", "rendered_stage", "source_stage"]
