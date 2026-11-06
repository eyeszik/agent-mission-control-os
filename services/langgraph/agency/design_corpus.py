"""Provenance-aware design corpus: install-time indexing and run-time retrieval.

The corpus lives in ``knowledge/design-corpus/`` at the repository root:

* ``standards/*.md``  - the owned Creative Production Standard contracts
  (internal guidance; excerpts may be passed to generation).
* ``references/*.md`` - third-party design-system write-ups, **reference only**.
  Retrieval never forwards their text: a reference contributes only its
  category and generic section names, so no third-party brand identity,
  trademark, wording, palette or typeface can reach a generated deliverable.
* ``manifest.json`` / ``catalog.json`` - generated deterministically from the
  installed bytes by :func:`build_index`.

Every retrieval re-validates the whole corpus (manifest/catalog agreement, safe
relative paths, per-file SHA-256, metadata shape and rights classification).
Any failure returns an explicit ``DEGRADED`` result with no guidance at all:
nothing is ever fabricated to fill the gap.

Deliberately dependency-free (stdlib only) and side-effect free at run time.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCHEMA_VERSION = "amc-design-corpus/v1"
DEFAULT_CORPUS_ROOT = Path(__file__).resolve().parents[3] / "knowledge" / "design-corpus"

MAX_RESULTS = 5
MAX_STANDARDS = 3
MAX_EXCERPT_CHARS = 700
# Ranking reads only a bounded prefix of each document body.
RANKING_WINDOW_CHARS = 2000

STANDARDS_DIR = "standards"
REFERENCES_DIR = "references"

SOURCE_CLASS_STANDARD = "creative_production_standard"
SOURCE_CLASS_REFERENCE = "reference_only"
RIGHTS_OWNED = "owned_standard"
RIGHTS_REFERENCE = "reference_only"
RIGHTS_UNKNOWN = "unknown"
INCLUDED = "included"
EXCLUDED_PENDING_REVIEW = "excluded_pending_rights_review"

STATUS_OK = "OK"
STATUS_NO_MATCH = "NO_MATCH"
STATUS_DEGRADED = "DEGRADED"

_REFERENCE_TITLE = re.compile(r"^# Design System Inspired by .+$")
_CATEGORY_LINE = re.compile(r"^> Category:\s*(.+?)\s*$", re.M)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$", re.M)
_TOKEN = re.compile(r"[a-z0-9]+")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")

# Generic, brand-neutral section vocabulary a reference may contribute.
_PRINCIPLE_VOCABULARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("visual theme and atmosphere", ("theme", "atmosphere")),
    ("color roles", ("color", "colour", "palette")),
    ("typography", ("typography", "type", "font")),
    ("components", ("component", "components")),
    ("layout", ("layout", "grid", "spacing")),
    ("responsive behavior", ("responsive",)),
    ("depth and elevation", ("depth", "elevation", "shadow")),
    ("motion and interaction", ("motion", "interaction", "animation")),
    ("voice and tone", ("voice", "tone")),
    ("accessibility", ("accessibility", "accessible", "contrast")),
    ("dos and donts", ("dos", "donts", "don")),
    ("anti-patterns", ("anti",)),
    ("imagery", ("imagery", "photography", "illustration", "iconography")),
)

_STOPWORDS = frozenset(
    "the and for with from that this your our are was were will into over under about more most very "
    "than then them they their what when where which while who why how all any can not but its it's".split()
)

_REQUIRED_ENTRY_FIELDS = (
    "corpus_id",
    "path",
    "title",
    "headings",
    "tags",
    "source_path",
    "content_sha256",
    "source_class",
    "rights_status",
    "inclusion_status",
)


class CorpusIntegrityError(ValueError):
    """The installed corpus does not match its manifest/catalog contract."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corpus_id_for(content_sha256: str) -> str:
    return f"dc-{content_sha256[:16]}"


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if len(token) >= 3 and token not in _STOPWORDS}


