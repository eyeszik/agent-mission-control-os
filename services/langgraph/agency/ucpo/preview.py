"""Local preview of a verified export. Loopback only; nothing is deployed or published.

``materialize`` writes the stored export to a fresh directory and refuses it unless its
digest equals the build output hash the browser verification checked. ``serve`` binds
127.0.0.1 only, serves files from that directory with traversal refused, and returns a
``PreviewResult`` (endpoint, matching build revision, cleanup state). Serving is a plain
static file server for already-built HTML/CSS/JS; no generated code runs in this process.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash


@dataclass
class PreviewResult:
    reachable_endpoint: Optional[str]
    matching_build_revision: Optional[str]
    cleanup_state: str
    reasons: list[str] = field(default_factory=list)
    _server: Optional[ThreadingHTTPServer] = None
    _dir: Optional[Path] = None

    def stop(self) -> "PreviewResult":
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._dir is not None and self._dir.name.startswith("amc-ucpo-preview-"):
            shutil.rmtree(self._dir, ignore_errors=True)
        self.cleanup_state = "CLEANED"
        self.reachable_endpoint = None
        return self

    def describe(self) -> dict:
        return {"reachable_endpoint": self.reachable_endpoint, "matching_build_revision": self.matching_build_revision,
                "cleanup_state": self.cleanup_state, "reasons": self.reasons}


def materialize(export: dict[str, str], *, expected_output_hash: str) -> Path:
    entries = []
    for rel, b64 in export.items():
        parts = rel.split("/")
        if rel.startswith("/") or any(p in {"", ".", ".."} for p in parts):
            raise ValueError(f"unsafe export path {rel!r}")
        entries.append((rel, hashlib.sha256(base64.b64decode(b64)).hexdigest()))
    if canonical_hash(sorted(entries)) != expected_output_hash:
        raise ValueError("export does not match the verified build output")
    target = Path(tempfile.mkdtemp(prefix="amc-ucpo-preview-"))
    for rel, b64 in export.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(b64))
    return target


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - quiet; the operator sees the URL
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                    "script-src 'self' 'unsafe-inline'; connect-src 'self'")
        super().end_headers()


def serve(export: dict[str, str], *, expected_output_hash: str, port: int = 0) -> PreviewResult:
    try:
        directory = materialize(export, expected_output_hash=expected_output_hash)
    except ValueError as exc:
        return PreviewResult(None, None, "NOTHING_CREATED", [str(exc)])
    server = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(_Handler, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, bound = server.server_address[:2]
    return PreviewResult(f"http://{host}:{bound}/", expected_output_hash, "RUNNING", [], server, directory)


__all__ = ["PreviewResult", "materialize", "serve"]
