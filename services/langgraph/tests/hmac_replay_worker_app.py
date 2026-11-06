"""Test-only ASGI app for the multi-worker replay test. Not used by the product."""

import asyncio
import os

from services.langgraph.security.hmac_ingress import HMACIngressConfig, HMACIngressMiddleware


async def _ok(scope, receive, send):
    await receive()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain"), (b"x-worker-pid", str(os.getpid()).encode())]})
    await send({"type": "http.response.body", "body": b"ok"})


async def _slow_entry(scope, receive, send):
    # Test-only: pause so overlapping requests are accepted by different workers, and stamp every response
    # (including middleware 401/503 responses) with the serving pid. The replay check is unchanged.
    await asyncio.sleep(0.25)

    async def stamped_send(message):
        if message.get("type") == "http.response.start":
            message = {**message, "headers": [*message.get("headers", []),
                                              (b"x-worker-pid", str(os.getpid()).encode())]}
        await send(message)

    await inner(scope, receive, stamped_send)


inner = HMACIngressMiddleware(_ok, HMACIngressConfig(
    header_name="X-AMC-Signature",
    secret=os.environ["AMC_TEST_HMAC_SECRET"].encode("utf-8"),
    protected_paths=("/p",),
    replay_backend=os.environ.get("AMC_TEST_REPLAY_BACKEND", "database"),
))
app = _slow_entry
