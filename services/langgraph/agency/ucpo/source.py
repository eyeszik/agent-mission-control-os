"""WebsiteIR -> a Next.js static-export source tree, with a per-file SHA-256 manifest.

The generated tree is untrusted until the build sandbox has built it. It is produced
from fixed templates plus one data file (``content/site.json``); brief copy is data,
never code, and React escapes it on render. Every text-bearing element carries a
``data-req`` attribute with the requirement id it satisfies, which is how the browser
verifier traces a requirement to the DOM.

Rules enforced here, before anything is written or built:

* paths are relative, inside an allowlisted layout, with no traversal segments;
* code files are scanned for forbidden constructs (raw HTML injection, ``eval``,
  dynamic code, process access, network calls, external URLs);
* SVG assets are scanned for scripts, event handlers and external references;
* dependencies are the exact versions installed in ``apps/web`` (no install step ever runs).

``reconcile_tree`` preserves human edits on regeneration: a file whose bytes on disk no
longer match the previous manifest is left alone and reported, never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.contracts import CreativeGenome

from .contracts import SourceFile, SourceTreeManifest, WebsiteIR

# Exact versions, as pinned in apps/web/package.json and installed by the workspace lockfile.
# The build verifies the installed packages match before it runs anything.
DEPENDENCIES = {
    "next": "16.4.2",
    "react": "19.3.1",
    "react-dom": "19.3.1",
}
DEV_DEPENDENCIES = {
    "typescript": "7.0.2",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
}
ROOT_FILES = {"package.json", "next.config.mjs", "tsconfig.json", "amc-env.d.ts", "UCPO.md"}
TOP_DIRS = {"app", "components", "lib", "content", "public"}
CODE_SUFFIXES = {".ts", ".tsx", ".mjs", ".css"}
_W3_NS = ("http://www.w3.org/2000/svg",)
FORBIDDEN_CODE = (
    ("dangerouslySetInnerHTML", re.compile(r"dangerouslySetInnerHTML")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("new Function", re.compile(r"\bnew\s+Function\b")),
    ("dynamic import", re.compile(r"\bimport\s*\(")),
    ("require", re.compile(r"\brequire\s*\(")),
    ("process access", re.compile(r"\bprocess\.")),
    ("child_process", re.compile(r"child_process")),
    ("network call", re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b")),
    ("external url", re.compile(r"(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}", re.I)),
    ("css import", re.compile(r"@import")),
    ("script tag", re.compile(r"<script", re.I)),
)
FORBIDDEN_SVG = (
    ("script", re.compile(r"<script", re.I)),
    ("event handler", re.compile(r"\son[a-z]+\s*=", re.I)),
    ("foreign object", re.compile(r"<foreignObject", re.I)),
    ("external reference", re.compile(r"(?:href|src)\s*=\s*[\"'](?!#)", re.I)),
    ("url()", re.compile(r"url\(\s*[\"']?(?!#)", re.I)),
)


class SourcePolicyError(ValueError):
    pass


def check_path(path: str) -> None:
    p = PurePosixPath(path)
    # Raw segments, not PurePosixPath.parts: the latter silently drops "." and empty segments.
    if not path or path.startswith("/") or "\\" in path or p.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        raise SourcePolicyError(f"unsafe path {path!r}")
    if len(p.parts) == 1:
        if path not in ROOT_FILES:
            raise SourcePolicyError(f"{path!r} is not an allowed root file")
    elif p.parts[0] not in TOP_DIRS:
        raise SourcePolicyError(f"{path!r} is outside the allowed layout")
    if not re.fullmatch(r"[A-Za-z0-9._/\[\]-]+", path):
        raise SourcePolicyError(f"{path!r} has characters outside the allowed set")


def scan(path: str, data: bytes) -> list[str]:
    """Forbidden constructs in one generated file. Content JSON is data and is not scanned for code."""
    text = data.decode("utf-8")
    suffix = PurePosixPath(path).suffix
    findings: list[str] = []
    if suffix in CODE_SUFFIXES:
        for name, rx in FORBIDDEN_CODE:
            if rx.search(text):
                findings.append(f"{path}: {name}")
    elif suffix == ".svg":
        stripped = text
        for ns in _W3_NS:
            stripped = stripped.replace(f'xmlns="{ns}"', "")
        for name, rx in FORBIDDEN_SVG:
            if rx.search(stripped):
                findings.append(f"{path}: {name}")
    return findings


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _doc_title(page_title: str, organization: str) -> str:
    return page_title if page_title == organization else f"{page_title} · {organization}"


def site_content(ir: WebsiteIR) -> dict:
    """The data file the templates render. A projection of the IR; nothing is added."""
    return {
        "schema_version": "amc-ucpo-site-content/v1",
        "website_ir": ir.content_hash,
        "organization": ir.organization,
        "tagline": ir.tagline,
        "locale": ir.locale,
        "brand_req": "req.brand",
        "nav": [{"page_id": p.page_id, "href": p.route, "title": p.title, "req": f"req.nav.{p.page_id}"} for p in ir.pages],
        "pages": {p.page_id: {
            "route": p.route, "title": p.title, "doc_title": _doc_title(p.title, ir.organization),
            "description": p.description, "req": p.req_refs["page"],
            "sections": [s.model_dump(mode="json") for s in p.sections],
        } for p in ir.pages},
        "images": {i.asset_id: {"src": f"/assets/{i.asset_id}.svg", "alt": i.alt, "rights": i.rights,
                                "license_ref": i.license_ref, "width": 1200, "height": 800} for i in ir.images},
    }


STRUCTURE_CSS = """
/* Structure: PSEM editorial modernism. Colours come only from the token variables above. */
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
body { margin: 0; background: var(--amc-color-paper); color: var(--amc-color-ink); font-family: var(--amc-font-text);
  font-size: 1rem; line-height: 1.55; overflow-wrap: break-word; }
