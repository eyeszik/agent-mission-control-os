"""The preview bundle verifier rejects drift; it does not assert release readiness."""
from __future__ import annotations

import hashlib

import pytest

from scripts.verify_northline_bundle import BundleError, safe_relative, verify_checksums, verify_vtt, website_digest
from services.langgraph.agency.ucpo.build import output_digest


def _manifest(root, names):
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n" for name in names), encoding="utf-8")


def test_manifest_covers_exact_files_and_detects_tampering(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder/a.txt").write_text("good", encoding="utf-8")
    _manifest(tmp_path, ["folder/a.txt"])
    assert verify_checksums(tmp_path) == 1
    (tmp_path / "folder/a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(BundleError, match="checksum mismatch"):
        verify_checksums(tmp_path)
    _manifest(tmp_path, ["folder/a.txt"])
    (tmp_path / "unexpected").write_text("extra", encoding="utf-8")
    with pytest.raises(BundleError, match="checksum coverage differs"):
        verify_checksums(tmp_path)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../escape", "./a", "a//b", "a\\b", "."])
def test_manifest_refuses_unsafe_paths(name):
    with pytest.raises(BundleError):
        safe_relative(name)


def test_manifest_refuses_symlinks_even_when_their_content_matches(tmp_path):
    (tmp_path / "target").write_text("bytes", encoding="utf-8")
    (tmp_path / "link").symlink_to(tmp_path / "target")
    _manifest(tmp_path, ["target", "link"])
    with pytest.raises(BundleError, match="symlink"):
        verify_checksums(tmp_path)


def test_standalone_website_digest_matches_the_ucpo_algorithm(tmp_path):
    (tmp_path / "about").mkdir()
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    (tmp_path / "about/index.html").write_text("about", encoding="utf-8")
    assert website_digest(tmp_path) == output_digest(tmp_path)[0]


def test_vtt_requires_valid_bounded_nonempty_cues(tmp_path):
    vtt = tmp_path / "captions.vtt"
    vtt.write_text("WEBVTT\n\n1\n00:00:00.100 --> 00:00:01.000\nHello\n", encoding="utf-8")
    assert verify_vtt(vtt, duration_ms=1000, expected_cues=1) == 1
    vtt.write_text("WEBVTT\n\n1\n00:00:00.100 --> 00:00:01.001\nHello\n", encoding="utf-8")
    with pytest.raises(BundleError, match="out-of-range cue"):
        verify_vtt(vtt, duration_ms=1000, expected_cues=1)
    vtt.write_text("WEBVTT\n\n1\n00:00:00.100 --> 00:00:01.000\n\n", encoding="utf-8")
    with pytest.raises(BundleError, match="empty cue"):
        verify_vtt(vtt, duration_ms=1000, expected_cues=1)
