---
chapter_id: migrate-from-2025
---

# Migrate a 2025-era server

By the end of this chapter you can move a Model Context Protocol server written for the 2025 revisions and the Python SDK's 1.x line to the specification at revision {{out:serve-two-revisions:auto revision}} and `mcp` {{version:mcp}}: find what it depends on, remove its sessions, move it off the HTTP+SSE transport, replace sampling, roots, logging and Dynamic Client Registration, port the code, and serve clients of both eras while the old ones are still around.

This book follows one case study throughout: a small online shop for kitchen and garden goods, which we call **the shop**, and whose support team answers customer tickets through a host. [Meet the shop and its API](#the-shop) introduces it. Every earlier chapter built the shop's server, `shop-support`, for the pinned revision from the start. Most teams don't start there. They have a server that a 2025-era team wrote against revisions 2025-03-26 to 2025-11-25 with SDK 1.x, and hosts that still speak those revisions. This chapter is the only one in the book that teaches the 2025 protocol, and it teaches it only as the thing you migrate from.

Between those revisions and the pinned one, the Model Context Protocol (MCP) removed the `initialize` handshake and protocol sessions, removed requests that a server pushes to the client in the middle of a call, and deprecated five features and two values of one sampling field ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). The shop's 2025-era server uses most of that. Here it is, as a team would have written it for `{{out:scan-a-2025-server:written for}}`:

```python
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
```

The listing is the 2025-era shop server, and a shared module for this chapter, `lib.legacy`, holds it as text with the host's OAuth setup and the rules for finding each dependency. It is shown and scanned, never run. SDK 1.x and SDK 2.x are both the `mcp` distribution, so one environment holds only one of them, and the examples' environment pins 2.x. Every example in the chapter runs the ported server on 2.x instead, or reads the listing. `shop_calls` stands for the calls to the shop's API that chapter 3's tools make; the listing doesn't show it.

## Inventory what the old server depends on {#inventory-2025-features}

A migration starts with a list, because the pinned revision treats the old features in three different ways, and each way sets a different deadline. Some were **removed** at revision 2026-07-28, with no window: the `initialize` handshake, protocol sessions and the `Mcp-Session-Id` header, requests a server sends to the client in the middle of a call, whatever they ask for, the HTTP GET stream, `resources/subscribe`, `ping`, `logging/setLevel` and stream resumability ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). A client at the pinned revision never uses them, so code that depends on them fails for that client the first time it runs.

Others are **deprecated**: roots, sampling, logging, the HTTP+SSE transport and Dynamic Client Registration. The changelog says that roots, sampling and logging stay "fully functional during the deprecation window" (same source), and the specification's registry gives each deprecated feature a migration path and an earliest removal ([deprecated features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)). The earliest removal is when a feature becomes eligible to go, not when it goes. Removal is a decision the core maintainers make when they prepare a revision, and a feature may stay deprecated for much longer ([feature lifecycle](https://modelcontextprotocol.io/community/feature-lifecycle)). The window is at least twelve months from the release of the revision that first marks the feature deprecated, and can be cut to ninety days for an active security risk, so the windows differ from feature to feature. Removal from the specification also doesn't oblige an SDK to drop the feature; each SDK's own policy decides that (same source).

The third kind isn't the protocol's at all. SDK 2.x renamed and moved parts of the 1.x API, so a 1.x server fails to start on 2.x even where the protocol didn't change ([migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)).

The example parses the server listing above and the host's OAuth setup, shown in [Replace dynamic client registration](#replace-dynamic-registration), with Python's `ast` module and matches each node against `lib.legacy.RULES`. Each rule names a dependency, its status at the pinned revision, its replacement and, for a deprecated feature, the registry's earliest removal. The example then prints them grouped by status, with the function each one sits in.

[Scan the 2025-era server for what the pinned revision removed or deprecated](../examples/scan-a-2025-server.py)

