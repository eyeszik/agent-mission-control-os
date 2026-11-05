"""Test-only ASGI app for the mTLS transport test."""


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"tls-ok"})
