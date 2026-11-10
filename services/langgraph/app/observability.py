from __future__ import annotations

"""Structured logging and request observation (W8 foundation).

- AMC_LOG_FORMAT=json emits one JSON object per log record with patch-friendly
  fields; the default remains readable text for local development.
- AMCTracingMiddleware emits a request log line carrying
  method/path/status/duration plus the request id already assigned by
  ``request_id_middleware`` in ``app/main.py`` (the single owner of X-Request-ID
  and of its format validation), so a request can be traced through frontend
  logs, API access logs and application logs.
- AMC_DEPLOYED_REVISION is surfaced via /ready for deploy verification; never
  fabricate a revision value. /health stays pure liveness by design.
"""

import json
import logging
import time

from fastapi import Request, Response

_custom_log_format: str = ""


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(env: "str | None" = None) -> None:
    import os

    fmt = (env or os.environ.get("AMC_LOG_FORMAT") or "text").strip().lower()
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("AMC_LOG_LEVEL", "INFO").upper() or "INFO")


class AMCTracingMiddleware:
    """ASGI middleware: request id propagation + access log + timing."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # The request id is owned by request_id_middleware in app/main.py, which also
        # validates its shape. Reading it from the shared ASGI scope on the response
        # path (instead of parsing the inbound header here) keeps one correlation id
        # per request and never echoes an unvalidated client header into log output.
        started = time.perf_counter()

        async def send_with_request_id(message) -> None:
            if message.get("type") == "http.response.start":
                response_headers = message.setdefault("headers", [])
                request_id = str(scope.get("state", {}).get("request_id") or "")
                has_header = any(
                    k.decode("latin-1").lower() == "x-request-id" for k, _v in response_headers
                )
                if request_id and not has_header:
                    response_headers.append((b"x-request-id", request_id.encode()))
                status = message.get("status", 0)
                path = scope.get("path", "")
                method = scope.get("method", "")
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                logging.getLogger("amc.request").info(
                    json.dumps(
                        {
                            "request_id": request_id,
                            "method": method,
                            "path": path,
                            "status": status,
                            "duration_ms": duration_ms,
                        },
                        ensure_ascii=False,
                    )
                )
            await send(message)

        await self.app(scope, receive, send_with_request_id)
