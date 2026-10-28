"""Render the brand book for a FICTIONAL brand into runtime/brandbook/demo/ (compiler + renderer + Chromium checks, no DB).

    python scripts/render_brandbook_demo.py

Writes book.html (editable source), prompts.json (24 self-contained page prompts), package.json, checks.json and
page-*.png raster previews when local Chromium is available. Every value is from the fictional test genome; nothing
here is a real brand, client or claim.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.langgraph.agency.foundry import compose  # noqa: E402
from services.langgraph.agency.vnexus.brandbook import checks, compiler, render  # noqa: E402
from services.langgraph.agency.vnexus.brandbook.assets import AssetKind, MarkAsset  # noqa: E402
from services.langgraph.agency.vnexus.brandbook.fields import EvidenceClass, EvidenceRecord  # noqa: E402
from services.langgraph.agency.vnexus.brandbook.manifest import Mode  # noqa: E402
from services.langgraph.agency.vnexus.bridge import GenomeProjection, creative_genome  # noqa: E402
from services.langgraph.agency.vnexus.genome import GenomeLayer, Scope, VersionStatus, resolve  # noqa: E402
from services.langgraph.agency.vnexus.identity import transparent_svg  # noqa: E402
from services.langgraph.agency.visual.browser import measure_layout, probe_browser  # noqa: E402
from services.langgraph.tests._vnexus_support import FULL_DOC  # noqa: E402
from services.langgraph.tests.test_vnexus_brandbook import DECIDED  # noqa: E402

OUT = ROOT / "runtime" / "brandbook" / "demo"
NAME = "Halden & Fen (fictional)"


def main() -> int:
    from services.langgraph.agency.vnexus.genome import document_from_flat

    doc = document_from_flat({**FULL_DOC.flatten(), **DECIDED}, constraints=list(FULL_DOC.constraints))
    res = resolve([GenomeLayer(scope=Scope.BRAND, scope_ref="demo", status=VersionStatus.APPROVED, document=doc, version_id="demo-v1")])
    p = GenomeProjection(res, brand_name=NAME, genome_ref="demo-v1")
    genome = creative_genome(p, project_id="demo")
    ir = compose.mark(genome, size=512)
    svg = transparent_svg(compose.to_svg(ir, genome), ir, genome)
    mark = MarkAsset(kind=AssetKind.VECTOR, sha256=hashlib.sha256(svg.encode()).hexdigest(), svg=svg, approved=True,
                     source="deterministic composition of visual.logo.mark=ring_dot")
    evidence = (EvidenceRecord(source_id="studio-visit", locator="studio visit notes (fictional)", evidence_class=EvidenceClass.USER_REPORTED,
                               observations=("matte glazes", "founder [PII] fires the kiln weekly"), privacy="contains_pii_redacted"),)
    ctx = compiler.BookContext(brand_id="demo", brand_name=NAME, genome_ref="demo-v1", resolution_hash=res.resolution_hash,
                               approved=dict(res.values), sources=dict(res.sources), mode=Mode.PREVIEW, mark=mark, evidence=evidence)
    book = compiler.compile_book(ctx)
    fields = render.style_values(book)
    name, w, h, _ = render.page_format(fields)
    sections = {pg.page_id: render.page_html(pg, mark=mark, brand_name=NAME, fields=fields, width=w, height=h, total=24) for pg in book.pages}
    style = render.css(fields, w, h)
    html = render.book_html([s for pg in book.pages for _, s in sections[pg.page_id]], title=f"{NAME} brand guidelines", style=style)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    all_checks = []
    if probe_browser().get("available"):
        with tempfile.TemporaryDirectory() as work:
            run = measure_layout(html, width=w, height=h, out_dir=Path(work), capture=True)
            measured = checks.measurement_for([pg.page_id for pg in book.pages], run["pages"])
            for pg in book.pages:
                all_checks += checks.static_checks(pg, sections[pg.page_id], mode=Mode.PREVIEW, palette=render.palette_for(fields)[0], neutral=False)
                all_checks += checks.measured_checks(pg, measured[pg.page_id], mark=mark, total=24)
            for pid in ("p01", "p06", "p07", "p14", "p15", "p16"):
                shutil.copy(Path(work) / run["captures"][pid], OUT / f"page-{pid}.png")
    book = compiler.compile_book(ctx, checks=all_checks or None, reuse={pg.dependency_hash: pg for pg in book.pages})
    (OUT / "book.html").write_text(html, encoding="utf-8")
    (OUT / "package.json").write_text(json.dumps(book.model_dump(mode="json"), indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "prompts.json").write_text(json.dumps({pg.page_id: compiler.standalone_prompt(pg) for pg in book.pages}, indent=1,
                                                 ensure_ascii=False) + "\n", encoding="utf-8")
    summary = checks.summarize(all_checks)
    (OUT / "checks.json").write_text(json.dumps({"format": name, "summary": summary, "measured": bool(all_checks),
                                                 "checks": all_checks}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(book.pages)} pages, package {book.package_hash[:16]}, checks {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
