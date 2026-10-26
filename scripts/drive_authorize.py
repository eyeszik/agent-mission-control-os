#!/usr/bin/env python3
"""Sign in to Google once and print a refresh token for scripts/export_to_drive.py.

Run this on your own computer (it opens a browser and listens on 127.0.0.1):

    GOOGLE_OAUTH_CLIENT_ID=... GOOGLE_OAUTH_CLIENT_SECRET=... python scripts/drive_authorize.py

The client id and secret come from a Google Cloud OAuth client of type
"Desktop app". The refresh token is printed to stdout once. Copy it into your
secret store as GOOGLE_OAUTH_REFRESH_TOKEN; it is never written to disk.
See docs/drive-export.md.
"""

from __future__ import annotations

import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.langgraph.integrations.drive_export._http import ApiError  # noqa: E402
from services.langgraph.integrations.drive_export.oauth_setup import (  # noqa: E402
    build_authorization_url,
    exchange_code,
    new_pkce_pair,
)

WAIT_SECONDS = 300
PAGE = b"<html><body style='font-family:sans-serif'><h3>You can close this tab.</h3></body></html>"


def _wait_for_code(server: HTTPServer, expected_state: str, wait_seconds: float = WAIT_SECONDS) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlsplit(self.path).query)
            if query.get("state", [""])[0] == expected_state and "code" in query:
                result["code"] = query["code"][0]
            elif "error" in query:
                result["error"] = query["error"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args) -> None:  # keep the code out of any log
            return

    server.RequestHandlerClass = Handler
    server.timeout = 5
    deadline = time.monotonic() + wait_seconds
    # A request with the wrong state is ignored and the wait continues.
    while not result and time.monotonic() < deadline:
        server.handle_request()
    if "code" not in result:
        raise SystemExit(f"No authorization received ({result.get('error', 'timed out')}).")
    return result["code"]


def main() -> int:
    client_id = (os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        print("Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET (a Desktop-app OAuth client).", file=sys.stderr)
        return 2
    verifier, challenge = new_pkce_pair()
    state = secrets.token_urlsafe(24)
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = build_authorization_url(client_id, redirect_uri, state, challenge)
    print("Open this address in your browser and approve access:\n", file=sys.stderr)
    print(url, file=sys.stderr)
    webbrowser.open(url)
    try:
        code = _wait_for_code(server, state)
        token = exchange_code(client_id, client_secret, code, redirect_uri, verifier)
    except ApiError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    finally:
        server.server_close()
    print("\nStore this value as GOOGLE_OAUTH_REFRESH_TOKEN (it is not saved anywhere else):\n", file=sys.stderr)
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