def _clean_heading(raw: str) -> str:
    text = re.sub(r"^\d+(\.\d+)*[.)]?\s*", "", raw.strip())
    return re.sub(r"[*_`]", "", text).strip()


def _slug(text: str) -> str:
    return "-".join(_TOKEN.findall(text.lower()))


def safe_relative_path(value: Any) -> PurePosixPath:
    """Validate a catalog path: relative, no traversal, no hidden parts, Markdown."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CorpusIntegrityError("unsafe path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts):
        raise CorpusIntegrityError(f"unsafe path: {value!r}")
    if path.suffix != ".md" or len(path.parts) != 2 or path.parts[0] not in {STANDARDS_DIR, REFERENCES_DIR}:
        raise CorpusIntegrityError(f"path outside corpus layout: {value!r}")
    return path


def _resolve_inside(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise CorpusIntegrityError(f"symlinked document: {relative}")
    resolved = candidate.resolve()
    if root.resolve() not in resolved.parents:
        raise CorpusIntegrityError(f"document escapes corpus root: {relative}")
    return resolved


def _body_after_title(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) pairs for level-2/3 sections; preamble uses an empty heading."""
    body = _body_after_title(text)
    parts: list[tuple[str, str]] = []
    current_heading = ""
    current: list[str] = []
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            if current or current_heading:
                parts.append((current_heading, "\n".join(current).strip()))
            current_heading = _clean_heading(match.group(2))
            current = []
        else:
            current.append(line)
    if current or current_heading:
        parts.append((current_heading, "\n".join(current).strip()))
    return parts


# ---------------------------------------------------------------------------
# Install-time indexing (deterministic)
# ---------------------------------------------------------------------------


def classify(relative_path: str, text: str) -> tuple[str, str, str]:
    """Return (source_class, rights_status, inclusion_status) for one document.

    Standards are owned. A reference is ``reference_only`` only when it has the
    expected attributed shape (an "Inspired by" title and a category line);
    anything else has uncertain provenance and is excluded until reviewed.
    """
    folder = PurePosixPath(relative_path).parts[0]
    if folder == STANDARDS_DIR:
        return SOURCE_CLASS_STANDARD, RIGHTS_OWNED, INCLUDED
    first_line = text.splitlines()[0] if text else ""
    if _REFERENCE_TITLE.match(first_line) and _CATEGORY_LINE.search(text):
        return SOURCE_CLASS_REFERENCE, RIGHTS_REFERENCE, INCLUDED
    return SOURCE_CLASS_REFERENCE, RIGHTS_UNKNOWN, EXCLUDED_PENDING_REVIEW


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _headings(text: str) -> list[str]:
    seen: list[str] = []
    for match in _HEADING.finditer(_body_after_title(text)):
        heading = _clean_heading(match.group(2))
        if heading and heading not in seen:
            seen.append(heading)
    return seen[:40]


def _tags(relative_path: str, text: str, title: str) -> list[str]:
    folder = PurePosixPath(relative_path).parts[0]
    tags = {"standard"} if folder == STANDARDS_DIR else {"reference"}
    category = _CATEGORY_LINE.search(text)
    if category:
        tags.add(f"category:{_slug(category.group(1))}")
    if folder == STANDARDS_DIR:
        tags.add(f"contract:{_slug(title)}")
    for principle in reference_principles(_headings(text)):
        tags.add(f"topic:{_slug(principle)}")
    return sorted(tags)


def reference_principles(headings: Iterable[str]) -> list[str]:
    """Map arbitrary headings onto the generic principle vocabulary."""
    tokens: set[str] = set()
    for heading in headings:
        tokens |= set(_TOKEN.findall(heading.lower()))
    return [name for name, keys in _PRINCIPLE_VOCABULARY if tokens & set(keys)]


