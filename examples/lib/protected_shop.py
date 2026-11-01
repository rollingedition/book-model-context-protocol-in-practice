"""The shop's MCP server as chapter 8 protects it: chapter 3's five tools behind OAuth, over Streamable HTTP.

    from lib import auth_server, protected_shop
    with auth_server.serve() as issuer, protected_shop.serve(issuer.url) as url:   # url: ".../mcp"
        ...

`create_app(resource, issuer)` builds the server with the SDK's `AuthSettings`: the authorization server at `issuer`,
`resource` as the resource server URL (the endpoint's own URL, which the Protected Resource Metadata names and each
token's `aud` must equal), `ENDPOINT_SCOPES` required on every request, and `validate_token_resource=True`. The
token verifier is `lib.auth_server.JwtVerifier`. It then wraps the app with `lib.tool_scopes.require` and
`TOOL_SCOPES`, so a refund needs `refunds:write`. `hide_tools=True` also filters `tools/list` by the token's scopes.

`call_at_2025_11_25(url, token, params)` makes a tool call the way a client at revision 2025-11-25 does: `initialize`,
then `tools/call` in the session it opened, with no `Mcp-Method` or `Mcp-Name` header. The SDK's server still
accepts that revision on the same endpoint, so a scope check must hold for it too.

`call_with_headers(url, params, headers)` sends `tools/call` with `params` as `lib.http_mcp.post` does, but takes
`headers` as a list of pairs, so that a header can be sent twice, as an attacker would send `Authorization`.

`serve(issuer, ...)` serves that app on loopback with `lib.auth_server.serve_built` and yields the endpoint's URL.
The tools call the shop's API with the address and key in this process's environment (`SHOP_API_URL`,
`SHOP_API_KEY`), as in chapter 6's in-process examples.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx2
from mcp.server.auth.settings import AuthSettings

from lib import auth_server, http_mcp, raw_stdio, shop_tools, tool_scopes

ENDPOINT_SCOPES = ["orders:read", "stock:read"]
TOOL_SCOPES = {"find_orders": "orders:read", "get_order_status": "orders:read", "quote_refund": "orders:read",
               "check_stock": "stock:read", "issue_refund": "refunds:write"}
VERSION = "0.8.0"
OLD_REVISION = "2025-11-25"


def create_app(resource: str, issuer: str, *, hide_tools: bool = False):
    """The protected server's Streamable HTTP app, with scopes per tool."""
    verifier = auth_server.JwtVerifier(issuer)
    settings = AuthSettings(issuer_url=issuer, resource_server_url=resource, required_scopes=ENDPOINT_SCOPES,
                            validate_token_resource=True)
    server = shop_tools.create_server(version=VERSION, auth=settings, token_verifier=verifier)
    if hide_tools:
        tool_scopes.hide_unscoped(server, TOOL_SCOPES)
    return tool_scopes.require(server.streamable_http_app(), TOOL_SCOPES, verifier=verifier, resource=resource)


def call_at_2025_11_25(url: str, token: str, params: dict) -> httpx2.Response:
    """`initialize` at 2025-11-25, then `tools/call` with `params` in that session, as a client at that revision would."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json", "MCP-Protocol-Version": OLD_REVISION}
    hello = {"protocolVersion": OLD_REVISION, "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}}
    started = httpx2.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": hello},
                          headers=headers, timeout=10.0)
    headers["Mcp-Session-Id"] = started.headers["mcp-session-id"]
    httpx2.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers, timeout=10.0)
    return httpx2.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params},
                       headers=headers, timeout=10.0)


def call_with_headers(url: str, params: dict, headers: list[tuple[str, str]]) -> httpx2.Response:
    """`tools/call` with `params`, as `lib.http_mcp.post` sends it, plus `headers`, which may repeat a name."""
    sent = [("Content-Type", "application/json"), ("Accept", "application/json, text/event-stream"),
            ("MCP-Protocol-Version", http_mcp.VERSION), ("Mcp-Method", "tools/call"), ("Mcp-Name", params["name"])]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {**params, "_meta": raw_stdio.envelope(http_mcp.VERSION, capabilities={})}}
    return httpx2.post(url, content=json.dumps(body), headers=sent + headers, timeout=10.0)


@contextmanager
def serve(issuer: str, **options) -> Iterator[str]:
    """Serve the protected server on loopback and yield its endpoint URL."""
    with auth_server.serve_built(lambda base_url: create_app(base_url + "/mcp", issuer, **options)) as base_url:
        yield base_url + "/mcp"
