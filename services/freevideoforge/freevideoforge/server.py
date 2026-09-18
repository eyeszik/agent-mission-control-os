"""Local web UI and JSON API.

Built on :mod:`http.server` so the UI adds no dependency at all. It binds to
loopback by default, serves one self-contained page with no CDN or external
asset, and exposes the same operations the CLI does.

Security posture: this is a local tool, not a public service. Binding to a
non-loopback address prints an explicit warning, path traversal is blocked when
serving run artifacts, and request bodies are size-capped and validated against
:class:`GenerateRequest` before anything runs.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import api, doctor
from .errors import ForgeError
from .models import GenerateRequest, JobState, to_jsonable
from .version import __version__

#: Request bodies larger than this are rejected outright.
MAX_BODY_BYTES = 256 * 1024

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

#: Served at /favicon.svg so the page does not generate a 404 on every load.
_FAVICON = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" rx="7" fill="#0B1020"/>'
    b'<circle cx="16" cy="16" r="6" fill="#F5C451"/>'
    b'<ellipse cx="16" cy="16" rx="13" ry="5" fill="none" stroke="#8E9BB7" '
    b'stroke-width="1.5"/></svg>'
)


class JobManager:
    """Runs jobs on background threads, bounded by the resource governor."""

    def __init__(self, workspace: Optional[str]) -> None:
        self.workspace = workspace
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        pipeline = api.build_pipeline(workspace)
        self._semaphore = threading.BoundedSemaphore(
            max(1, pipeline.settings.governor.max_concurrent_heavy_jobs)
        )

    def submit(self, request: GenerateRequest) -> str:
        from .state import new_run_id

        run_id = new_run_id()
        with self._lock:
            self._jobs[run_id] = {
                "run_id": run_id, "state": JobState.CREATED.value, "stage": "queued",
                "progress": 0.0, "message": "waiting for a render slot",
                "topic": request.topic, "result": None, "error": None,
            }

        def progress(stage: str, fraction: float, message: str) -> None:
            with self._lock:
                job = self._jobs[run_id]
                job.update(stage=stage, progress=round(fraction, 4), message=message)

        def work() -> None:
            with self._semaphore:
                try:
                    result = api.generate(
                        request, workspace=self.workspace, progress=progress, run_id=run_id
                    )
                    with self._lock:
                        self._jobs[run_id].update(
                            state=result.state.value,
                            result=to_jsonable(result),
                            error=result.error,
                            progress=1.0 if result.ok else self._jobs[run_id]["progress"],
                            message="complete" if result.ok else (result.error or "failed"),
                        )
                except Exception as exc:  # a crashed worker must still report
                    with self._lock:
                        self._jobs[run_id].update(
                            state=JobState.FAILED.value, error=str(exc),
                            message=f"{type(exc).__name__}: {exc}",
                        )
                    traceback.print_exc()

        threading.Thread(target=work, name=f"fvf-{run_id}", daemon=True).start()
        return run_id

    def get(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(run_id)
            return dict(job) if job else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in self._jobs.values()]


def _page() -> str:
    return (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = f"FreeVideoForge/{__version__}"
    manager: JobManager
    workspace: Optional[str]

    # -- plumbing --------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter default logging
        return

    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This UI never loads a remote asset; the policy makes that enforceable.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; media-src 'self'; img-src 'self' data:",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(to_jsonable(payload), indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route == "/favicon.svg":
                self._send(HTTPStatus.OK, _FAVICON, "image/svg+xml")
            elif route in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, _page().encode("utf-8"),
                           "text/html; charset=utf-8")
            elif route == "/api/health":
                self._json(HTTPStatus.OK, {"ok": True, "version": __version__})
            elif route == "/api/doctor":
                self._json(HTTPStatus.OK, doctor.collect(self.workspace))
            elif route == "/api/providers":
                self._json(HTTPStatus.OK, api.describe_providers(self.workspace))
            elif route == "/api/runs":
                limit = int(parse_qs(parsed.query).get("limit", ["25"])[0])
                self._json(HTTPStatus.OK, {
                    "runs": api.list_runs(self.workspace, limit=min(200, max(1, limit))),
                    "jobs": self.manager.all(),
                })
            elif route.startswith("/api/jobs/"):
                run_id = unquote(route.rsplit("/", 1)[-1])
                job = self.manager.get(run_id)
                if job is None:
                    try:
                        self._json(HTTPStatus.OK, api.run_status(run_id, self.workspace))
                    except ForgeError:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
                else:
                    self._json(HTTPStatus.OK, job)
            elif route.startswith("/media/"):
                self._serve_media(unquote(route[len("/media/"):]))
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                       {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route == "/api/generate":
                payload = self._read_body()
                payload.pop("output_dir", None)  # the server owns output placement
                request = GenerateRequest.from_dict(payload)
                request.validate()
                run_id = self.manager.submit(request)
                self._json(HTTPStatus.ACCEPTED, {"run_id": run_id})
            elif route == "/api/resume":
                payload = self._read_body()
                run_id = str(payload.get("run_id", ""))
                if not run_id:
                    raise ValueError("run_id is required")
                record = api.run_status(run_id, self.workspace)
                self._json(HTTPStatus.OK, record)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (ForgeError, ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                       {"error": f"{type(exc).__name__}: {exc}"})

    def _serve_media(self, relative: str) -> None:
        """Serve a produced artifact, refusing anything outside the output root.

        Range requests are supported because browsers will not play an MP4
        without them - a video element given a non-seekable response reports a
        duration of zero and never starts.
        """
        from .config import Settings

        settings = Settings.resolve(self.workspace)
        root = settings.output_root.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self._json(HTTPStatus.FORBIDDEN, {"error": "refused"})
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        size = target.stat().st_size
        start, end = self._parse_range(self.headers.get("Range"), size)

        with target.open("rb") as handle:
            if start is None:
                data = handle.read()
                self._send(HTTPStatus.OK, data, content_type,
                           {"Accept-Ranges": "bytes", "Cache-Control": "no-store"})
                return
            handle.seek(start)
            data = handle.read(end - start + 1)

        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    @staticmethod
    def _parse_range(header: Optional[str], size: int) -> tuple[Optional[int], int]:
        """Parse a single-range `bytes=` header. Returns (None, size-1) when the
        whole file should be sent."""
        if not header or not header.startswith("bytes=") or size == 0:
            return None, size - 1
        spec = header[len("bytes="):].split(",")[0].strip()
        first, _, last = spec.partition("-")
        try:
            if not first:  # suffix range: bytes=-500
                length = int(last)
                start = max(0, size - length)
                return start, size - 1
            start = int(first)
            end = int(last) if last else size - 1
        except ValueError:
            return None, size - 1
        if start >= size:
            return None, size - 1
        return start, min(end, size - 1)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: Optional[str] = None,
    open_browser: bool = True,
) -> int:
    """Start the local UI. Blocks until interrupted."""
    Handler.manager = JobManager(workspace)
    Handler.workspace = workspace
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/"

    print(f"FreeVideoForge {__version__} - local UI at {url}")
    if host not in _LOOPBACK and host != "":
        print(
            "WARNING: you bound to a non-loopback address. This server has no "
            "authentication and is meant for local use only.",
        )
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
    return 0
