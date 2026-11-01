"""The shop's server as a 2025-era team wrote it, kept as text for chapter 12: read and scanned, never imported.

    from lib import legacy
    legacy.SERVER, legacy.HOST_AUTH       # the 1.x server file and the 2025 host's OAuth setup, as source text
    legacy.WRITTEN_FOR                    # the SDK release the listings were written against
    for rule in legacy.RULES: ...         # what each 2025 dependency is, its status at 2026-07-28, its replacement

SDK 1.x and SDK 2.x are both the `mcp` distribution, so one environment holds only one of them, and the examples'
runtime pins 2.x. That is why the 2025-era code lives here as strings: chapter 12 shows it, and `scan-a-2025-server`
parses it with `ast`, but nothing runs it. The listings were written against the `mcp` 1.30.0 wheel's source
(`mcp/server/fastmcp/server.py`: the constructor's `instructions`, `port` and `stateless_http`, `Context.elicit`,
`Context.info`; `mcp/server/session.py`: `create_message`, `list_roots`; `mcp/client/auth/oauth2.py`:
`OAuthClientProvider`, which registers dynamically when it has no `client_metadata_url`). `shop_calls` stands for the
shop's API calls that chapter 3 makes in `lib.shop_tools`; the listing doesn't show it.

Each rule in `RULES` names one dependency, how to find it in the source (`matches(node, source)` on an `ast` node),
its status at revision 2026-07-28 and its replacement, from the specification's changelog
(https://modelcontextprotocol.io/specification/2026-07-28/changelog) and its deprecated-features registry
(https://modelcontextprotocol.io/specification/2026-07-28/deprecated). `removal` is the registry's earliest removal:
the date a feature becomes eligible for removal, not the date it goes. Rules of kind "sdk" are SDK 1.x API that SDK
2.x renamed or moved (https://py.sdk.modelcontextprotocol.io/v2/migration/). One call can match two rules: a pushed
`create_message` is a removed mechanism, a request sent mid-call (https://modelcontextprotocol.io/specification/
2026-07-28/basic/patterns/mrtr), carrying a deprecated feature, sampling.
"""
from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

WRITTEN_FOR = "mcp==1.30.0"
REVISIONS = "2025-03-26 to 2025-11-25"

SERVER = '''\
"""shop-support as a 2025-era team wrote it, for SDK 1.x and revisions up to 2025-11-25."""
import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent
from pydantic import BaseModel

import shop_calls                                   # the shop's API, as chapter 3 calls it; not shown

server = FastMCP("shop-support", "Answers the support team's questions about orders, refunds and stock.",
                 port=8000, stateless_http=False)
quotes: dict[ServerSession, dict] = {}              # each connection's open quote


class Release(BaseModel):
    release: bool


@server.tool()
async def quote_refund(order_id: str, ctx: Context) -> dict:
    quotes[ctx.session] = quote = shop_calls.quote(order_id)
    await ctx.info(f"quoted {quote['amount']} for {order_id}")
    return quote


@server.tool()
async def issue_refund(ctx: Context) -> dict:
    quote = quotes.pop(ctx.session)                 # the quote this connection made last
    if not quote["within_limit"]:
        answer = await ctx.elicit(f"Refund {quote['amount']}? It is above the policy limit.", Release)
        if answer.action != "accept" or not answer.data.release:
            return shop_calls.hold(quote)
    return shop_calls.refund(quote)


@server.tool()
async def triage_ticket(text: str, ctx: Context) -> str:
    reply = await ctx.session.create_message(
        [SamplingMessage(role="user", content=TextContent(type="text", text=text))],
        max_tokens=20, system_prompt="Name the one shop tool this ticket needs.")
    return reply.content.text


@server.tool()
async def save_restock_report(ctx: Context) -> str:
    folder = (await ctx.session.list_roots()).roots[0].uri.path
    return shop_calls.write_restock_report(folder)


server.run(transport="sse" if os.environ.get("SHOP_OLD_HOSTS") else "streamable-http")   # HTTP+SSE: the 2024 transport
'''

HOST_AUTH = '''\
"""How the support team's 2025 host got tokens for shop-support: it registered itself with each authorization server."""
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

auth = OAuthClientProvider(
    server_url="https://mcp.fernhill.example/mcp",
    client_metadata=OAuthClientMetadata(client_name="Support desk", redirect_uris=["http://127.0.0.1:3030/callback"]),
    storage=token_store, redirect_handler=open_browser, callback_handler=wait_for_code,
)
'''

LISTINGS = {"server": SERVER, "host": HOST_AUTH}


@dataclass(frozen=True)
class Rule:
    feature: str
    kind: str                                   # "removed", "deprecated" or "sdk"
    replacement: str
    matches: Callable[[ast.AST], bool]
    removal: str = ""                           # the registry's earliest removal, for deprecated features


def _call(node: ast.AST, *names: str) -> bool:
    """A call whose function is one of `names`, as a bare name or the last part of an attribute."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)) in names


def _keyed_by_session(node: ast.AST) -> bool:
    """`quotes[ctx.session]`, `quotes.pop(ctx.session)`, `quotes.get(ctx.session)`: state kept per connection."""
    if isinstance(node, ast.Subscript):
        return ast.unparse(node.slice) == "ctx.session"
    return _call(node, "pop", "get") and bool(node.args) and ast.unparse(node.args[0]) == "ctx.session"


def _keyword(node: ast.AST, call: str, name: str, value=...) -> bool:
    return _call(node, call) and any(k.arg == name and (value is ... or getattr(k.value, "value", None) == value)
                                     for k in node.keywords)


AFTER_2027 = "first revision released on or after 2027-07-28"

RULES = [
    Rule("sessions", "removed", "a handle the server mints, passed back as a tool argument",
         lambda n: _keyed_by_session(n) or _keyword(n, "FastMCP", "stateless_http", False)),
    Rule("pushed requests", "removed", "an input request in a Multi Round-Trip Request",
         lambda n: _call(n, "elicit", "elicit_url", "create_message", "list_roots")),
    Rule("sampling", "deprecated", "a model call the host or the server makes itself",
         lambda n: _call(n, "create_message"), AFTER_2027),
    Rule("roots", "deprecated", "a tool parameter, a resource URI or server configuration",
         lambda n: _call(n, "list_roots"), AFTER_2027),
    Rule("logging", "deprecated", "stderr on stdio, or OpenTelemetry",
         lambda n: _call(n, "debug", "info", "warning", "error", "log") and isinstance(n.func, ast.Attribute)
         and ast.unparse(n.func.value) == "ctx",
         AFTER_2027),
    Rule("HTTP+SSE transport", "deprecated", "Streamable HTTP",
         lambda n: isinstance(n, ast.Constant) and n.value == "sse", "three months after SEP-2596 reaches Final"),
    Rule("dynamic client registration", "deprecated", "a Client ID Metadata Document",
         lambda n: _call(n, "OAuthClientProvider") and not any(k.arg == "client_metadata_url" for k in n.keywords),
         AFTER_2027),
    Rule("FastMCP", "sdk", "mcp.server.mcpserver.MCPServer",
         lambda n: isinstance(n, ast.ImportFrom) and n.module == "mcp.server.fastmcp"),
    Rule("positional instructions", "sdk", "instructions= by keyword",
         lambda n: _call(n, "FastMCP") and len(n.args) > 1),
    Rule("transport settings on the constructor", "sdk", "arguments to run() or streamable_http_app()",
         lambda n: _call(n, "FastMCP") and any(k.arg in {"host", "port", "stateless_http", "json_response"}
                                                for k in n.keywords)),
]