def catalog_entry(relative_path: str, data: bytes, source_prefix: str) -> dict:
    text = data.decode("utf-8")
    content_sha256 = sha256_bytes(data)
    title = _title(text, PurePosixPath(relative_path).stem)
    source_class, rights_status, inclusion_status = classify(relative_path, text)
    return {
        "corpus_id": corpus_id_for(content_sha256),
        "path": relative_path,
        "title": title,
        "headings": _headings(text),
        "tags": _tags(relative_path, text, title),
        "source_path": f"{source_prefix}{relative_path}" if source_prefix else relative_path,
        "content_sha256": content_sha256,
        "source_class": source_class,
        "rights_status": rights_status,
        "inclusion_status": inclusion_status,
    }


def build_index(root: Path, *, archive_name: str, archive_sha256: str, source_prefix: str) -> tuple[bytes, bytes]:
    """Build (manifest.json, catalog.json) bytes from the installed files.

    Output depends only on file bytes and the arguments, so re-running it on
    the same install is byte-identical.
    """
    documents: list[tuple[str, bytes]] = []
    for folder in (STANDARDS_DIR, REFERENCES_DIR):
        for path in sorted((root / folder).glob("*.md")):
            documents.append((f"{folder}/{path.name}", path.read_bytes()))
    entries = [catalog_entry(rel, data, source_prefix) for rel, data in documents]
    _check_unique(entries)
    catalog = {"schema": SCHEMA_VERSION, "entries": entries}
    catalog_bytes = canonical_json(catalog)

    readme = root / "README.md"
    files = [{"path": "README.md", "content_sha256": sha256_bytes(readme.read_bytes())}] if readme.exists() else []
    files += [{"path": entry["path"], "content_sha256": entry["content_sha256"]} for entry in entries]
    counts = {
        "documents": len(entries),
        "standards": sum(1 for e in entries if e["source_class"] == SOURCE_CLASS_STANDARD),
        "references": sum(1 for e in entries if e["source_class"] == SOURCE_CLASS_REFERENCE),
        "owned_standard": sum(1 for e in entries if e["rights_status"] == RIGHTS_OWNED),
        "reference_only": sum(1 for e in entries if e["rights_status"] == RIGHTS_REFERENCE),
        "unknown": sum(1 for e in entries if e["rights_status"] == RIGHTS_UNKNOWN),
        "included": sum(1 for e in entries if e["inclusion_status"] == INCLUDED),
    }
    corpus_version = "dcv-" + sha256_bytes(canonical_json(files))[:16]
    manifest = {
        "schema": SCHEMA_VERSION,
        "corpus_version": corpus_version,
        "source_archive": {"name": archive_name, "sha256": archive_sha256},
        "catalog_sha256": sha256_bytes(catalog_bytes),
        "counts": counts,
        "files": files,
    }
    return canonical_json(manifest), catalog_bytes


def _check_unique(entries: list[dict]) -> None:
    for field in ("corpus_id", "path", "content_sha256"):
        values = [entry.get(field) for entry in entries]
        if len(values) != len(set(values)):
            raise CorpusIntegrityError(f"duplicate {field}")


# ---------------------------------------------------------------------------
# Run-time validation
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> tuple[Any, bytes]:
    if not path.is_file() or path.is_symlink():
        raise CorpusIntegrityError(f"missing {path.name}")
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusIntegrityError(f"malformed {path.name}") from exc


