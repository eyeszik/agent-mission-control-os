"""One-time Google sign-in for the export runner (installed-app OAuth, PKCE).

``scripts/drive_authorize.py`` opens a consent page on the user's own machine,
receives the authorization code on a loopback address, and exchanges it for a
refresh token with these functions. Only the refresh token is returned. It is
printed once by the script and never written to disk or logged.

The default scope is ``drive.file``: the resulting token can only reach files
and folders the export tool created, not the rest of the user's Drive.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from ._http import ApiError, request_with_retry
from .google_drive import DEFAULT_TOKEN_URI, DRIVE_FILE_SCOPE

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"


def new_pkce_pair() -> tuple[str, str]:
    """A random code verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(client_id: str, redirect_uri: str, state: str, challenge: str,
                            *, scope: str = DRIVE_FILE_SCOPE) -> str:
    return AUTH_URI + "?" + urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # offline + consent make Google issue a refresh token even on a repeat sign-in.
        "access_type": "offline",
        "prompt": "consent",
    })


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str,
                  *, transport: httpx.BaseTransport | None = None, token_uri: str = DEFAULT_TOKEN_URI) -> str:
    """Exchange an authorization code for a refresh token."""
    with httpx.Client(transport=transport, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = request_with_retry(client, "POST", token_uri, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "client_secret": client_secret, "code_verifier": verifier,
        })
    token = response.json().get("refresh_token")
    if not token:
        raise ApiError("Google returned no refresh token; remove this app under "
                       "myaccount.google.com/permissions and run the authorization again")
    return token