img { max-width: 100%; height: auto; display: block; }
a { color: inherit; text-underline-offset: 0.2em; transition: text-decoration-color var(--amc-motion-duration) var(--amc-motion-easing); }
:focus-visible { outline: var(--amc-focus-ring) solid var(--amc-color-ink); outline-offset: 3px; }
.sec--charcoal :focus-visible, .site-footer :focus-visible { outline-color: var(--amc-color-paper); }
.skip { position: absolute; left: var(--amc-space-s3); top: -100px; z-index: 10; padding: var(--amc-space-s2) var(--amc-space-s3);
  background: var(--amc-color-ink); color: var(--amc-color-paper); }
.skip:focus { top: var(--amc-space-s3); outline-color: var(--amc-color-paper); }
.site-header { display: flex; flex-wrap: wrap; gap: var(--amc-space-s3) var(--amc-space-s5); align-items: baseline;
  justify-content: space-between; padding: var(--amc-space-s4) clamp(1rem, 5vw, 4rem); border-bottom: 1px solid var(--amc-color-muted); }
.brand { font-family: var(--amc-font-display); font-weight: var(--amc-weight-display); letter-spacing: -0.02em;
  font-size: 1.25rem; text-decoration: none; color: var(--amc-color-ink); }
.nav ul { display: flex; flex-wrap: wrap; gap: var(--amc-space-s2) var(--amc-space-s4); margin: 0; padding: 0; list-style: none; }
.nav a { display: inline-block; min-height: var(--amc-target-min); padding: 0.6rem 0; color: var(--amc-color-graphite);
  font-family: var(--amc-font-mono); font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.06em; }
.nav a[aria-current="page"] { color: var(--amc-color-ink); text-decoration-thickness: 2px; }
main:focus { outline: none; }
.sec { position: relative; padding: clamp(3rem, 9vw, 9rem) clamp(1rem, 5vw, 4rem); }
.sec--paper { background: var(--amc-color-paper); color: var(--amc-color-ink); --label: var(--amc-color-graphite);
  --rule: var(--amc-color-muted); --serial: var(--amc-color-graphite); --cta-bg: var(--amc-color-ink); --cta-fg: var(--amc-color-paper); }
.sec--charcoal { background: var(--amc-color-ink); color: var(--amc-color-paper); --label: var(--amc-color-muted);
  --rule: var(--amc-color-muted); --serial: var(--amc-color-paper); --cta-bg: var(--amc-color-paper); --cta-fg: var(--amc-color-ink); }
