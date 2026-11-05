"""Mutual TLS for service-to-service links (OWASP ASI07, transport identity).

When enabled, a server requires a client certificate that chains to the configured client CA. A
connection without one, or with one from another CA, fails during the TLS handshake and never reaches
the application. HMAC v2 (``hmac_ingress``) still runs on top, so a stolen client certificate alone
does not authorize a request.

Configuration (all three together, or none). Any partial configuration is refused:

    AMC_MTLS_CERT_FILE       server certificate chain (PEM)
    AMC_MTLS_KEY_FILE        server private key (PEM)
    AMC_MTLS_CLIENT_CA_FILE  CA bundle that signs the client certificates allowed to connect

Scope: trust is CA-level. The handshake accepts any certificate issued by the configured CA. Per-service
identity therefore needs one CA per trust domain. The application cannot read the peer certificate
through uvicorn, so there is no per-CN check in the app.
"""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_KEYS = ("AMC_MTLS_CERT_FILE", "AMC_MTLS_KEY_FILE", "AMC_MTLS_CLIENT_CA_FILE")


@dataclass(frozen=True, slots=True)
class MTLSConfig:
    cert_file: str
    key_file: str
    client_ca_file: str


def load_mtls_config(env: Mapping[str, str] | None = None) -> MTLSConfig | None:
    """Return the validated mTLS configuration, or None when none of it is set. Fails closed otherwise."""
    source = os.environ if env is None else env
    values = {key: (source.get(key) or "").strip() for key in _KEYS}
    if not any(values.values()):
        return None
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"mTLS is partially configured; missing {', '.join(missing)}")
    config = MTLSConfig(values["AMC_MTLS_CERT_FILE"], values["AMC_MTLS_KEY_FILE"], values["AMC_MTLS_CLIENT_CA_FILE"])
    for path in (config.cert_file, config.key_file, config.client_ca_file):
        if not Path(path).is_file():
            raise RuntimeError(f"mTLS file not found: {path}")
    build_server_context(config)  # raises if the key does not match the certificate or the CA is unusable
    return config


def build_server_context(config: MTLSConfig) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=config.cert_file, keyfile=config.key_file)
    context.load_verify_locations(cafile=config.client_ca_file)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def uvicorn_tls_kwargs(config: MTLSConfig) -> dict:
    """Keyword arguments for ``uvicorn.run`` / ``uvicorn.Config`` that enforce client certificates."""
    return {
        "ssl_certfile": config.cert_file,
        "ssl_keyfile": config.key_file,
        "ssl_ca_certs": config.client_ca_file,
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
    }


def _status() -> str:
    try:
        config = load_mtls_config()
    except RuntimeError as exc:
        return f"REFUSED: {exc}"
    if config is None:
        return "DISABLED: no AMC_MTLS_* variables set"
    return "ENABLED: client certificates required"


if __name__ == "__main__":  # pragma: no cover - operator convenience; prints no secret material
    print(_status())
