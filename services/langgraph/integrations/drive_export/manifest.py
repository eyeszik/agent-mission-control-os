"""Content-addressed manifest, delta, graph index and zip packaging.

Pure local file work: no network, no credentials. The manifest lists every
exported file with its SHA-256 and size, sorted by path, and its hash is the
SHA-256 of the canonical JSON, so the same tree always yields the same hash.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_FILE_BYTES = 50 * 1024 * 1024
EXCLUDED_DIRS = frozenset({".git", "node_modules", "__pycache__", ".next", ".venv", ".amc-export"})
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".html", ".csv", ".srt"})
KIND_BY_SUFFIX = {
    ".md": "document", ".txt": "document", ".pdf": "document", ".html": "page",
    ".json": "data", ".yaml": "data", ".yml": "data", ".csv": "data",
    ".svg": "vector", ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".mp4": "video", ".webm": "video", ".srt": "captions", ".wav": "audio", ".mp3": "audio",
}
STOPWORDS = frozenset(
    "the a an and or of to in for on with by is are be as at from that this it its into not no "
    "your you we our their they them can will may must should use used using each every all any".split()
)
ENCRYPTED_MAGIC = b"AMCX1"


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Collected:
    entries: tuple[ManifestEntry, ...]
    skipped: tuple[str, ...]


def collect_manifest(root: Path) -> Collected:
    """Walk ``root`` and hash every regular file; symlinks and oversized files are skipped."""
    root = root.resolve()
    entries: list[ManifestEntry] = []
    skipped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                skipped.append(f"{rel}: not a regular file")
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped.append(f"{rel}: {size} bytes exceeds {MAX_FILE_BYTES}")
                continue
            entries.append(ManifestEntry(rel, _sha256_file(path), size))
    entries.sort(key=lambda e: e.path)
    return Collected(tuple(entries), tuple(skipped))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_document(entries: tuple[ManifestEntry, ...]) -> dict:
    return {"schema": "amc-export-manifest/v1", "files": [asdict(e) for e in entries]}


def manifest_hash(entries: tuple[ManifestEntry, ...]) -> str:
    canonical = json.dumps(manifest_document(entries), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def previous_shas(document: dict | None) -> dict[str, str]:
    if not document:
        return {}
    return {item["path"]: item["sha256"] for item in document.get("files", [])}


def delta(entries: tuple[ManifestEntry, ...], previous: dict[str, str]) -> tuple[ManifestEntry, ...]:
    """Entries that are new or whose content changed since ``previous``."""
    return tuple(e for e in entries if previous.get(e.path) != e.sha256)


def removed_paths(entries: tuple[ManifestEntry, ...], previous: dict[str, str]) -> tuple[str, ...]:
    current = {e.path for e in entries}
    return tuple(sorted(p for p in previous if p not in current))


def build_graph_index(root: Path, entries: tuple[ManifestEntry, ...], *, prompt_snippet_chars: int = 400) -> dict:
    """A compact, deterministic index of what the export contains.

    Counts by kind and top-level folder, the prompt files with a short opening
    excerpt, the first heading of each Markdown file and the most frequent
    content words. No model call: identical files give an identical index.
    """
    kinds = Counter(KIND_BY_SUFFIX.get(Path(e.path).suffix.lower(), "other") for e in entries)
    folders = Counter(e.path.split("/", 1)[0] if "/" in e.path else "." for e in entries)
    prompts, headings, words = [], [], Counter()
    for entry in entries:
        suffix = Path(entry.path).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            continue
        text = (root / entry.path).read_text(encoding="utf-8", errors="replace")
        if "prompt" in entry.path.lower():
            prompts.append({"path": entry.path, "excerpt": " ".join(text.split())[:prompt_snippet_chars]})
        if suffix == ".md":
            heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), None)
            if heading:
                headings.append({"path": entry.path, "heading": heading[:200]})
        if suffix in {".md", ".txt"}:
            words.update(w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in STOPWORDS)
    return {
        "schema": "amc-export-graph/v1",
        "artifacts_count": len(entries),
        "total_bytes": sum(e.size for e in entries),
        "kinds": dict(sorted(kinds.items())),
        "folders": dict(sorted(folders.items())),
        "prompts": prompts,
        "headings": headings,
        "keywords": [w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))[:20]],
    }


def short_summary(graph: dict) -> str:
    kinds = ", ".join(f"{count} {kind}" for kind, count in graph["kinds"].items()) or "no files"
    return f"{graph['artifacts_count']} files ({kinds}); {len(graph['prompts'])} prompt files."


def write_zip(root: Path, files: tuple[ManifestEntry, ...], extras: dict[str, dict], out_path: Path) -> Path:
    """Write ``files`` plus JSON ``extras`` (manifest, graph, audit) into a zip.

    Members are added in sorted order with a fixed timestamp, so the archive
    depends only on its contents.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(extras):
            _add(archive, name, json.dumps(extras[name], indent=2, sort_keys=True).encode("utf-8"))
        for entry in sorted(files, key=lambda e: e.path):
            _add(archive, f"files/{entry.path}", (root / entry.path).read_bytes())
    return out_path


def _add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_encryption_key(value: str) -> bytes:
    """Decode a base64 AES-256 key; reject anything that is not exactly 32 bytes."""
    try:
        key = base64.b64decode(value.strip(), validate=True)
    except ValueError:
        raise ValueError("EXPORT_ENCRYPTION_KEY must be base64") from None
    if len(key) != 32:
        raise ValueError("EXPORT_ENCRYPTION_KEY must decode to 32 bytes (AES-256)")
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return ENCRYPTED_MAGIC + nonce + AESGCM(key).encrypt(nonce, data, ENCRYPTED_MAGIC)


def decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(ENCRYPTED_MAGIC):
        raise ValueError("not an AMC encrypted export")
    nonce = blob[len(ENCRYPTED_MAGIC):len(ENCRYPTED_MAGIC) + 12]
    return AESGCM(key).decrypt(nonce, blob[len(ENCRYPTED_MAGIC) + 12:], ENCRYPTED_MAGIC)
