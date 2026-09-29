#!/usr/bin/env python3
"""Install a design-corpus archive into knowledge/design-corpus/.

Usage: python scripts/install_design_corpus.py <archive.zip> [--check] [--archive-name NAME]

Validates the archive (integrity, member paths, Markdown-only, UTF-8, no
symlinks, no duplicate paths or content), extracts it into a temporary
directory outside the repository, copies each document byte-for-byte, and
regenerates manifest.json and catalog.json deterministically.

``--check`` validates and compares against the installed corpus without
writing anything; it exits non-zero on any difference.

Only knowledge/design-corpus/ is ever written. Files already there that the
archive does not contain are never deleted; their presence aborts the install.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.langgraph.agency.design_corpus import (  # noqa: E402
    CorpusIntegrityError,
    build_index,
    load_validated_corpus,
)

TARGET = ROOT / "knowledge" / "design-corpus"
EXPECTED = {"README.md": 1, "standards": 6, "references": 163}


def _fail(message: str) -> None:
    raise SystemExit(f"design corpus install BLOCKED: {message}")


def validate_archive(archive: Path) -> tuple[str, str, dict[str, bytes]]:
    """Return (archive_sha256, member_prefix, {corpus-relative path: bytes})."""
    raw = archive.read_bytes()
    archive_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        bundle = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        _fail(f"not a zip archive ({exc})")
    bad = bundle.testzip()
    if bad is not None:
        _fail(f"CRC failure in {bad}")

    names = [info.filename for info in bundle.infolist()]
    if len(names) != len(set(names)):
        _fail("duplicate member paths")
    files = [info for info in bundle.infolist() if not info.is_dir()]
    prefixes = {PurePosixPath(info.filename).parts[0] for info in files}
    prefix = f"{prefixes.pop()}/" if len(prefixes) == 1 and all(len(PurePosixPath(i.filename).parts) > 1 for i in files) else ""

    documents: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for info in files:
        name = info.filename
        path = PurePosixPath(name)
        if path.is_absolute() or "\\" in name or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts):
            _fail(f"unsafe member path {name!r}")
        if stat.S_ISLNK(info.external_attr >> 16):
            _fail(f"symlink member {name!r}")
        if path.suffix != ".md":
            _fail(f"non-Markdown member {name!r}")
        relative = name[len(prefix):]
        rel_path = PurePosixPath(relative)
        if not (relative == "README.md" or (len(rel_path.parts) == 2 and rel_path.parts[0] in {"standards", "references"})):
            _fail(f"unexpected layout for {name!r}")
        data = bundle.read(info)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            _fail(f"member is not UTF-8: {name!r}")
        digest = hashlib.sha256(data).hexdigest()
        if digest in hashes:
            _fail(f"duplicate content: {name!r} == {hashes[digest]!r}")
        hashes[digest] = name
        documents[relative] = data

    counts = {
        "README.md": int("README.md" in documents),
        "standards": sum(1 for rel in documents if rel.startswith("standards/")),
        "references": sum(1 for rel in documents if rel.startswith("references/")),
    }
    if counts != EXPECTED:
        _fail(f"unexpected file counts {counts}, expected {EXPECTED}")
    return archive_sha256, prefix, documents


def install(archive: Path, *, check: bool, archive_name: str | None = None) -> int:
    archive_sha256, prefix, documents = validate_archive(archive)

    with tempfile.TemporaryDirectory(prefix="amc-design-corpus-") as tmp:
        staging = Path(tmp) / "design-corpus"
        for relative, data in documents.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        manifest, catalog = build_index(staging, archive_name=archive_name or archive.name, archive_sha256=archive_sha256, source_prefix=prefix)
        (staging / "manifest.json").write_bytes(manifest)
        (staging / "catalog.json").write_bytes(catalog)
        load_validated_corpus(staging)

        staged = {p.relative_to(staging).as_posix(): p.read_bytes() for p in staging.rglob("*") if p.is_file()}
        existing = {p.relative_to(TARGET).as_posix(): p.read_bytes() for p in TARGET.rglob("*") if p.is_file()} if TARGET.exists() else {}
        extra = sorted(set(existing) - set(staged))
        changed = sorted(rel for rel in staged if existing.get(rel) != staged[rel])

        if check:
            if extra or changed:
                print(f"design corpus differs: changed={changed[:10]} extra={extra[:10]}")
                return 1
            print(f"design corpus matches archive {archive_sha256} ({len(documents)} files)")
            return 0
        if extra:
            _fail(f"target contains files not in the archive (not deleting): {extra[:10]}")
        for relative in changed:
            destination = TARGET / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / relative, destination)

    try:
        manifest_obj, loaded = load_validated_corpus(TARGET)
    except CorpusIntegrityError as exc:
        _fail(f"installed corpus failed validation: {exc}")
    print(
        f"installed {len(loaded)} documents + README into {TARGET.relative_to(ROOT)} "
        f"(archive sha256 {archive_sha256}, corpus_version {manifest_obj['corpus_version']}, "
        f"counts {manifest_obj['counts']}, files written {len(changed)})"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", type=Path)
    parser.add_argument("--check", action="store_true", help="validate and compare only; write nothing")
    parser.add_argument("--archive-name", help="canonical archive name to record (defaults to the file name)")
    args = parser.parse_args()
    return install(args.archive, check=args.check, archive_name=args.archive_name)


if __name__ == "__main__":
    raise SystemExit(main())