def _validate_entry(entry: Any) -> None:
    if not isinstance(entry, dict) or any(field not in entry for field in _REQUIRED_ENTRY_FIELDS):
        raise CorpusIntegrityError("catalog entry missing required fields")
    for field in ("corpus_id", "path", "title", "source_path", "content_sha256", "source_class", "rights_status", "inclusion_status"):
        if not isinstance(entry[field], str) or not entry[field]:
            raise CorpusIntegrityError(f"catalog field {field} malformed")
    for field in ("headings", "tags"):
        if not isinstance(entry[field], list) or not all(isinstance(item, str) for item in entry[field]):
            raise CorpusIntegrityError(f"catalog field {field} malformed")
    if not re.fullmatch(r"[0-9a-f]{64}", entry["content_sha256"]):
        raise CorpusIntegrityError("catalog content_sha256 malformed")
    if entry["corpus_id"] != corpus_id_for(entry["content_sha256"]):
        raise CorpusIntegrityError("corpus_id is not derived from content_sha256")
    folder = safe_relative_path(entry["path"]).parts[0]
    expected_class = SOURCE_CLASS_STANDARD if folder == STANDARDS_DIR else SOURCE_CLASS_REFERENCE
    if entry["source_class"] != expected_class:
        raise CorpusIntegrityError("source_class does not match corpus folder")
    allowed_rights = {RIGHTS_OWNED} if folder == STANDARDS_DIR else {RIGHTS_REFERENCE, RIGHTS_UNKNOWN}
    if entry["rights_status"] not in allowed_rights:
        raise CorpusIntegrityError("rights_status does not match corpus folder")
    if entry["inclusion_status"] not in {INCLUDED, EXCLUDED_PENDING_REVIEW}:
        raise CorpusIntegrityError("inclusion_status malformed")
    if entry["rights_status"] == RIGHTS_UNKNOWN and entry["inclusion_status"] == INCLUDED:
        raise CorpusIntegrityError("unknown-rights document marked for retrieval")