.sec--charcoal[data-accent="signal_red"] { --rule: var(--amc-color-accent); --serial: var(--amc-color-accent);
  --cta-bg: var(--amc-color-accent); }
.sec--charcoal[data-accent="amber"] { --rule: var(--amc-color-accent-2); --serial: var(--amc-color-accent-2);
  --cta-bg: var(--amc-color-accent-2); }
.sec__meta { display: flex; flex-wrap: wrap; gap: var(--amc-space-s4); padding-top: var(--amc-space-s3);
  border-top: 1px solid var(--rule); font-family: var(--amc-font-mono); font-size: 0.8125rem; letter-spacing: 0.08em;
  text-transform: uppercase; }
.sec__serial { color: var(--serial); }
.sec__label { color: var(--label); }
.sec__heading { margin: clamp(2rem, 6vw, 5rem) 0 var(--amc-space-s4); max-width: 18ch; font-family: var(--amc-font-display);
  font-weight: var(--amc-weight-display); letter-spacing: -0.035em; line-height: 1.02; font-size: clamp(2.25rem, 7vw, 6rem); }
h2.sec__heading { font-size: clamp(1.875rem, 5vw, 4rem); }
.sec__body { margin: 0 0 var(--amc-space-s5); max-width: 62ch; font-size: clamp(1rem, 1.6vw, 1.1875rem); }
.sec__items { margin: 0; padding: 0; list-style: none; max-width: 68ch; }
.sec__items li { display: grid; gap: var(--amc-space-s1); padding: var(--amc-space-s3) 0; border-top: 1px solid var(--rule); }
.item__title { font-weight: 700; }
.sec__plate { margin: 0 0 var(--amc-space-s5); max-width: 960px; }
.cta { display: inline-flex; align-items: center; min-height: var(--amc-target-min); padding: 0.7rem 1.4rem;
  background: var(--cta-bg); color: var(--cta-fg); font-weight: 700; text-decoration: none; }
.sec--statement .sec__heading { max-width: 22ch; }
.site-footer { display: flex; flex-wrap: wrap; gap: var(--amc-space-s3) var(--amc-space-s5); justify-content: space-between;
  padding: var(--amc-space-s5) clamp(1rem, 5vw, 4rem); background: var(--amc-color-ink); color: var(--amc-color-paper); }
