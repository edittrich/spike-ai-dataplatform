"""
Tests for mcp_server.financial_data_mcp_server.BearerAuthMiddleware -- zero
coverage previously (Q9): "BearerAuthMiddleware has zero coverage -- the
fail-open branch and the non-ASCII TypeError are both unexercised." Both are
covered here, plus the ordinary 401/200 paths.

Constructs ASGI scope/receive/send by hand rather than pulling in a test
client dependency (httpx/starlette TestClient) -- the middleware's contract
is a plain ASGI callable, so this exercises it directly and keeps the test
suite dependency-free.
"""

import asyncio

from mcp_server.financial_data_mcp_server import BearerAuthMiddleware

API_KEY = "test-secret-key-123"


async def _inner_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"OK"})


def _make_scope(auth_header_bytes=None):
    headers = []
    if auth_header_bytes is not None:
        headers.append((b"authorization", auth_header_bytes))
    return {"type": "http", "headers": headers}


async def _run(scope):
    middleware = BearerAuthMiddleware(_inner_app, API_KEY)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await middleware(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status


def test_missing_authorization_header_rejected():
    status = asyncio.run(_run(_make_scope(None)))
    assert status == 401


def test_wrong_token_rejected():
    status = asyncio.run(_run(_make_scope(b"Bearer wrong-token")))
    assert status == 401


def test_correct_token_accepted():
    status = asyncio.run(_run(_make_scope(f"Bearer {API_KEY}".encode())))
    assert status == 200


def test_empty_bearer_token_rejected():
    status = asyncio.run(_run(_make_scope(b"Bearer ")))
    assert status == 401


def test_non_ascii_authorization_header_rejected_not_500():
    # Regression test for H5's fix: hmac.compare_digest raises TypeError on a
    # non-ASCII str, which previously surfaced as an unhandled 500. Must
    # cleanly 401 instead.
    status = asyncio.run(_run(_make_scope("Bearer ü-not-the-key".encode("utf-8"))))
    assert status == 401


def test_non_http_scope_passes_through():
    # Non-HTTP ASGI scopes (e.g. lifespan events) must bypass auth entirely
    # rather than being rejected.
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "lifespan.startup"}

    async def run():
        middleware = BearerAuthMiddleware(_inner_app, API_KEY)
        await middleware({"type": "lifespan"}, receive, send)

    asyncio.run(run())
    # _inner_app only sends http.response.* messages; a lifespan scope
    # reaching it without an auth check would still produce those, proving
    # the middleware passed it straight through instead of 401ing it.
    assert any(m["type"] == "http.response.start" and m["status"] == 200 for m in sent)
