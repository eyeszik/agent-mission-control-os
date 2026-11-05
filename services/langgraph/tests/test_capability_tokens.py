"""ASI03: per-call capability tokens. Unit rules, gateway integration, and a real MCP server that verifies."""

import json
import sys
import time
from pathlib import Path

import pytest

from services.langgraph.agency.council import capability as cap
from services.langgraph.agency.council.gateway import GatewayDenied, invoke
from services.langgraph.tests.council_support import council  # noqa: F401 - fixture

pytest.importorskip("cryptography")
SCOPES = frozenset({"mcp:read"})
TOOL = "mcp.testsrv.echo_verified"
ARGS = {"text": "hello"}
CTX = {"tenant_id": "tenant_1", "project_id": "proj_1", "mission_id": "m-1"}


def _issuer():
    return cap.CapabilityIssuer()


def _mint(issuer, **overrides):
    kwargs = {"tool_id": TOOL, "seat": "george", "scopes": SCOPES, "args": ARGS, "ctx": CTX}
    kwargs.update(overrides)
    return issuer.mint(**kwargs)


def _verify(issuer, token, **overrides):
    kwargs = {"public_key": issuer.public_key(), "tool_id": TOOL, "args": ARGS, "required_scopes": SCOPES}
    kwargs.update(overrides)
    return cap.verify(token, **kwargs)


def _code(fn) -> str:
    with pytest.raises(cap.CapabilityError) as exc:
        fn()
    return exc.value.code


def test_round_trip_verifies_and_is_single_use():
    issuer = _issuer()
    token = _mint(issuer)
    registry = cap.JTIRegistry()
    claims = _verify(issuer, token, registry=registry)
    assert claims["aud"] == TOOL and claims["sub"] == "george" and claims["scopes"] == ["mcp:read"]
    assert _code(lambda: _verify(issuer, token, registry=registry)) == "TOKEN_REPLAYED"


def test_capability_is_bound_to_the_exact_arguments_and_the_tool():
    issuer = _issuer()
    token = _mint(issuer)
    assert _code(lambda: _verify(issuer, token, args={"text": "other"})) == "ARGS_MISMATCH"
    assert _code(lambda: _verify(issuer, token, tool_id="mcp.testsrv.fail")) == "AUDIENCE_MISMATCH"


def test_scopes_must_cover_the_call():
    issuer = _issuer()
    token = _mint(issuer, scopes=frozenset({"mcp:read"}))
    assert _code(lambda: _verify(issuer, token, required_scopes=frozenset({"mcp:write"}))) == "SCOPE_INSUFFICIENT"


def test_lifetime_and_clock_rules():
    issuer = _issuer()
    now = time.time()
    token = _mint(issuer, now=now, ttl_s=30)
    assert _code(lambda: _verify(issuer, token, now=now + 36)) == "TOKEN_EXPIRED"
    assert _verify(issuer, token, now=now + 34)  # inside the leeway
    assert _code(lambda: _verify(issuer, token, now=now - 60)) == "TOKEN_NOT_YET_VALID"
    assert _code(lambda: _mint(issuer, ttl_s=cap.MAX_TTL_S + 1)) == "TTL_INVALID"
    assert _code(lambda: _mint(issuer, ttl_s=0)) == "TTL_INVALID"


def test_tampering_and_key_confusion_are_refused():
    issuer = _issuer()
    token = _mint(issuer)
    header, payload, sig = token.split(".")
    forged_claims = cap._b64(cap._json({**json.loads(cap._unb64(payload)), "scopes": ["mcp:write"]}))
    assert _code(lambda: _verify(issuer, f"{header}.{forged_claims}.{sig}")) == "SIGNATURE_INVALID"
    other = _issuer()  # a different signing key must not verify this token
    assert _code(lambda: _verify(other, token)) == "SIGNATURE_INVALID"
    none_header = cap._b64(cap._json({"alg": "none", "typ": "amc-cap+jwt"}))
    assert _code(lambda: _verify(issuer, f"{none_header}.{payload}.{sig}")) == "ALG_REJECTED"
    assert _code(lambda: _verify(issuer, "not-a-token")) == "TOKEN_MALFORMED"


def test_the_verifier_is_bounded_and_fails_closed(monkeypatch):
    issuer = _issuer()
    registry = cap.JTIRegistry(max_entries=1)
    _verify(issuer, _mint(issuer), registry=registry)
    assert _code(lambda: _verify(issuer, _mint(issuer), registry=registry)) == "VERIFIER_SATURATED"


def test_signing_key_loads_from_a_file_and_must_be_ed25519(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = cap.CapabilityIssuer()._key
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path = tmp_path / "cap.pem"
    path.write_bytes(pem)
    monkeypatch.setenv("AMC_CAPABILITY_SIGNING_KEY_FILE", str(path))
    loaded = cap.CapabilityIssuer.from_environment()
    assert loaded.public_key_pem() == key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    rsa_pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.write_bytes(rsa_pem)
    with pytest.raises(cap.CapabilityError):
        cap.CapabilityIssuer.from_environment()


@pytest.fixture
def capability_server(monkeypatch, tmp_path, council):  # noqa: F811
    pytest.importorskip("mcp")
    pytest.importorskip("jsonschema")
    from services.langgraph.agency.council.mcp_client import file_sha256

    issuer = cap.CapabilityIssuer()
    cap.reset_default_issuer()
    monkeypatch.setattr(cap, "_ISSUER", issuer)
    public_pem = tmp_path / "capability-public.pem"
    public_pem.write_bytes(issuer.public_key_pem())
    server = str(Path(__file__).parent / "fixtures" / "council_mcp_server.py")
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps({"testsrv": {
        "command": sys.executable, "args": ["-I", server, "--public-key-file", str(public_pem)],
        "pins": {sys.executable: file_sha256(sys.executable), server: file_sha256(server),
                 str(public_pem): file_sha256(str(public_pem))},
        "tools": {"echo_verified": {"sensitivity": "READ", "timeout_s": 20},
                  "echo": {"sensitivity": "READ"}}}}))
    yield issuer
    cap.reset_default_issuer()


def test_gateway_presents_a_capability_that_the_mcp_server_verifies(capability_server, monkeypatch, council):  # noqa: F811
    from services.langgraph.tests.council_support import gated_mission

    mission = gated_mission(monkeypatch, council["project_id"])
    ctx = {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"], "mission_id": mission["mission_id"],
           "user_id": "tester"}
    result = invoke(TOOL, {"text": "bound call"}, ctx=ctx, seat="george", mission=mission)
    content = result["result"]["content"]
    assert content and content[0].startswith("verified:"), result
    _, jti, echoed = content[0].split(":", 2)
    assert echoed == "bound call"
    assert result["capability"]["jti"] == jti
    assert result["capability"]["scopes"] == ["mcp:read"]


def test_gateway_denies_a_seat_whose_scopes_do_not_cover_the_tool(capability_server, monkeypatch, council):  # noqa: F811
    from services.langgraph.agency.council import gateway
    from services.langgraph.tests.council_support import gated_mission

    mission = gated_mission(monkeypatch, council["project_id"])
    ctx = {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"], "mission_id": mission["mission_id"],
           "user_id": "tester"}
    monkeypatch.setitem(gateway.SEAT_SCOPES, "nobody", frozenset())
    with pytest.raises(GatewayDenied) as exc:
        invoke(TOOL, {"text": "x"}, ctx=ctx, seat="nobody", mission=mission)
    assert exc.value.code == "SCOPE_NOT_GRANTED"