def load_validated_corpus(root: Path | None = None) -> tuple[dict, list[tuple[dict, str]]]:
    """Validate the full corpus and return (manifest, [(entry, text), ...]).

    Raises :class:`CorpusIntegrityError` on any mismatch.
    """
    root = Path(root) if root is not None else DEFAULT_CORPUS_ROOT
    if not root.is_dir():
        raise CorpusIntegrityError("corpus root missing")
    manifest, _ = _load_json(root / "manifest.json")
    catalog, catalog_raw = _load_json(root / "catalog.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA_VERSION:
        raise CorpusIntegrityError("manifest schema mismatch")
    if not isinstance(catalog, dict) or catalog.get("schema") != SCHEMA_VERSION or not isinstance(catalog.get("entries"), list):
        raise CorpusIntegrityError("catalog schema mismatch")
    if manifest.get("catalog_sha256") != sha256_bytes(catalog_raw):
        raise CorpusIntegrityError("catalog does not match manifest catalog_sha256")
    archive = manifest.get("source_archive") or {}
    if not isinstance(archive, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(archive.get("sha256") or "")):
        raise CorpusIntegrityError("manifest source_archive malformed")
    if not isinstance(manifest.get("corpus_version"), str) or not manifest["corpus_version"]:
        raise CorpusIntegrityError("manifest corpus_version malformed")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise CorpusIntegrityError("manifest files malformed")
    manifest_hashes: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content_sha256"), str):
            raise CorpusIntegrityError("manifest file entry malformed")
        if item["path"] in manifest_hashes:
            raise CorpusIntegrityError("duplicate manifest path")
        manifest_hashes[item["path"]] = item["content_sha256"]

    entries = catalog["entries"]
    for entry in entries:
        _validate_entry(entry)
    _check_unique(entries)
    catalog_paths = {entry["path"] for entry in entries}
    if catalog_paths != set(manifest_hashes) - {"README.md"}:
        raise CorpusIntegrityError("manifest and catalog list different documents")
    expected_version = "dcv-" + sha256_bytes(canonical_json(files))[:16]
    if manifest["corpus_version"] != expected_version:
        raise CorpusIntegrityError("corpus_version does not match manifest files")

    loaded: list[tuple[dict, str]] = []
    for entry in entries:
        relative = safe_relative_path(entry["path"])
        if manifest_hashes[entry["path"]] != entry["content_sha256"]:
            raise CorpusIntegrityError("manifest and catalog hashes disagree")
        document = _resolve_inside(root, relative)
        if not document.is_file():
            raise CorpusIntegrityError(f"missing document {entry['path']}")
        data = document.read_bytes()
        if sha256_bytes(data) != entry["content_sha256"]:
            raise CorpusIntegrityError(f"content hash mismatch for {entry['path']}")
        if _HEX16.match(relative.stem) and relative.stem != entry["content_sha256"][:16]:
            raise CorpusIntegrityError(f"hash-named file does not match its content: {entry['path']}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusIntegrityError(f"document is not UTF-8: {entry['path']}") from exc
        loaded.append((entry, text))
    return manifest, loaded


# ---------------------------------------------------------------------------
# Run-time retrieval
# ---------------------------------------------------------------------------


def query_tokens(fields: Iterable[Any]) -> set[str]:
    """Tokenize already-sanitized brief/strategy values. Only [a-z0-9] tokens survive."""
    tokens: set[str] = set()
    for value in fields:
        if isinstance(value, (list, tuple)):
            tokens |= query_tokens(value)
        elif value is not None:
            tokens |= _tokens(str(value))
    return tokens


def _score(entry: dict, text: str, tokens: set[str]) -> int:
    if not tokens:
        return 0
    title_hits = len(tokens & _tokens(entry["title"]))
    heading_hits = len(tokens & _tokens(" ".join(entry["headings"])))
    tag_hits = len(tokens & _tokens(" ".join(entry["tags"])))
    excerpt_hits = len(tokens & _tokens(_body_after_title(text)[:RANKING_WINDOW_CHARS]))
    return 3 * title_hits + 2 * heading_hits + 2 * tag_hits + excerpt_hits


def _standard_excerpt(text: str, tokens: set[str]) -> str:
    """Best-matching section of an owned standard, bounded to MAX_EXCERPT_CHARS."""
    sections = [(heading, body) for heading, body in _sections(text) if body or heading]
    if not sections:
        return ""
    best = max(
        enumerate(sections),
        key=lambda item: (len(tokens & _tokens(item[1][0] + " " + item[1][1])), -item[0]),
    )[1]
    excerpt = (f"{best[0]}: " if best[0] else "") + re.sub(r"\s+", " ", best[1]).strip()
    return excerpt[:MAX_EXCERPT_CHARS].rstrip()


def _degraded(reason: str, manifest: dict | None = None) -> dict:
    archive = (manifest or {}).get("source_archive") or {}
    return {
        "status": STATUS_DEGRADED,
        "reason": reason,
        "corpus_version": (manifest or {}).get("corpus_version"),
        "archive_sha256": archive.get("sha256") if isinstance(archive, dict) else None,
        "results": [],
    }


def retrieve(fields: Iterable[Any], *, root: Path | None = None, limit: int = MAX_RESULTS) -> dict:
    """Rank corpus guidance for the given sanitized fields.

    Returns ``{status, reason, corpus_version, archive_sha256, results}``. The
    query itself is never part of the result.
    """
    try:
        manifest, loaded = load_validated_corpus(root)
    except CorpusIntegrityError as exc:
        return _degraded(f"corpus_invalid: {exc}")
    except OSError as exc:
        return _degraded(f"corpus_unreadable: {type(exc).__name__}")

    tokens = query_tokens(fields)
    ranked: list[tuple[int, int, str, dict, str]] = []
    for entry, text in loaded:
        if entry["inclusion_status"] != INCLUDED:
            continue
        score = _score(entry, text, tokens)
        if score <= 0:
            continue
        class_rank = 0 if entry["source_class"] == SOURCE_CLASS_STANDARD else 1
        ranked.append((-score, class_rank, entry["corpus_id"], entry, text))
    ranked.sort(key=lambda item: item[:3])

    # Owned standards carry the actual guidance; long reference write-ups would
    # otherwise win on raw token overlap. Keep up to MAX_STANDARDS matching
    # standards, then fill with references whose (category, principles) adds
    # something new. Selection is then re-ordered by the original ranking.
    cap = max(0, min(limit, MAX_RESULTS))
    standards = [item for item in ranked if item[3]["source_class"] == SOURCE_CLASS_STANDARD][:MAX_STANDARDS]
    selected = list(standards[:cap])
    seen_signatures: set[tuple] = set()
    for item in ranked:
        if len(selected) >= cap:
            break
        entry = item[3]
        if entry["source_class"] == SOURCE_CLASS_STANDARD:
            continue
        signature = (tuple(sorted(tag for tag in entry["tags"] if tag.startswith("category:"))), tuple(reference_principles(entry["headings"])))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        selected.append(item)
    selected.sort(key=lambda item: item[:3])

    results: list[dict] = []
    for negative_score, _class_rank, _cid, entry, text in selected:
        item = {
            "corpus_id": entry["corpus_id"],
            "content_sha256": entry["content_sha256"],
            "source_class": entry["source_class"],
            "rights_status": entry["rights_status"],
            "score": -negative_score,
        }
        if entry["source_class"] == SOURCE_CLASS_STANDARD:
            item["title"] = entry["title"]
            item["excerpt"] = _standard_excerpt(text, tokens)
        else:
            # Reference-only: abstract, brand-neutral principles; no source text.
            item["category"] = next(
                (tag.split(":", 1)[1] for tag in entry["tags"] if tag.startswith("category:")), "uncategorized"
            )
            item["principles"] = reference_principles(entry["headings"])
            item["excerpt"] = ""
        results.append(item)

    archive = manifest.get("source_archive") or {}
    return {
        "status": STATUS_OK if results else STATUS_NO_MATCH,
        "reason": None,
        "corpus_version": manifest["corpus_version"],
        "archive_sha256": archive.get("sha256"),
        "results": results,
    }


def provenance(context: dict) -> dict:
    """The subset of a retrieval result that is safe to persist in events."""
    return {
        "corpus_version": context.get("corpus_version"),
        "archive_sha256": context.get("archive_sha256"),
        "status": context.get("status"),
        "degraded": context.get("status") == STATUS_DEGRADED,
        "reason": context.get("reason"),
        "selected": [
            {"corpus_id": item["corpus_id"], "content_sha256": item["content_sha256"], "score": item["score"]}
            for item in context.get("results", [])
        ],
    }


def prompt_block(context: dict) -> str:
    """Compact, rights-bounded guidance block for generation prompts ('' when none)."""
    results = context.get("results") or []
    if context.get("status") != STATUS_OK or not results:
        return ""
    standards = [
        {"title": item["title"], "guidance": item["excerpt"]}
        for item in results
        if item["source_class"] == SOURCE_CLASS_STANDARD
    ]
    references = [
        {"category": item["category"], "principles": item["principles"]}
        for item in results
        if item["source_class"] == SOURCE_CLASS_REFERENCE
    ]
    payload: dict[str, Any] = {}
    if standards:
        payload["internal_standards"] = standards
    if references:
        payload["reference_principles"] = references
    return (
        "\nDesign corpus guidance. Internal standards are binding house guidance. Reference principles are "
        "abstract and transferable only: do not reproduce any third-party brand name, logo, trademark, "
        "wording, palette, typeface or trade dress.\n"
        f"{json.dumps(payload, sort_keys=True)}"
    )


__all__ = [
    "CorpusIntegrityError",
    "DEFAULT_CORPUS_ROOT",
    "MAX_EXCERPT_CHARS",
    "MAX_RESULTS",
    "build_index",
    "catalog_entry",
    "classify",
    "corpus_id_for",
    "load_validated_corpus",
    "prompt_block",
    "provenance",
    "query_tokens",
    "reference_principles",
    "retrieve",
    "safe_relative_path",
]