The scan found {{out:scan-a-2025-server:removed dependencies}} removed dependencies, {{out:scan-a-2025-server:deprecated dependencies}} deprecated ones and {{out:scan-a-2025-server:sdk dependencies}} SDK changes. The removed ones come first because they fail for every client at the pinned revision: the sessions that `quote_refund` and `issue_refund` share, and the requests that three tools push in the middle of a call, `ctx.elicit` in `issue_refund`, `create_message` in `triage_ticket` and `list_roots` in `save_restock_report`. So sampling and roots are on both lists. As features they are deprecated, and they still work through their window: for a 2025-era client as written, and for a client at the pinned revision only when the server asks for them through a round trip, as [Replace sampling, roots and logging](#replace-deprecated-features) shows. Pushed mid-call, they fail for that client as `ctx.elicit` does; SDK {{version:mcp}} raises `NoBackChannelError` (`mcp/server/_streamable_http_modern.py`). Of sampling, roots and logging, only logging works as written for a client at the pinned revision, and only for a request whose `_meta` asks for a log level; for any other request the SDK drops the line (`mcp/server/connection.py`). Four of the deprecated features share one earliest removal, the {{out:scan-a-2025-server:sampling earliest removal}}. The HTTP+SSE transport's is different: {{out:scan-a-2025-server:HTTP+SSE transport earliest removal}}. It had already been deprecated for more than a year when that proposal set the policy, so it got a three-month grace period instead of twelve months ([SEP-2596](https://modelcontextprotocol.io/seps/2596)). The proposal's page marks it Final without a date, so the transport may already be eligible.

The SDK at {{version:mcp}} doesn't warn about all of these either. Its sampling, roots and logging APIs emit `MCPDeprecationWarning`, a `UserWarning` that prints by default ([what's new](https://py.sdk.modelcontextprotocol.io/v2/whats-new/)). Its HTTP+SSE app and client and its registration code carry no deprecation marker: we searched `mcp/server/sse.py`, `mcp/client/sse.py`, `mcp/server/auth/handlers/register.py` and `mcp/client/auth/oauth2.py` for "deprecat" and found nothing. A server can run on 2.x without a single warning and still depend on two deprecated features.

**Working rule:** Inventory before you change anything, and sort the list by status. Fix every removed dependency before you let a client at the pinned revision connect, because there is no window for it, and count every request the server pushes mid-call as removed, even when the feature it asks for is only deprecated. Give each deprecated one a date of your own, earlier than the registry's earliest removal, and don't wait for warnings: run a scan like this one in CI, because the SDK is silent about some deprecated features.

## Remove initialize and session IDs {#remove-sessions}

The scan in [Inventory what the old server depends on](#inventory-2025-features) put sessions first. Under the 2025 revisions, a connection started with `initialize`, and a server on Streamable HTTP could assign a session ID in its answer. The client then had to send `Mcp-Session-Id` on every request, start a new session when the server answered 404, and end it with DELETE ([2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)). A server could keep anything it liked per session.

The pinned revision removes the handshake and the sessions. Each request carries its protocol version and the client's capabilities in `_meta`, a client asks what a server supports with `server/discover`, which every server MUST implement, and a server that needs state across calls mints an explicit handle and has the client pass it back as an ordinary tool argument ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). [Carry the version and capabilities on every request](#request-meta) shows the `_meta` keys.

The 2025-era shop server keeps one piece of state per session. `quote_refund` stores the quote under `ctx.session`, the SDK's object for the connection, and `issue_refund` takes no argument and refunds whatever quote that connection made last. On SDK 1.x the same object serves every request of one connection (`mcp/server/lowlevel/server.py` in 1.x), so this worked. The example ports those two tools to 2.x unchanged, around chapter 3's quote and refund functions, and calls them once each from one client at the pinned revision. Then it does the same with chapter 3's server, whose `quote_refund` returns a `quote_id` that `issue_refund` takes.

[Port the session-keyed quote unchanged, then use a quote handle](../examples/stateless-after-migration.py)

The unchanged port failed on the second call: "{{out:stateless-after-migration:session-keyed issue_refund}}" The two calls came from one client to one process, and they saw {{out:stateless-after-migration:session objects in two calls}} different session objects. At the pinned revision there is no connection for a session to belong to, so the SDK gives each request its own. Nothing failed when the quote was stored, and the bug shows only when something reads it back. A server that keyed its state on the `Mcp-Session-Id` header would fare worse: at the pinned revision no client sends one, so every client's state would land under the same key, `None`.

With the handle, the refund went through: {{out:stateless-after-migration:handle issue_refund}}. This is the design that [Shape tools around tasks, not endpoints](#tasks-not-endpoints) chose for chapter 3, and the specification's guidance for such handles is that they be opaque and expire, and that a server with authentication check the caller's authorization against the handle on every call ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)). [Keep the server from acting as a confused deputy](#confused-deputy) binds the shop's quote IDs to the customer they were issued for. A handle in one process's memory still dies with the process, so once the server runs as replicas the handles go in shared storage, as [Run replicas without sticky sessions](#scale-without-sessions) does with SQLite.

**Working rule:** Search the old server for every use of the session, its ID and anything stored per connection, and turn each piece of state into a handle that one tool returns and the next takes as an argument. Make the handle opaque, give it an expiry that the creating tool's description states, check on every call that the caller may use it, and store it where every replica can read it. Keep nothing a later call needs in a dictionary keyed by the session, even for 2025-era clients that still have one.

## Move from HTTP+SSE to Streamable HTTP {#move-off-http-sse}

The sessions in [Remove initialize and session IDs](#remove-sessions) belong to Streamable HTTP's 2025 form. The shop's 2025-era server also speaks an older transport: its last line serves the HTTP+SSE transport, the one revision 2025-03-26 replaced, when `SHOP_OLD_HOSTS` is set. In that transport the client keeps an event stream open at one endpoint and posts its messages to a second ([Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)); SDK 1.x serves the pair at `/sse` and `/messages/` (`mcp/server/fastmcp/server.py` in 1.x). Revision 2025-03-26 put Streamable HTTP in its place ([2025-03-26 changelog](https://modelcontextprotocol.io/specification/2025-03-26/changelog)), and the pinned revision brings it under the lifecycle policy, with a shorter window ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).

For the server, the move is a deletion. The ported shop server serves `streamable_http_app()`, or `run(transport="streamable-http")`, at one endpoint, as in [Move the server from stdio to HTTP](#stdio-to-http), and nothing in its tools changes. Every client at the pinned revision that connects over HTTP uses Streamable HTTP, so the transport isn't what blocks them. What decides when the old transport can go is the hosts that still connect over HTTP+SSE, and they are 2025-era clients by definition.

Those hosts have two ways forward. A server that must keep them can host the old SSE and POST endpoints alongside its Streamable HTTP endpoint, which the specification has allowed since revision 2025-03-26 ([Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)). SDK {{version:mcp}} still has `MCPServer.sse_app()`, with the same two paths as 1.x, and `run(transport="sse")` (`mcp/server/mcpserver/server.py`), and as [Inventory what the old server depends on](#inventory-2025-features) found, neither raises a deprecation warning. Or the hosts move to Streamable HTTP, which SDK 1.x's client already speaks (`mcp/client/streamable_http.py` in 1.x).

The registry's earliest removal for HTTP+SSE is {{out:scan-a-2025-server:HTTP+SSE transport earliest removal}}, which may already have passed. That doesn't mean the SDK drops `sse_app()` on that day, since each SDK decides for itself ([feature lifecycle](https://modelcontextprotocol.io/community/feature-lifecycle)). It means a host can't count on the transport surviving the next revision, and neither can you.

The shop's support team chose a date. The old endpoints stay only as long as the server's logs show a host connecting to `/sse`, and the team tells each such host's owner the date when the endpoints go. A host that can't move by then can stay on SDK 1.x against a 1.x deployment of the old server, which [Port the code from SDK 1.x to 2.x](#sdk-1-to-2) covers.

**Working rule:** Delete the HTTP+SSE transport from the server rather than port it, unless your logs show hosts that still use it. If they do, serve the old endpoints beside the Streamable HTTP endpoint, log every connection to them by client, and set a date for removing them that you tell each host's owner. Treat the transport as already eligible for removal, because its window was three months, not twelve.

## Replace sampling, roots and logging {#replace-deprecated-features}

Three of the dependencies that [Inventory what the old server depends on](#inventory-2025-features) found have two changes stacked on them, and it pays to keep them apart. The first is a mechanism. A 2025 server sent its own request to the client in the middle of a call (`elicitation/create`, `sampling/createMessage`, `roots/list`) and waited for the answer. The pinned revision says that pattern "is no longer supported" and that this is a breaking change: a server asks through a Multi Round-Trip Request instead, returning an input request whose values may be an `ElicitRequest`, a `CreateMessageRequest` or a `ListRootsRequest` ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)). The second is the features themselves. Roots, sampling and logging are deprecated, with migration paths in the registry: roots to tool parameters, resource URIs or server configuration; sampling to integrating with a model provider's API directly; logging to stderr on stdio, or OpenTelemetry ([deprecated features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)).

So a Multi Round-Trip Request replaces the push, not sampling. A server that moves its `sampling/createMessage` into an input request still depends on a deprecated feature. Elicitation is the one of the three that isn't deprecated, so it is the only one worth moving into the round trip and keeping.

The 2025-era `issue_refund` pushes its confirmation with `ctx.elicit`, which fails at the pinned revision, as [See why a stateless server can't wait for an answer](#why-calls-cannot-wait) showed. The port asks with a resolver: a parameter declared `Annotated[Release, Resolve(confirm)]` is filled by running `confirm` before the tool, and when `confirm` returns `Elicit(...)`, the SDK asks the person at the host ([Ask for structured input with elicitation](#elicitation-forms)). `confirm` asks only when the shop's API holds the refund for confirmation. The example quotes order O-2289, whose refund is above the policy's limit, calls `issue_refund` once by hand to see the first round, and then lets `Client` run the rounds with the scripted lead from chapter 5, who says yes.

[Ask for the confirmation with a resolver, and log to stderr](../examples/replace-pushed-requests.py)

The first round returned `{{out:replace-pushed-requests:first round}}` with one question, `{{out:replace-pushed-requests:first round asks}}`: the same request the 2025 server pushed, carried in a result instead. After the lead's yes, the refund's status was {{out:replace-pushed-requests:refund after the lead's yes}}. The resolver also works for 2025-era clients, because the SDK sends its questions in whichever form the client's revision uses (`mcp/server/mcpserver/resolve.py`); [Serve old and new clients through the window](#serve-both-revisions) runs both.

The port's log line uses Python's `logging`, not `ctx.info`. `MCPServer` configures logging to stderr when it is built (`mcp/server/mcpserver/utilities/logging.py`), so the line goes to the server's own logs and never to the client. On stdio, stdout carries only the protocol's messages, and stderr is where a server's logs belong ([stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio.md)). [Trace calls with OpenTelemetry](#trace-with-opentelemetry) covers the other path.

The 2025-era `triage_ticket` asked the host's model, through sampling, which tool a ticket needs. The port deletes it. The host's own model already reads every ticket and picks the tools ([Work through the ticket queue](#work-the-queue)), so the server was asking the host to do what the host does anyway. A server that needs a model for its own work calls a model provider with its own credentials, which also lets it choose and pay for the model.

`save_restock_report` asked the client for its roots and wrote to the first one. Its port takes the folder as a parameter and checks it against the folders the server's configuration allows, in `SHOP_EXPORT_DIRS`, after resolving the path, so that `..` can't climb out.

[Take the export folder as a parameter, and check it](../examples/roots-to-a-parameter.py)

The allowed folder worked: "{{out:roots-to-a-parameter:export to exports}}" The path that climbs out did not: "{{out:roots-to-a-parameter:export to exports/../private}}" The host or the model now passes the folder, and the server, not the client, decides where it may write.

**Working rule:** Move every pushed elicitation into a resolver, which serves both eras. Delete sampling rather than move it: let the host's model do model work, or call a provider from the server with the server's own credentials. Turn roots into a parameter checked against an allow-list in the server's configuration, and send log lines to stderr and your traces, never to the client.

## Replace dynamic client registration {#replace-dynamic-registration}

The last deprecated dependency that [the inventory](#inventory-2025-features) found is in the host, not the server, but it decides whether the support team's host can get a token for the ported server at all. The 2025 host registered itself with each authorization server it met, through OAuth Dynamic Client Registration:

```python
"""How the support team's 2025 host got tokens for shop-support: it registered itself with each authorization server."""
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata

auth = OAuthClientProvider(
    server_url="https://mcp.fernhill.example/mcp",
    client_metadata=OAuthClientMetadata(client_name="Support desk", redirect_uris=["http://127.0.0.1:3030/callback"]),
    storage=token_store, redirect_handler=open_browser, callback_handler=wait_for_code,
)
```

SDK 1.x's `OAuthClientProvider` registers this way when it isn't given a `client_metadata_url` (`mcp/client/auth/oauth2.py` in 1.x). The pinned revision deprecates Dynamic Client Registration in favour of Client ID Metadata Documents, which revision 2025-11-25 had already recommended, and keeps it for backward compatibility ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog); [2025-11-25 changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)). Its earliest removal is the {{out:scan-a-2025-server:dynamic client registration earliest removal}}.

A Client ID Metadata Document makes the client ID an `https://` URL where the host publishes its own metadata, so no authorization server has to register it first. [Identify the client with a metadata document](#client-id-metadata-documents) builds one for the shop's host and shows the order the pinned revision ranks the options in: pre-registered credentials, then a metadata document, then registration.

The port is one argument. The host passes its document's URL as `client_metadata_url`, and SDK 2.x's `OAuthClientProvider` then uses the document when the authorization server advertises `client_id_metadata_document_supported`. When the server doesn't, the provider falls back to registration without saying so, as chapter 8's example showed, and the SDK's registration code at {{version:mcp}} raises no deprecation warning. So the authorization server is half of the port. It has to advertise metadata document support, and it should keep its registration endpoint only for the window and only for hosts that can't publish a document.

Two rules from the pinned revision matter while registration lingers. A client MUST key the credentials it stores by the authorization server's issuer and register again when the authorization server changes, and a client that registers MUST send an appropriate `application_type`, which SHOULD be `native` for a host that runs on the user's machine with a loopback redirect, like this one ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog); [client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)). A 2025 host that stored one client ID per MCP server's URL breaks the first rule the day the shop moves its authorization server.

**Working rule:** Publish a Client ID Metadata Document for every host and pass its URL as `client_metadata_url`. Make every authorization server you run advertise support for it, keep its registration endpoint only until the hosts that need it have moved, and log which kind of client ID each token was issued to, so that you can see when registration traffic has stopped.

## Port the code from SDK 1.x to 2.x {#sdk-1-to-2}

The sections so far changed what the shop's server does. The scan in [Inventory what the old server depends on](#inventory-2025-features) also found SDK changes, which stop the old file from starting on 2.x at all. They are a separate job, and two facts shape it. The 1.x line is still maintained. The first 2.x release and a 1.x release both shipped on 2026-07-28, the day of the pinned revision, and the 1.x release on 2026-09-07, `{{out:scan-a-2025-server:written for}}`, is a "maintenance release of the 1.x line" ([PyPI](https://pypi.org/pypi/mcp/json); [release notes](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)). The migration guide says the 1.x line keeps receiving critical bug fixes and security patches, and nobody has published an end date ([migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)). And both lines are the one `mcp` distribution, so a deployment runs one or the other, never both.

The guide lists the breaks. Those that touch a server like the shop's: `mcp.server.fastmcp.FastMCP` is `mcp.server.mcpserver.MCPServer`; `McpError` is `MCPError(code, message, data)`; fields are snake_case (`input_schema`, `is_error`); the HTTP client is `httpx2`, not `httpx`; `streamablehttp_client` is gone, in favour of `streamable_http_client`; `host`, `port`, `stateless_http` and `json_response` moved from the constructor to `run()` and `streamable_http_app()`; `instructions` is no longer the second positional argument; `MCP_*` environment variables are no longer read; the WebSocket transport is removed; and `ctx.log` takes `data`, not `message` ([migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/)).

Most of these fail loudly, which is the kind you want. One doesn't. The example tries the 2025-era server's setup lines on {{version:mcp}}: the import, the exception it raised, and the constructor. Then it builds the server twice, once with the arguments as written and once ported, and asks each what a client sees.

[Try the 2025-era setup lines on SDK 2.x, then port them](../examples/port-to-sdk-2.py)

The import failed with a message that names the rename and the import to use instead: "{{out:port-to-sdk-2:import FastMCP}}" (`mcp/server/fastmcp.py`, which exists only to raise it). `McpError` failed with "{{out:port-to-sdk-2:import McpError}}", and the constructor with "{{out:port-to-sdk-2:port on the constructor}}". Each points at the line to change.

The constructor as written didn't fail. In 2.x the second positional argument is `title` (`mcp/server/mcpserver/server.py`), so the server's instructions became its title: a client saw the title "{{out:port-to-sdk-2:as written title}}" and no instructions (`{{out:port-to-sdk-2:as written instructions}}`). A host that puts a server's instructions in the model's context would silently lose them. With `instructions=` by keyword, the ported server's title is {{out:port-to-sdk-2:ported title}} and its instructions arrive. The port number moves to the last line, as `server.run(transport="streamable-http", port=8000)`.

The silent breaks share a shape: an argument that still type-checks, or a setting that is no longer read, like the `MCP_*` environment variables. Find them by reading the guide's list against the code, not by waiting for errors, and check what a client sees with a test like this one.

**Working rule:** Keep a 2025-era server pinned to `mcp<2` until its port passes its tests, then port in one change: the imports and renames the errors point at, then each silent break from the migration guide, checked with a test against what a client sees. Pin the 2.x release exactly afterwards, and treat each 2.x release as a change to test, since the SDK's warnings and defaults move between releases.

## Serve old and new clients through the window {#serve-both-revisions}

The ported server from [Replace sampling, roots and logging](#replace-deprecated-features) answers clients at the pinned revision. The support team's hosts don't all move on the same day, and a 2025-era host has no way to move forward on its own: it sends `initialize` and expects an answer. The pinned revision allows a **dual-era** server, which serves both on the same endpoint. An `initialize` request selects the 2025 semantics for that process on stdio or that session on HTTP, and a request with the pinned revision's `_meta` is served statelessly. A server that serves only the pinned revision SHOULD name the versions it supports in its error to `initialize`, because a 2025 client can't discover them any other way ([versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md)). On the other side, a 2.x `Client` in its default mode tries `server/discover` first and falls back to `initialize` (`mcp/client/_probe.py`; [Call the tool from a client](#call-a-tool-from-a-client)).

At {{version:mcp}}, `MCPServer.streamable_http_app()` is dual-era with nothing to configure. It reads each request's `MCP-Protocol-Version` header: a request with no header, or with a version from 2024-11-05 to 2025-11-25, goes to the 2025 handler with its sessions, and anything else goes to the stateless handler (`mcp/server/streamable_http_manager.py`). The 2025 path keeps its sessions in the memory of the process that made them, so 2025-era clients keep their stickiness requirements ([what's new](https://py.sdk.modelcontextprotocol.io/v2/whats-new/)).

The example serves the ported server's app as replica a, recorded with chapter 6's `lib.wire.record_http`, and a second copy of it as replica b. A client in the default mode and a client in `mode="legacy"`, which speaks the 2025 handshake, each quote a refund above the policy's limit and issue it on replica a, with the scripted lead saying yes. Then the example sends the 2025 client's session ID to each replica.

[Serve one app to a 2026 client and a 2025 client, then move the 2025 session](../examples/serve-two-revisions.py)

The default client settled on {{out:serve-two-revisions:auto revision}}, got no session header ({{out:serve-two-revisions:auto session header}}), and its question came as {{out:serve-two-revisions:auto question came as}}. The 2025 client settled on {{out:serve-two-revisions:legacy revision}}, got a session header ({{out:serve-two-revisions:legacy session header}}), and its question came as {{out:serve-two-revisions:legacy question came as}}. The default client's refund ended {{out:serve-two-revisions:auto refund}}, and so did the 2025 client's ({{out:serve-two-revisions:legacy refund}}). One resolver served both eras, and no code in `issue_refund` checks which one it is in, which is simpler than the check of `ctx.protocol_version` around `ctx.elicit()` that [See why a stateless server can't wait for an answer](#why-calls-cannot-wait) allows. A hand-built input request, like chapter 5's, doesn't do that: a 2025 client receives it as an invalid result ([What goes wrong in production](#multi-round-trip-requests-in-production) in chapter 5).

The 2025 session worked on replica a, which answered {{out:serve-two-revisions:2025 session on replica a}}, and failed on replica b, which answered {{out:serve-two-revisions:2025 session on replica b}}. A 2026 client has no session to lose; what it needs from replicas is handles they all reach, as [Run replicas without sticky sessions](#scale-without-sessions) showed. Behind a load balancer, then, 2025-era traffic needs routing by `Mcp-Session-Id` to the replica that made the session, while the rest goes anywhere. The SDK's other choice, `stateless_http=True`, removes the sessions for 2025 clients but takes away their cancellation and their server-to-client requests ([What goes wrong in production](#streamable-http-in-production) in chapter 6). For the shop that would break the pushed confirmation that the 2025 client had answered, so we recommend sticky routing for the 2025 path, kept as small as the remaining clients allow.

**Working rule:** Serve both eras from one `streamable_http_app()` through the window, write every question a tool asks as a resolver, and route requests that carry `Mcp-Session-Id` to the replica that minted it. Count requests by era. When the 2025 count has stayed at zero for as long as your slowest host takes to upgrade, serve the pinned revision only, and answer `initialize` with an error that names the versions you support, as the specification asks.

## What goes wrong in production {#migrate-from-2025-in-production}

A migration fails in the gaps between the two eras: one client sees the old server, a proxy sees the new one, a warning says nothing. These are the failures to watch for.

**A 2025 session lands on another replica.** The sign is `404` with "Session not found" from 2025-era clients only, after a deployment or a scale-out, as on replica b in [Serve old and new clients through the window](#serve-both-revisions). A 2025 client that follows its revision starts a new session on 404 ([2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)), so the symptom may be lost state rather than an error. Route by `Mcp-Session-Id`, and count 404s by client.

**A proxy drops the version header.** The SDK's app picks the era from `MCP-Protocol-Version` alone, and its source marks routing by the body as a later step (`mcp/server/streamable_http_manager.py`). A proxy that strips headers it doesn't know sends a 2026-era request down the 2025 path, which expects a handshake first. The sign is failures from clients at the pinned revision behind that proxy only. Make every proxy pass the MCP headers, as [Read one HTTP exchange](#http-on-the-wire) lists them.

**Error codes moved.** A missing resource is `-32602` at the pinned revision, not `-32002`, though clients SHOULD still accept `-32002` ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)). The revision adds `-32020` for headers that disagree with the body, `-32021` for a missing client capability and `-32022` for an unsupported protocol version ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). A host that branches on the old codes treats the codes the pinned revision added as unknown ones. Search client code for each numeric code before the server moves.

**Warnings that teach people to ignore warnings.** `MCPDeprecationWarning` is a `UserWarning`, so it prints by default ([what's new](https://py.sdk.modelcontextprotocol.io/v2/whats-new/)), and a server that still uses sampling, roots or logging writes it into its logs. Turned off wholesale, it also hides the next deprecation. Filter each warning by its message only once the feature is on your inventory with a date.

**Silence about HTTP+SSE and registration.** The SDK at {{version:mcp}} warns about neither, as the inventory found. A server can pass its tests with no warnings and still lose its oldest hosts when the transport goes. Keep the scan from [Inventory what the old server depends on](#inventory-2025-features) in CI, and treat a later SDK release that adds these warnings as a reason to recheck the dates.

**Reading the earliest removal as the end date.** A team that plans to move off sampling or roots on 2027-07-28 has no margin, because the first revision released on or after that date may remove them. A team that reads the date as the day they disappear may also drop a feature its SDK keeps supporting for longer. Plan by the clients you serve: the registry gives the earliest date, and your logs give the real one.

**Working rule:** Before the ported server takes traffic, test four things through the real proxy path: a 2025 client completes a confirmation, a 2026 client completes the same one, a 2025 session survives a deployment, and the version header reaches the server. Then watch requests by era, 404s by client and every deprecation warning, until the 2025 count reaches zero.

## Decisions this chapter made {#migrate-from-2025-decisions}

- **The 2025-era server is a listing, not a running example.** `lib.legacy` holds it as text for SDK 1.x, and the examples run only the port on 2.x, because one environment can't hold both lines.
- **The inventory sorts dependencies into removed, deprecated and SDK changes,** with the registry's earliest removal for each deprecated feature, read as the earliest date, never an end date.
- **The scan runs in CI through the window,** because the SDK warns about sampling, roots and logging but not about HTTP+SSE or registration.
- **Per-session state becomes handles:** the quote is chapter 3's `quote_id`, passed back by the client, and stored where every replica reads it.
- **HTTP+SSE goes.** The shop's server serves Streamable HTTP only, and keeps the old endpoints only while its logs show a host using them.
- **Elicitation moves into a resolver,** which serves both eras. Sampling is deleted: the host's model triages tickets. Roots become the `export_dir` parameter, checked against `SHOP_EXPORT_DIRS`. Logging goes to stderr and traces.
- **The host uses a Client ID Metadata Document** through `client_metadata_url`, and authorization servers keep registration only for hosts that can't publish one.
- **The port to 2.x is one change,** behind `mcp<2` until its tests pass, with `instructions=` by keyword and transport settings on `run()`.
- **One dual-era app serves both eras** through the window, with sticky routing by `Mcp-Session-Id` for 2025 traffic and no `stateless_http`.
