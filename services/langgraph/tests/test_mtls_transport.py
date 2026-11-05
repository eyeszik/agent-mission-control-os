"""mTLS transport tests against a real uvicorn TLS server. Certificates are synthetic and generated here.

They are test fixtures for the contract only. No production key or CA is created or stored.
"""

import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from services.langgraph.security import mtls

REPO_ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI not available")


def _openssl(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def _ca(dir_: Path, name: str) -> tuple[Path, Path]:
    key, cert = dir_ / f"{name}.key", dir_ / f"{name}.pem"
    _openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", f"/CN={name}",
             "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
             cwd=dir_)
    return cert, key


def _leaf(dir_: Path, name: str, ca: tuple[Path, Path], usage: str, san: str = "") -> tuple[Path, Path]:
    key, csr, cert, ext = dir_ / f"{name}.key", dir_ / f"{name}.csr", dir_ / f"{name}.pem", dir_ / f"{name}.ext"
    ext_lines = [f"extendedKeyUsage={usage}", "basicConstraints=CA:FALSE"]
    if san:
        ext_lines.append(f"subjectAltName={san}")
    ext.write_text("\n".join(ext_lines) + "\n")
    _openssl("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}", cwd=dir_)
    _openssl("x509", "-req", "-in", str(csr), "-CA", str(ca[0]), "-CAkey", str(ca[1]), "-CAcreateserial",
             "-out", str(cert), "-days", "2", "-extfile", str(ext), cwd=dir_)
    return cert, key


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    d = tmp_path_factory.mktemp("mtls")
    client_ca = _ca(d, "amc-client-ca")
    rogue_ca = _ca(d, "rogue-ca")
    server = _leaf(d, "amc-server", client_ca, "serverAuth", "IP:127.0.0.1,DNS:localhost")
    client = _leaf(d, "amc-worker", client_ca, "clientAuth")
    rogue = _leaf(d, "rogue-client", rogue_ca, "clientAuth")
    return {"dir": d, "client_ca": client_ca[0], "server": server, "client": client, "rogue": rogue}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def tls_server(pki):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.langgraph.tests.mtls_worker_app:app", "--host", "127.0.0.1",
         "--port", str(port), "--ssl-certfile", str(pki["server"][0]), "--ssl-keyfile", str(pki["server"][1]),
         "--ssl-ca-certs", str(pki["client_ca"]), "--ssl-cert-reqs", "2", "--log-level", "warning"],
        cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail(proc.stderr.read().decode()[-800:])
    yield f"https://127.0.0.1:{port}/"
    proc.terminate()
    proc.wait(15)


def test_trusted_client_certificate_is_accepted(pki, tls_server):
    with httpx.Client(verify=ssl.create_default_context(cafile=str(pki["client_ca"])), cert=(str(pki["client"][0]), str(pki["client"][1])),
                      timeout=15) as client:
        response = client.get(tls_server)
    assert response.status_code == 200
    assert response.text == "tls-ok"


def test_connection_without_a_client_certificate_fails_the_handshake(pki, tls_server):
    with httpx.Client(verify=ssl.create_default_context(cafile=str(pki["client_ca"])), timeout=15) as client:
        with pytest.raises(httpx.TransportError):
            client.get(tls_server)


def test_client_certificate_from_another_ca_is_refused(pki, tls_server):
    with httpx.Client(verify=ssl.create_default_context(cafile=str(pki["client_ca"])), cert=(str(pki["rogue"][0]), str(pki["rogue"][1])),
                      timeout=15) as client:
        with pytest.raises(httpx.TransportError):
            client.get(tls_server)


def test_partial_or_mismatched_configuration_is_refused(pki, monkeypatch):
    with pytest.raises(RuntimeError, match="partially configured"):
        mtls.load_mtls_config({"AMC_MTLS_CERT_FILE": str(pki["server"][0])})
    # A certificate paired with the wrong key must not load.
    with pytest.raises(ssl.SSLError):
        mtls.load_mtls_config({
            "AMC_MTLS_CERT_FILE": str(pki["server"][0]),
            "AMC_MTLS_KEY_FILE": str(pki["client"][1]),
            "AMC_MTLS_CLIENT_CA_FILE": str(pki["client_ca"]),
        })
    assert mtls.load_mtls_config({}) is None


def test_valid_configuration_yields_client_cert_requirement(pki):
    config = mtls.load_mtls_config({
        "AMC_MTLS_CERT_FILE": str(pki["server"][0]),
        "AMC_MTLS_KEY_FILE": str(pki["server"][1]),
        "AMC_MTLS_CLIENT_CA_FILE": str(pki["client_ca"]),
    })
    kwargs = mtls.uvicorn_tls_kwargs(config)
    assert kwargs["ssl_cert_reqs"] == ssl.CERT_REQUIRED
    assert mtls.build_server_context(config).verify_mode == ssl.CERT_REQUIRED
