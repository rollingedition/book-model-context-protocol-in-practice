"""Scopes per tool for a protected MCP server over Streamable HTTP (chapter 8).

The SDK's `AuthSettings.required_scopes` applies to the whole endpoint: every request needs every scope in it. There
is nothing per tool. An HTTP middleware can check a tool's scope before the server runs the call, and answer the way
the authorization spec asks: 403 with `WWW-Authenticate: Bearer error="insufficient_scope", scope="...", resource_metadata="..."`,
which is what the SDK's client steps up on.

    from lib import tool_scopes
    app = tool_scopes.require(server.streamable_http_app(), TOOL_SCOPES, verifier=verifier, resource=resource_url)
    tool_scopes.hide_unscoped(server, TOOL_SCOPES)    # optional: tools/list shows only what the token allows

`require(app, scopes, ...)` wraps the server's app. It decides on the request the server will execute, with the
credential the SDK will authenticate, in this order:

- **One credential.** A request with more than one `Authorization` header gets 400 `invalid_request`, whatever its
  method. The SDK's `BearerAuthBackend` reads the first such header, so two of them would let a check that read any
  other one decide on a different token from the SDK's.
- **One message.** A POST body that doesn't parse as a single JSON object, or that repeats a key, gets 400 and
  -32700, so the middleware and the server can never read different names from one body.
- **Deny by default.** A message with no `method` (a response to the server), a notification, and a method that names
  nothing (`initialize`, `ping`, `server/discover` and the `*/list` methods) need only the endpoint's scopes, which the
  SDK checks. `tools/call` is checked against `scopes`, and a tool not in `scopes` is refused. Every other method,
  including `prompts/get`, `resources/read`, `completion/complete`, `subscriptions/listen` and the `tasks/*` methods,
  names a prompt, resource or task that `scopes` can't map, so it gets 403 with no challenge, since no scope would help.
- **The tool in the body.** For `tools/call`, the tool is `params.name`. `Mcp-Name` is only a routing hint: when
  present, it is decoded as the SDK and the specification do (`decode_header_value`, so the `=?base64?...?=` form
  counts) and must equal `params.name`, or the request gets 400 and -32020, `HeaderMismatch`. A client at revision
  2025-11-25, which the SDK's server still accepts on the same endpoint, sends no `Mcp-Name`, and is checked the same.
- **The SDK's token.** The token is read by the SDK's own `BearerAuthBackend`, with `verifier`: the same header, the
  same `Bearer ` prefix and the same expiry check. No token, or one that doesn't verify or has expired, gets 401
  `invalid_token`; so does a token issued for another resource, compared as the SDK compares it. A valid token that
  lacks any of the tool's scopes (one, or several separated by spaces) gets 403 with the challenge, whose `scope`
  lists all of the tool's scopes, as the spec asks ("all scopes required for the current operation in a single
  challenge"); the endpoint's own scopes, which the token already carries, stay out of it.

The scope and the headers are then handed on to `app` unchanged, with the body as it arrived.

`hide_unscoped(server, scopes)` adds a server middleware that drops from `tools/list` every tool whose scope the
request's token lacks, reading the token with the SDK's `get_access_token()`.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.shared.inbound import MCP_NAME_HEADER, decode_header_value
from mcp_types.jsonrpc import HEADER_MISMATCH, INVALID_REQUEST, PARSE_ERROR
from pydantic import AnyHttpUrl, ValidationError
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Methods that name no tool, prompt, resource or task, so the endpoint's scopes are enough for them.
NAMES_NOTHING = frozenset({"initialize", "ping", "server/discover", "tools/list", "prompts/list", "resources/list",
                           "resources/templates/list"})


def require(app: ASGIApp, scopes: Mapping[str, str], *, verifier: TokenVerifier, resource: str) -> ASGIApp:
    """`app` with a 403 `insufficient_scope` challenge for any tool call whose token lacks the tool's scope."""
    metadata_url = str(build_resource_metadata_url(AnyHttpUrl(resource)))
    this_resource = _canonical(resource)
    authenticate = BearerAuthBackend(verifier).authenticate              # the SDK's own reading of the header

    async def refuse(send: Send, status: int, body: dict, challenge: str | None = None) -> None:
        content = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(content)).encode())]
        if challenge:
            headers.append((b"www-authenticate", challenge.encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": content})

    async def checked(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        headers = [(k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in scope.get("headers", [])]
        if sum(key == "authorization" for key, _ in headers) > 1:
            await refuse(send, 400, {"error": "invalid_request"},
                         f'Bearer error="invalid_request", error_description="Send one Authorization header", '
                         f'resource_metadata="{metadata_url}"')
            return
        if scope["method"].upper() != "POST":
            await app(scope, receive, send)
            return
        body, more = b"", True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return                                                    # the client went away
            body, more = body + message.get("body", b""), message.get("more_body", False)
        request = _parse(body)
        if request is None:
            await refuse(send, 400, _rpc_error(None, PARSE_ERROR, "Send one JSON-RPC message, with no repeated keys"))
            return
        method = request.get("method")
        if "method" in request and not (method in NAMES_NOTHING or method == "tools/call"
                                        or isinstance(method, str) and method.startswith("notifications/")):
            await refuse(send, 403, _rpc_error(request.get("id"), INVALID_REQUEST,
                                               f"No scope is mapped for {str(method)[:64]!r}; the server refuses it"))
            return
        if method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            name = params.get("name")
            named = [value for key, value in headers if key == MCP_NAME_HEADER]
            if named and (len(named) > 1 or decode_header_value(named[0]) != name):
                await refuse(send, 400, _rpc_error(request.get("id"), HEADER_MISMATCH,
                                                   "Mcp-Name header does not match the request body's 'name' parameter"))
                return
            needed = scopes.get(name) if isinstance(name, str) else None
            if needed is None:
                await refuse(send, 403, _rpc_error(request.get("id"), INVALID_REQUEST,
                                                   "No scope is mapped for this tool; the server refuses it"))
                return
            authenticated = await authenticate(HTTPConnection(scope))
            token = authenticated[1].access_token if authenticated else None
            if token is None or _canonical(token.resource) != this_resource:
                why = "Token is not for this resource" if token else "Authentication required"
                await refuse(send, 401, {"error": "invalid_token"},
                             f'Bearer error="invalid_token", error_description="{why}", '
                             f'resource_metadata="{metadata_url}"')
                return
            if not set(needed.split()) <= set(token.scopes):
                await refuse(send, 403, {"error": "insufficient_scope", "scope": needed},
                             f'Bearer error="insufficient_scope", scope="{needed}", '
                             f'resource_metadata="{metadata_url}", error_description="{name} needs {needed}"')
                return
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await app(scope, replay, send)

    return checked


def _parse(body: bytes) -> dict | None:
    """The body as one JSON object, or None if it isn't one or repeats a key (two parsers could disagree on it)."""
    def no_repeats(pairs: list[tuple[str, object]]) -> dict:
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("repeated key")
        return dict(pairs)

    try:
        parsed = json.loads(body, object_pairs_hook=no_repeats)
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _canonical(url: str | None) -> str | None:
    """`url` as the SDK compares a token's resource: as a URL, a trailing slash aside."""
    try:
        return str(AnyHttpUrl(url or "")).removesuffix("/")
    except ValidationError:
        return None


def _rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def hide_unscoped(server, scopes: Mapping[str, str]) -> None:
    """Make `tools/list` on `server` leave out each tool whose scope the request's token doesn't carry."""

    async def filter_tools(ctx, call_next):
        result = await call_next(ctx)
        token = get_access_token()
        if ctx.method != "tools/list" or token is None:
            return result
        allowed = [tool for tool in result["tools"] if set(scopes.get(tool["name"], "").split()) <= set(token.scopes)]
        return {**result, "tools": allowed}

    server.middleware.append(filter_tools)