.site-footer small { color: var(--amc-color-muted); font-size: 0.875rem; max-width: 60ch; }
@media (min-width: 1024px) {
  .sec { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: 2vw; }
  .sec > * { grid-column: 1 / -1; }
  .sec__heading { grid-column: 1 / span 9; }
  .sec__body, .sec__items, .sec__cta { grid-column: 4 / span 7; }
  .sec__plate { grid-column: 1 / span 10; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
"""

LIB_SITE = '''import content from "../content/site.json";

export type Item = { title: string; body: string };
export type Cta = { label: string; href: string };
export type SectionData = {
  section_id: string;
  kind: string;
  component_id: string;
  scheme: "paper" | "charcoal";
  accent: "signal_red" | "amber" | "none";
  serial: string;
  label: string;
  heading: string;
  body: string;
  items: Item[];
  image: string | null;
  cta: Cta | null;
  req_refs: Record<string, string>;
};
export type PageData = {
  route: string;
  title: string;
  doc_title: string;
  description: string;
  req: string;
  sections: SectionData[];
};
export type ImageData = { src: string; alt: string; rights: string; license_ref: string | null; width: number; height: number };
export type NavEntry = { page_id: string; href: string; title: string; req: string };
export type SiteContent = {
  organization: string;
  tagline: string;
  locale: string;
  brand_req: string;
  nav: NavEntry[];
  pages: Record<string, PageData>;
  images: Record<string, ImageData>;
};

export const site = content as unknown as SiteContent;

export function page(pageId: string): PageData {
  const found = site.pages[pageId];
  if (!found) throw new Error(`unknown page ${pageId}`);
  return found;
}
'''

LAYOUT = '''import type { ReactNode } from "react";
import "./globals.css";
import { site } from "../lib/site";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang={site.locale} data-req="req.lang">
      <body>{children}</body>
    </html>
  );
}
'''

HEADER = '''import { site } from "../lib/site";

export function SiteHeader({ current }: { current: string }) {
  return (
    <header className="site-header">
      <a className="skip" href="#main">Skip to content</a>
      <a className="brand" href="/" data-req={site.brand_req}>{site.organization}</a>
      <nav className="nav" aria-label="Primary">
        <ul>
          {site.nav.map((entry) => (
            <li key={entry.page_id}>
              <a href={entry.href} data-req={entry.req} aria-current={entry.page_id === current ? "page" : undefined}>
                {entry.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
'''

FOOTER = '''import { site } from "../lib/site";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <span>{site.organization}</span>
      {site.tagline ? <small>{site.tagline}</small> : null}
    </footer>
  );
}
'''

SECTION = '''import { site, type SectionData } from "../lib/site";

export function Section({ s, first }: { s: SectionData; first: boolean }) {
  const Heading = first ? "h1" : "h2";
  const image = s.image ? site.images[s.image] : undefined;
  return (
    <section id={s.section_id} className={`sec sec--${s.scheme} sec--${s.kind}`} data-accent={s.accent}
      aria-labelledby={`${s.section_id}-h`}>
      <div className="sec__meta">
        <span className="sec__serial">{s.serial}</span>
        {s.label ? <span className="sec__label" data-req={s.req_refs.label}>{s.label}</span> : null}
      </div>
      <Heading id={`${s.section_id}-h`} className="sec__heading" data-req={s.req_refs.heading}>{s.heading}</Heading>
      {image ? (
        <figure className="sec__plate">
          <img src={image.src} alt={image.alt} width={image.width} height={image.height} data-req={s.req_refs.image} />
        </figure>
      ) : null}
      {s.body ? <p className="sec__body" data-req={s.req_refs.body}>{s.body}</p> : null}
      {s.items.length ? (
        <ul className="sec__items">
          {s.items.map((item, i) => (
            <li key={i} data-req={s.req_refs[`item:${i}`]}>
              <span className="item__title">{item.title}</span>
              {item.body ? <span className="item__body">{item.body}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {s.cta ? (
        <p className="sec__cta"><a className="cta" href={s.cta.href} data-req={s.req_refs.cta}>{s.cta.label}</a></p>
      ) : null}
    </section>
  );
}
'''

PAGE_VIEW = '''import type { Metadata } from "next";
import { page, site } from "../lib/site";
import { Section } from "./Section";
import { SiteFooter } from "./SiteFooter";
import { SiteHeader } from "./SiteHeader";

export function pageMetadata(pageId: string): Metadata {
  const p = page(pageId);
  return { title: p.doc_title, description: p.description };
}

export function PageView({ pageId }: { pageId: string }) {
  const p = page(pageId);
  return (
    <>
      <SiteHeader current={pageId} />
      <main id="main" tabIndex={-1} data-req={p.req} data-page={pageId} data-site={site.organization ? "ucpo" : ""}>
        {p.sections.map((s, i) => <Section key={s.section_id} s={s} first={i === 0} />)}
      </main>
      <SiteFooter />
    </>
  );
}
'''


def _page_file(page_id: str, depth: int) -> str:
    up = "../" * depth
    return (f'import type {{ Metadata }} from "next";\n'
            f'import {{ PageView, pageMetadata }} from "{up}components/PageView";\n\n'
            f'export const metadata: Metadata = pageMetadata({json.dumps(page_id)});\n\n'
            f'export default function Page() {{\n  return <PageView pageId={{{json.dumps(page_id)}}} />;\n}}\n')


TSCONFIG = {
    "compilerOptions": {
        "target": "ES2022", "lib": ["dom", "es2022"], "jsx": "react-jsx", "module": "esnext",
        "moduleResolution": "bundler", "strict": True, "noEmit": True, "esModuleInterop": True, "skipLibCheck": True,
        "isolatedModules": True, "resolveJsonModule": True, "plugins": [{"name": "next"}], "allowJs": True,
        "incremental": True,
    },
    "include": ["**/*.ts", "**/*.tsx", ".next/types/**/*.ts", ".next/dev/types/**/*.ts"],
    "exclude": ["node_modules"],
}


def generate_source(ir: WebsiteIR, genome: CreativeGenome, token_css: str) -> tuple[dict[str, bytes], SourceTreeManifest]:
    """The full source tree and its manifest. Deterministic: same IR, genome and tokens -> same bytes."""
    files: dict[str, tuple[bytes, str, tuple[str, ...]]] = {}

    def put(path: str, data: bytes | str, role: str, req_refs: Iterable[str] = ()) -> None:
        raw = data.encode() if isinstance(data, str) else data
        files[path] = (raw, role, tuple(sorted(set(r for r in req_refs if r))))

    content = site_content(ir)
    all_refs = sorted({ref for p in ir.pages for s in p.sections for ref in s.req_refs.values()}
                      | {p.req_refs["page"] for p in ir.pages} | {f"req.nav.{p.page_id}" for p in ir.pages} | {"req.brand"})
    put("package.json", _json({"name": "ucpo-site", "private": True, "version": "0.0.0",
                               "scripts": {"build": "next build --webpack", "typecheck": "tsc --noEmit"},
                               "dependencies": DEPENDENCIES, "devDependencies": DEV_DEPENDENCIES}), "config")
    put("next.config.mjs", "/** Static export only: no server, no image optimizer, no runtime network. */\n"
                           "export default { output: \"export\", trailingSlash: true, images: { unoptimized: true },\n"
                           "  poweredByHeader: false, typescript: { ignoreBuildErrors: false } };\n", "config")
    put("tsconfig.json", _json(TSCONFIG), "config")
    put("amc-env.d.ts", 'declare module "*.css";\n', "config")
    put("app/globals.css", token_css + STRUCTURE_CSS, "style", ("req.psem.colour", "req.motion.reduced",
                                                                 "req.keyboard.focus", "req.responsive.reflow"))
    put("app/layout.tsx", LAYOUT, "layout", ("req.lang",))
    put("lib/site.ts", LIB_SITE, "component")
    put("components/SiteHeader.tsx", HEADER, "component", ["req.brand", "req.keyboard.focus"] + [f"req.nav.{p.page_id}" for p in ir.pages])
    put("components/SiteFooter.tsx", FOOTER, "component")
    put("components/Section.tsx", SECTION, "component")
    put("components/PageView.tsx", PAGE_VIEW, "component")
    put("content/site.json", _json(content), "content", all_refs)
    for p in ir.pages:
        path = "app/page.tsx" if p.page_id == "index" else f"app/{p.page_id}/page.tsx"
        refs = [p.req_refs["page"]] + [ref for s in p.sections for ref in s.req_refs.values()]
        put(path, _page_file(p.page_id, 1 if p.page_id == "index" else 2), "route", refs)
    for image in ir.images:
        put(f"public/assets/{image.asset_id}.svg", psem.plate(genome, title=image.alt, motif_seed=image.motif_seed), "asset",
            (f"req.image.{image.asset_id}.alt", f"req.image.{image.asset_id}.rights"))
    put("UCPO.md", "# Generated site\n\nGenerated by the AMC website production line from WebsiteIR "
                   f"`{ir.content_hash[:16]}` ({ir.compiler_version}).\nEdit the brief and regenerate; files edited by hand "
                   "are preserved and reported on regeneration.\n", "doc")

    findings: list[str] = []
    for path, (raw, _, _) in files.items():
        check_path(path)
        findings += scan(path, raw)
    if findings:
        raise SourcePolicyError("; ".join(findings))
    entries = tuple(SourceFile(path=path, sha256=_sha(raw), bytes=len(raw), role=role, req_refs=refs)
                    for path, (raw, role, refs) in sorted(files.items()))
    manifest = SourceTreeManifest(website_ir_ref=ir.content_hash, files=entries,
                                  dependencies={**DEPENDENCIES, **DEV_DEPENDENCIES}, tree_hash=tree_hash(entries))
    return {path: raw for path, (raw, _, _) in files.items()}, manifest


def tree_hash(entries: Iterable[SourceFile]) -> str:
    return canonical_hash(sorted((f.path, f.sha256) for f in entries))


def verify_tree(files: dict[str, bytes], manifest: SourceTreeManifest) -> list[str]:
    """Differences between a tree and its manifest (missing, extra, changed). Empty means they agree."""
    expected = {f.path: f.sha256 for f in manifest.files}
    problems = [f"missing {p}" for p in sorted(set(expected) - set(files))]
    problems += [f"unexpected {p}" for p in sorted(set(files) - set(expected))]
    problems += [f"changed {p}" for p in sorted(set(files) & set(expected)) if _sha(files[p]) != expected[p]]
    if tree_hash(manifest.files) != manifest.tree_hash:
        problems.append("manifest tree_hash does not match its entries")
    return problems


def pack_tree(files: dict[str, bytes], manifest: SourceTreeManifest) -> bytes:
    """One JSON bundle of the tree and its manifest, for storage as a single artifact."""
    return _json({"schema_version": "amc-ucpo-source-bundle/v1", "manifest": manifest.model_dump(mode="json"),
                  "files": {p: files[p].decode("utf-8") for p in sorted(files)}})


def unpack_tree(bundle: bytes) -> tuple[dict[str, bytes], SourceTreeManifest]:
    """The tree back from a bundle, re-checked: paths, forbidden constructs, and agreement with its manifest."""
    data = json.loads(bundle)
    if data.get("schema_version") != "amc-ucpo-source-bundle/v1":
        raise SourcePolicyError("not a source bundle")
    out = {p: t.encode() for p, t in data["files"].items()}
    manifest = SourceTreeManifest.model_validate(data["manifest"])
    problems: list[str] = []
    for p, raw in out.items():
        check_path(p)
        problems += scan(p, raw)
    problems += verify_tree(out, manifest)
    if problems:
        raise SourcePolicyError("; ".join(problems))
    return out, manifest


def reconcile_tree(previous: Optional[SourceTreeManifest], on_disk: dict[str, bytes],
                   generated: dict[str, bytes]) -> dict[str, object]:
    """What a regeneration may write without destroying human edits.

    A file is human-edited when it exists on disk and its bytes differ from the previous
    manifest. Such files are preserved; if the generator also changed them, that is a conflict
    for a person to resolve. Files that are not in the previous manifest are never overwritten.
    """
    prev = {f.path: f.sha256 for f in previous.files} if previous else {}
    write: dict[str, bytes] = {}
    preserved: list[str] = []
    conflicts: list[str] = []
    for path, raw in sorted(generated.items()):
        if path in on_disk:
            disk_sha = _sha(on_disk[path])
            if disk_sha == _sha(raw):
                continue
            if path not in prev or disk_sha != prev[path]:
                preserved.append(path)
                if path not in prev or _sha(raw) != prev[path]:
                    conflicts.append(path)
                continue
        write[path] = raw
    stale = sorted(p for p in prev if p not in generated and p in on_disk and _sha(on_disk[p]) == prev[p])
    return {"write": write, "preserved": preserved, "conflicts": conflicts, "stale_generated": stale}


def export_tree(dest: Path, files: dict[str, bytes], previous: Optional[SourceTreeManifest] = None) -> dict[str, object]:
    """Write a generated tree to ``dest`` (an operator's checkout), preserving human edits."""
    dest = dest.resolve()
    on_disk = {}
    for path in files:
        check_path(path)
        target = (dest / path).resolve()
        if dest not in target.parents:
            raise SourcePolicyError(f"{path!r} escapes the destination")
        if target.is_file():
            on_disk[path] = target.read_bytes()
    plan = reconcile_tree(previous, on_disk, files)
    for path, raw in plan["write"].items():  # type: ignore[union-attr]
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return {k: (sorted(v) if isinstance(v, dict) else v) for k, v in plan.items()}


__all__ = ["DEPENDENCIES", "DEV_DEPENDENCIES", "SourcePolicyError", "check_path", "export_tree", "generate_source",
           "pack_tree", "reconcile_tree", "scan", "site_content", "tree_hash", "unpack_tree", "verify_tree"]
