#!/usr/bin/env python3
"""Verify a fictional Northline preview bundle, not its creative quality or release authority.

Checksums and report bindings run with the standard library. ffprobe is optional:
without it, structural checks can pass but stream verification is NOT_RUN and
this command exits 2. Exit 0 means all listed mechanical checks ran and passed;
exit 1 means a check failed. No result constitutes rights or human approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path, PurePosixPath


class BundleError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_relative(name: str) -> Path:
    require(bool(name) and "\\" not in name and "\n" not in name and "\r" not in name,
            "invalid manifest path")
    value = PurePosixPath(name)
    require(bool(value.parts) and not value.is_absolute() and all(part not in ("", ".", "..") for part in value.parts)
            and value.as_posix() == name, f"unsafe manifest path: {name}")
    return Path(*value.parts)


def verify_checksums(root: Path) -> int:
    manifest = root / "SHA256SUMS"
    require(manifest.is_file() and not manifest.is_symlink(), "missing or unsafe SHA256SUMS")
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, "malformed checksum line")
        assert match is not None
        name = match.group(2)
        safe_relative(name)
        require(name != "SHA256SUMS" and name not in entries, f"duplicate or self-referential checksum: {name}")
        entries[name] = match.group(1)
    require(bool(entries), "empty checksum manifest")
    found: set[str] = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            require(not path.is_symlink(), f"symlink not permitted: {path.relative_to(root)}")
        for name in files:
            path = Path(directory) / name
            require(path.is_file(), f"non-regular bundle file: {path.relative_to(root)}")
            relative = path.relative_to(root).as_posix()
            if relative != "SHA256SUMS":
                found.add(relative)
    require(found == set(entries), f"checksum coverage differs: missing={sorted(set(entries) - found)}, extra={sorted(found - set(entries))}")
    for name, expected in entries.items():
        require(digest(root / safe_relative(name)) == expected, f"checksum mismatch: {name}")
    return len(entries)


def _canonical_sequence(value: object) -> bytes:
    """AMC-CANON-1 for the string/sequence subset used by UCPO output_digest."""
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return b"S" + str(len(raw)).encode("ascii") + b":" + raw
    if isinstance(value, (tuple, list)):
        return b"L" + str(len(value)).encode("ascii") + b":" + b"".join(_canonical_sequence(x) for x in value)
    raise BundleError("unsupported website digest value")


def website_digest(root: Path) -> str:
    require(root.is_dir(), f"missing website export: {root}")
    entries = sorted((p.relative_to(root).as_posix(), digest(p)) for p in root.rglob("*") if p.is_file())
    return hashlib.sha256(b"AMC-CANON-1\0" + _canonical_sequence(entries)).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    require(len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR",
            f"invalid PNG header: {path.name}")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


_CUE = re.compile(r"^(\d{2,}):(\d{2}):(\d{2})\.(\d{3}) --> (\d{2,}):(\d{2}):(\d{2})\.(\d{3})$")


def verify_vtt(path: Path, *, duration_ms: int, expected_cues: int) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(bool(lines) and lines[0] == "WEBVTT", f"invalid WebVTT header: {path.name}")
    count, previous_start = 0, -1
    for i, line in enumerate(lines):
        if "-->" not in line:
            continue
        match = _CUE.fullmatch(line)
        require(match is not None, f"malformed cue timing: {path.name}")
        assert match is not None
        numbers = [int(x) for x in match.groups()]
        sh, sm, ss, sms, eh, em, es, ems = numbers
        require(sm < 60 and ss < 60 and em < 60 and es < 60, f"invalid cue timestamp: {path.name}")
        start = ((sh * 60 + sm) * 60 + ss) * 1000 + sms
        end = ((eh * 60 + em) * 60 + es) * 1000 + ems
        require(previous_start <= start < end <= duration_ms, f"out-of-range cue: {path.name}")
        require(i + 1 < len(lines) and bool(lines[i + 1].strip()), f"empty cue: {path.name}")
        previous_start, count = start, count + 1
    require(count == expected_cues, f"unexpected cue count: {path.name}, {count}")
    return count


def verify_report_bindings(root: Path) -> None:
    website = json.loads((root / "reports/website-report.json").read_text(encoding="utf-8"))
    for version in ("v1", "v2"):
        export = root / "website" / version / "static-export"
        require(website_digest(export) == website[version]["build_output_hash"], f"{version} export differs from build report")
        for route in ("index.html", "services/index.html", "process/index.html", "about/index.html", "contact/index.html",
                      "workflow-diagnostic/index.html", "implementation-planning/index.html"):
            require((export / route).is_file(), f"missing {version} route {route}")
        require((root / "website" / version / "editable-source/package.json").is_file(), f"missing {version} source")

    media = json.loads((root / "reports/media-report.json").read_text(encoding="utf-8"))
    require(len(media["social"]) == 6, "expected six social previews")
    names: set[str] = set()
    for item in media["social"]:
        name = item["name"]
        require(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name) is not None and name not in names,
                "invalid or duplicate social preview name")
        names.add(name)
        for suffix in ("svg", "png"):
            require(item[suffix] == f"social/{name}.{suffix}", "unexpected social report path")
            path = root / item[suffix]
            require(digest(path) == item[f"{suffix}_sha256"], f"social report hash mismatch: {name}.{suffix}")
        require(png_dimensions(root / item["png"]) == (1080, 1080), f"wrong social dimensions: {name}")

    motion = json.loads((root / "reports/timeline-report.json").read_text(encoding="utf-8"))
    require(digest(root / "motion/editable-timeline.json") == motion["plan_sha256"], "timeline plan hash mismatch")
    expected = {"master-30s": (900, 30), "cutdown-a-15s": (450, 15), "cutdown-b-15s": (450, 15)}
    outputs = motion["outputs"]
    require(len(outputs) == len(expected), "unexpected timeline output count")
    for item in outputs:
        name = item["name"]
        require(name in expected and item["file"] == f"{name}.mp4" and item["captions"] == f"{name}.vtt",
                "unexpected timeline output path")
        frames, seconds = expected.pop(name)
        require(item["frames"] == frames and item["fps"] == 30 and item["duration_seconds"] == str(seconds),
                f"unexpected timeline report values: {name}")
        require(digest(root / "motion" / item["file"]) == item["sha256"], f"video report hash mismatch: {name}")
        require(digest(root / "motion" / item["captions"]) == item["captions_sha256"], f"VTT report hash mismatch: {name}")
    require(not expected, "missing timeline output")
    for suffix in ("svg", "png"):
        item = motion["reduced_motion"]["outputs"][suffix]
        require(item["file"] == f"master-reduced-motion.{suffix}", "unexpected reduced-motion path")
        require(digest(root / "motion" / item["file"]) == item["sha256"], f"still hash mismatch: {suffix}")
    require(png_dimensions(root / "motion/master-reduced-motion.png") == (640, 360), "wrong reduced-motion dimensions")
    verify_vtt(root / "motion/master-30s.vtt", duration_ms=30000, expected_cues=6)
    verify_vtt(root / "motion/cutdown-a-15s.vtt", duration_ms=15000, expected_cues=3)
    verify_vtt(root / "motion/cutdown-b-15s.vtt", duration_ms=15000, expected_cues=3)
    verify_vtt(root / "motion/short-preview/captions.vtt", duration_ms=13600, expected_cues=4)


def verify_streams(root: Path, ffprobe: str) -> None:
    expected = (("master-30s.mp4", 640, 360, 30, 900, 30.0), ("cutdown-a-15s.mp4", 640, 360, 30, 450, 15.0),
                ("cutdown-b-15s.mp4", 640, 360, 30, 450, 15.0), ("short-preview/master_silent.mp4", 480, 270, 10, 136, 13.6))
    for name, width, height, fps, frames, seconds in expected:
        path = root / "motion" / name
        try:
            result = subprocess.run([ffprobe, "-v", "error", "-count_frames", "-show_entries",
                                     "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_read_frames:format=duration",
                                     "-of", "json", str(path)], capture_output=True, text=True, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BundleError(f"ffprobe did not run for {name}: {type(exc).__name__}") from exc
        require(result.returncode == 0, f"ffprobe failed for {name}")
        payload = json.loads(result.stdout)
        streams = payload.get("streams", [])
        require(len(streams) == 1 and streams[0].get("codec_type") == "video", f"unexpected streams in {name}")
        s = streams[0]
        require(s.get("codec_name") == "h264" and (s.get("width"), s.get("height")) == (width, height)
                and Fraction(s.get("avg_frame_rate", "0")) == fps and int(s.get("nb_read_frames", 0)) == frames
                and abs(float(payload.get("format", {}).get("duration", 0)) - seconds) < 0.01,
                f"unexpected video metadata in {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, nargs="?", default=Path(__file__).resolve().parent)
    parser.add_argument("--ffprobe", help="Path to ffprobe; otherwise discover it on PATH")
    args = parser.parse_args()
    root = args.bundle.expanduser().resolve()
    try:
        require(root.is_dir(), "bundle directory does not exist")
        files = verify_checksums(root)
        verify_report_bindings(root)
        print(f"PASS: {files} files matched checksums; website, social, timeline and caption bindings checked")
        probe = args.ffprobe or shutil.which("ffprobe")
        if not probe:
            print("NOT_RUN: ffprobe is unavailable; stream verification did not run", file=sys.stderr)
            return 2
        verify_streams(root, probe)
        print("PASS: ffprobe verified the four silent H.264 streams, dimensions, rates, frame counts and durations")
        print("NOT_EVALUATED: rights, font clearance, unsampled visual quality, accessibility, creative review and release approval")
        return 0
    except (BundleError, OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
