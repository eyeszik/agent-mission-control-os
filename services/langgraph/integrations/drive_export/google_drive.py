"""Google Drive v3 client for the export runner.

Two ways to authenticate:

- ``ServiceAccount``: the OAuth 2.0 JWT-bearer exchange (RS256, signed locally
  with ``cryptography``). A service account has no storage quota of its own,
  so the destination folder has to be in a shared drive (Google Workspace), or
  the account has to impersonate a Workspace user through domain-wide
  delegation.
- ``OAuthUser``: a refresh token obtained once with ``scripts/drive_authorize.py``.
  Files belong to the signed-in user and use their quota, which is what a
  personal Google account needs. The default scope is ``drive.file``, so the
  token can only reach files and folders this tool created.

Implements only what the export runner needs: folder lookup and creation, file
search by ``appProperties``, resumable upload, metadata read back, download,
link sharing and trashing. Every call sets ``supportsAllDrives=true``.

Credentials are read from the environment by the runner, held in memory only,
never logged and never included in a repr or an error message.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from ._http import ApiError, request_with_retry

DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
# Full Drive scope: a service account can only reach items explicitly shared
# with it, so its effective access is the destination folder. ``drive.file``
# would hide the shared folder itself from folder lookups.
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
# Per-file scope for the OAuth user mode: only files this app created.
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
# Resumable chunks must be a multiple of 256 KiB (except the last one).
CHUNK_BYTES = 32 * 256 * 1024
FILE_FIELDS = "id,name,size,md5Checksum,webViewLink,appProperties,createdTime,trashed"


class DriveConfigError(ValueError):
    """The service-account credential is missing or malformed."""


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    private_key_pem: str = field(repr=False)
    token_uri: str = DEFAULT_TOKEN_URI
    subject: str | None = None

    @classmethod
    def from_value(cls, value: str, *, subject: str | None = None) -> "ServiceAccount":
        """Parse ``GOOGLE_SA_JSON``: either the key JSON itself or a path to it."""
        raw = (value or "").strip()
        if not raw:
            raise DriveConfigError("GOOGLE_SA_JSON is not set")
        if not raw.startswith("{"):
            path = Path(raw).expanduser()
            if not path.is_file():
                raise DriveConfigError("GOOGLE_SA_JSON is neither key JSON nor a readable file path")
            raw = path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise DriveConfigError("GOOGLE_SA_JSON is not valid JSON") from None
        if data.get("type") != "service_account":
            raise DriveConfigError("GOOGLE_SA_JSON is not a service-account key")
        email, key = data.get("client_email"), data.get("private_key")
        if not email or not key:
            raise DriveConfigError("GOOGLE_SA_JSON lacks client_email or private_key")
        return cls(email, key, data.get("token_uri") or DEFAULT_TOKEN_URI, subject or None)


@dataclass(frozen=True)
class OAuthUser:
    """A signed-in Google user, represented by an OAuth client and its refresh token."""

    client_id: str
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    token_uri: str = DEFAULT_TOKEN_URI

    def __post_init__(self) -> None:
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise DriveConfigError("OAuth sign-in needs a client id, client secret and refresh token")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def signed_assertion(account: ServiceAccount, *, now: int, scope: str = DRIVE_SCOPE) -> str:
    """Build the RS256 JWT the token endpoint exchanges for an access token."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": account.client_email, "scope": scope, "aud": account.token_uri, "iat": now, "exp": now + 3600}
    if account.subject:
        claims["sub"] = account.subject
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode("utf-8")) for part in (header, claims)
    )
    try:
        key = serialization.load_pem_private_key(account.private_key_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError):
        raise DriveConfigError("GOOGLE_SA_JSON private_key is not a usable PEM RSA key") from None
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64url(signature)}"


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(
        self,
        account: ServiceAccount | OAuthUser,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        chunk_bytes: int = CHUNK_BYTES,
    ) -> None:
        self._account = account
        self._http = httpx.Client(transport=transport, timeout=httpx.Timeout(60.0, connect=15.0))
        self._sleep = sleep
        self._clock = clock
        self._chunk = chunk_bytes
        self._token: str | None = None
        self._token_expiry = 0.0

    def __repr__(self) -> str:
        if isinstance(self._account, ServiceAccount):
            return f"DriveClient(service_account={self._account.client_email!r})"
        return "DriveClient(oauth_user)"

    def close(self) -> None:
        self._http.close()

    # -- auth ---------------------------------------------------------------
    def _access_token(self) -> str:
        now = self._clock()
        if self._token and now < self._token_expiry - 60:
            return self._token
        if isinstance(self._account, OAuthUser):
            form = {"grant_type": "refresh_token", "client_id": self._account.client_id,
                    "client_secret": self._account.client_secret, "refresh_token": self._account.refresh_token}
        else:
            form = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_assertion(self._account, now=int(now))}
        try:
            response = request_with_retry(self._http, "POST", self._account.token_uri, sleep=self._sleep, data=form)
        except ApiError as exc:
            if exc.status in (400, 401) and isinstance(self._account, OAuthUser):
                raise ApiError(
                    "Google rejected the OAuth refresh token (revoked, expired, or the consent screen is still in "
                    "Testing, which expires tokens after 7 days); run scripts/drive_authorize.py again",
                    status=exc.status) from None
            raise
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ApiError("token endpoint returned no access_token")
        self._token = token
        self._token_expiry = now + float(payload.get("expires_in", 3600))
        return token

    def _call(self, method: str, url: str, *, ok_status: frozenset[int] = frozenset(), headers=None, **kwargs):
        merged = {"Authorization": f"Bearer {self._access_token()}", **(headers or {})}
        return request_with_retry(self._http, method, url, sleep=self._sleep, ok_status=ok_status, headers=merged, **kwargs)

    # -- metadata -----------------------------------------------------------
    def get(self, file_id: str, *, fields: str = FILE_FIELDS) -> dict:
        return self._call("GET", f"{DRIVE_API}/files/{file_id}",
                          params={"fields": fields, "supportsAllDrives": "true"}).json()

    def list_files(self, query: str, *, order_by: str = "createdTime desc", page_size: int = 100) -> list[dict]:
        files: list[dict] = []
        params = {
            "q": query, "orderBy": order_by, "pageSize": str(page_size), "fields": f"nextPageToken,files({FILE_FIELDS})",
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "corpora": "allDrives",
        }
        while True:
            body = self._call("GET", f"{DRIVE_API}/files", params=params).json()
            files.extend(body.get("files", []))
            token = body.get("nextPageToken")
            if not token:
                return files
            params = {**params, "pageToken": token}

    def find_by_app_properties(self, properties: dict[str, str], *, parent_id: str | None = None) -> list[dict]:
        clauses = ["trashed = false"]
        clauses += [f"appProperties has {{ key='{_quote(k)}' and value='{_quote(v)}' }}" for k, v in sorted(properties.items())]
        if parent_id:
            clauses.append(f"'{_quote(parent_id)}' in parents")
        return self.list_files(" and ".join(clauses))

    def ensure_folder(self, name: str, parent_id: str) -> str:
        query = (f"mimeType = '{FOLDER_MIME}' and name = '{_quote(name)}' "
                 f"and '{_quote(parent_id)}' in parents and trashed = false")
        existing = self.list_files(query, order_by="createdTime")
        if existing:
            return existing[0]["id"]
        created = self._call("POST", f"{DRIVE_API}/files", params={"supportsAllDrives": "true", "fields": "id"},
                             json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}).json()
        return created["id"]

    # -- content ------------------------------------------------------------
    def upload(self, path: Path, *, name: str, parent_id: str, mime_type: str, app_properties: dict[str, str]) -> dict:
        """Resumable upload; returns the created file's metadata."""
        size = path.stat().st_size
        start = self._call(
            "POST", UPLOAD_API,
            params={"uploadType": "resumable", "supportsAllDrives": "true", "fields": FILE_FIELDS},
            headers={"X-Upload-Content-Type": mime_type, "X-Upload-Content-Length": str(size)},
            json={"name": name, "parents": [parent_id], "mimeType": mime_type, "appProperties": app_properties},
        )
        session = start.headers.get("Location")
        if not session:
            raise ApiError("resumable upload did not return a session URL")
        with path.open("rb") as handle:
            offset = 0
            while True:
                chunk = handle.read(self._chunk)
                end = offset + len(chunk) - 1
                content_range = f"bytes {offset}-{end}/{size}" if chunk else f"bytes */{size}"
                response = self._call("PUT", session, ok_status=frozenset({308}), content=chunk,
                                      headers={"Content-Range": content_range})
                if response.status_code != 308:
                    return response.json()
                offset = end + 1

    def download(self, file_id: str) -> bytes:
        return self._call("GET", f"{DRIVE_API}/files/{file_id}",
                          params={"alt": "media", "supportsAllDrives": "true"}).content

    def share_with_anyone_with_link(self, file_id: str) -> None:
        self._call("POST", f"{DRIVE_API}/files/{file_id}/permissions",
                   params={"supportsAllDrives": "true"}, json={"role": "reader", "type": "anyone"})

    def trash(self, file_id: str) -> None:
        """Move to trash (recoverable for 30 days), never a permanent delete."""
        self._call("PATCH", f"{DRIVE_API}/files/{file_id}", params={"supportsAllDrives": "true", "fields": "id"},
                   json={"trashed": True})
