---
chapter_id: streamable-http
---

# Serve over Streamable HTTP

By the end of this chapter you can serve the shop's Model Context Protocol server over Streamable HTTP, read what each request and response carries, stream progress from a long call and cancel it, run the server as replicas behind one address with no sticky sessions, and refuse requests that a browser was tricked into sending. Each claim here holds at revision {{out:serve-on-loopback:protocol revision}} of the specification and at version {{version:mcp}} of the Python SDK, `mcp`.

Until this chapter, every host launched `shop-support`, the server for **the shop** ([a kitchen-and-garden retailer that sells online](#the-shop)), as a subprocess and talked to it over stdio, which works for one person on one machine. The support team answers the shop's tickets through a host, and now has many hosts. The server has to reach the shop's API from inside the shop's network. And the team wants a slow job on the server: `recount_stock`, which recounts every product in both warehouses and takes minutes in the real shop. A subprocess per host can't be shared, scaled or watched from one place.

The Model Context Protocol (MCP) defines a second transport for this, **Streamable HTTP**. The server listens at one HTTP endpoint, and each message a client sends is a POST of its own, as the specification's [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) describes. The rest of MCP stays as it is: the JSON-RPC messages, the `_meta` on every request and the same tools.

Four small shared modules in `examples/lib/` carry this chapter's setup, so each example shows only its idea:

- `lib.http_mcp` starts a server example as its own process on a free loopback port, sends hand-written requests with the headers the pinned revision asks for, and loads the server object an earlier example defines.
- `lib.wire`, the trace printer from [Read the messages on the wire](#read-the-messages), gains `record_http`, which wraps a server's HTTP app and logs each exchange: headers, body, status and every message in the response.
- `lib.recount` holds the shop's recount, its SKUs and one API call per product.
- `lib.shared_state` keeps state in one SQLite file that several server processes open, for the replicas in [Run replicas without sticky sessions](#scale-without-sessions).

Most examples serve the server's HTTP app in their own process, through [`lib.loopback`](#the-shop), chapter 1's helper for an app on a free loopback port, so the recorder sees the server side. The first and replicas examples are the exceptions, running the server as separate processes, as a deployment does. Everything binds to 127.0.0.1.

## Move the server from stdio to HTTP {#stdio-to-http}

A server on stdio has exactly one client, the host that launched it. A server on Streamable HTTP has an address, and any client that can reach that address can use it. At the pinned revision that costs the server little, because the protocol keeps no state between requests. The [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog) records that the revision removed the `initialize` handshake and the `Mcp-Session-Id` header, and that each request carries its own protocol version and client capabilities in `_meta`. A request over HTTP is therefore self-contained, like a call to the shop's own API: one POST in, one response out.

A server answers each request in one of two forms: a single JSON object (`Content-Type: application/json`), or a Server-Sent Events stream (`text/event-stream`) that belongs to that one request. The client must accept both, as the transport specification says. The stream exists so that the server can send notifications, such as progress, before the result, which [Stream progress on a long call](#stream-progress) relies on.

In the Python SDK the change is one argument. `MCPServer.run(transport="streamable-http")` serves the server under uvicorn, by default on 127.0.0.1, port 8000, at the path `/mcp` (`mcp/server/mcpserver/server.py`). On the client side, `Client` takes a URL where it took `StdioServerParameters`, and connects with the SDK's Streamable HTTP client (`mcp/client/client.py`). The shop's server keeps chapter 3's five tools unchanged, and only the last lines of its file change. The port comes from `http_mcp.port()`, not 8000, so it never collides with anything else.

[Serve the shop's tools over Streamable HTTP](../examples/serve-on-loopback.py)

The client reached the server at the SDK's defaults, `{{out:serve-on-loopback:endpoint host}}` at `{{out:serve-on-loopback:endpoint path}}`.

It settled on revision {{out:serve-on-loopback:protocol revision}} and found {{out:serve-on-loopback:tools}} tools on `{{out:serve-on-loopback:server}}`. Order O-1873 came back {{out:serve-on-loopback:O-1873 status}}, as it does over stdio. The server process got the shop's API address and key in its environment, as the stdio servers did, and nothing else changed.

The SDK's `streamable_http_app()` also takes a `stateless_http` flag, At {{version:mcp}}, the app routes each request by its `MCP-Protocol-Version` header, and a request at the pinned revision goes to a handler that serves one exchange and never sets `Mcp-Session-Id`, whatever the flag says. The flag only changes how clients on a 2025 revision are served (`mcp/server/streamable_http_manager.py`). The older HTTP+SSE transport, with its separate event endpoint, has been deprecated since revision 2025-03-26. Its earliest removal is three months after the specification's feature-lifecycle proposal, SEP-2596, reaches Final ([deprecated features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)). [Move from HTTP+SSE to Streamable HTTP](#move-off-http-sse) ports a server off it.

**Working rule:** Serve over Streamable HTTP with `MCPServer.run(transport="streamable-http")` and its loopback default while you develop, and give clients the endpoint's URL. Leave `stateless_http` alone unless you also serve clients on a 2025 revision, where it decides whether they get sessions. Keep stdio for servers that a host launches for one user, as [Choose stdio or Streamable HTTP](#stdio-or-http) explains.

## Read one HTTP exchange {#http-on-the-wire}

The client in [Move the server from stdio to HTTP](#stdio-to-http) hid all of this, but when a call fails behind a proxy or a gateway, the exchange is what you read, so it pays to know what a correct one looks like. At the pinned revision, every POST carries headers that copy parts of its body. `MCP-Protocol-Version` repeats the version, `Mcp-Method` the JSON-RPC method, and `Mcp-Name` the tool, prompt or resource for `tools/call`, `prompts/get` and `resources/read`. The copies exist so that load balancers, gateways and monitoring can route and inspect a request without parsing its body, as the specification's [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) explains.

The body stays the source of truth. A server MUST reject a request whose headers disagree with its body, with `400 Bad Request` and the JSON-RPC error -32020, `HeaderMismatch`. That rule is what makes the headers safe to route on. A gateway that sends `Mcp-Name: check_stock` to the stock replicas can trust that the body names `check_stock` too, because a server would refuse the request otherwise.

Recording one `get_order_status` call with the SDK's client shows a correct exchange. Two requests the SDK's client never sends, through `lib.http_mcp.post`, show what the server refuses: a `tools/call` whose `Mcp-Name` says `check_stock` while its body names `get_order_status`, and a GET.

[Record one tool call over HTTP, then break the rules twice](../examples/trace-an-http-exchange.py)

The client made three POSTs for that one call: {{out:trace-an-http-exchange:POSTs}}. The first asks the server what it supports, since there is no handshake. The last is the SDK's client fetching the tool list after the call, so that it can check the structured result against the tool's output schema (`mcp/client/session.py`, `validate_tool_result`). The `tools/call` POST carried:

- `MCP-Protocol-Version: {{out:trace-an-http-exchange:request mcp-protocol-version}}`
- `Mcp-Method: {{out:trace-an-http-exchange:request mcp-method}}`
- `Mcp-Name: {{out:trace-an-http-exchange:request mcp-name}}`
- `Accept: {{out:trace-an-http-exchange:request accept}}`, because the client must take either form of response

Its body's `_meta` held the same three keys that it holds over stdio: {{out:trace-an-http-exchange:request _meta keys}}. The response came back {{out:trace-an-http-exchange:response status}} as `{{out:trace-an-http-exchange:response content-type}}`, and it set no session header (`mcp-session-id`: {{out:trace-an-http-exchange:response mcp-session-id}}).

The response was plain JSON because the tool sent nothing before its result. The SDK doesn't commit to an event stream until the handler sends a notification or 15 seconds pass, so a handler that finishes silently inside that window gets a JSON response (`mcp/server/_streamable_http_modern.py`). That 15-second limit belongs to a detail of that private module and may change between releases.

The server refused the mismatched request before the tool ran, with {{out:trace-an-http-exchange:mismatched Mcp-Name status}} and error {{out:trace-an-http-exchange:mismatched Mcp-Name error}}. The SDK's own client recovers from -32020 by fetching the tool list again and resending once, because at the pinned revision a tool can mark parameters with `x-mcp-header`, which clients copy into `Mcp-Param-{Name}` headers, and a stale listing gets those headers wrong (`mcp/client/client.py`, `call_tool`).

The GET was refused too: {{out:trace-an-http-exchange:GET status}}, with `Allow: {{out:trace-an-http-exchange:GET allow}}`. A server that supports only the pinned revision SHOULD answer GET and DELETE with `405 Method Not Allowed`, because that revision has no stream a client opens with GET ([the transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)). The SDK's app also serves the 2025 revisions, and sends a GET without the pinned version in `MCP-Protocol-Version` to its 2025 handler, which serves it and refuses only a GET marked with the pinned revision, as this one was (`mcp/server/streamable_http_manager.py`).

**Working rule:** When an HTTP call fails, read the exchange first: the three routing headers, `_meta` in the body, the status and the content type. Route in a gateway on `Mcp-Method` and `Mcp-Name` if you need to, and never rewrite a body without rewriting its headers to match, because the server will refuse the pair with -32020. On a server that supports only the pinned revision, a 405 means an older client is opening a GET stream; the SDK's app serves those clients instead.

## Stream progress on a long call {#stream-progress}

The exchange in [Read one HTTP exchange](#http-on-the-wire) returned in milliseconds. A call that takes minutes leaves the person at the host seeing nothing, and the host can't tell slow from stuck. **Progress** is MCP's answer. A client that wants progress puts a `progressToken` in the request's `_meta`. The server MAY then send `notifications/progress` with that token, each carrying a `progress` value that MUST increase with every notification, and optionally a `total` and a `message` ([progress](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress)). Over Streamable HTTP, these notifications travel only on the response stream of the request they belong to ([Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)).

In the SDK, a tool reports with `await ctx.report_progress(progress, total=..., message=...)`. A client asks for reports on a call with `call_tool(..., progress_callback=...)`, which also puts the token in `_meta`. When the caller didn't ask, `report_progress` does nothing (`mcp/server/_streamable_http_modern.py`, `progress`), so a tool can always call it.

The shop's API has an endpoint, `POST /stock/{sku}/recount`, which recounts one product in both warehouses and takes a few seconds per product in the real shop. `recount_stock` calls it for each of the shop's {{out:start-the-shop-api:products}} SKUs and reports after each one. In the examples, `lib.recount` asks the API to take 0.02 seconds per product, so a full recount takes a few seconds. The same server runs twice: once with the SDK's default, which can stream, and once with `json_response=True`, which makes every response a single JSON object.

[Report progress from recount_stock, then turn streaming off](../examples/progress-on-stock-recount.py)

With the default, the host saw the recount move. The response came back as `{{out:progress-on-stock-recount:sse content-type}}`, and the client received {{out:progress-on-stock-recount:sse progress reports}} reports, the last of them {{out:progress-on-stock-recount:sse last report}}. The first progress notification is what committed the response to an event stream, so nobody had to wait out the SDK's 15-second window. The recount counted {{out:progress-on-stock-recount:sse units counted}} units.

With `json_response=True`, the host got nothing until the end. The response was `{{out:progress-on-stock-recount:json content-type}}`, and the client received {{out:progress-on-stock-recount:json progress reports}} reports. The recount still ran and counted {{out:progress-on-stock-recount:json units counted}} units, and nothing failed. The SDK's JSON path has nowhere to send a notification, so `report_progress` returns without sending, and neither side logs it (`mcp/server/_streamable_http_modern.py`). The specification allows that, because progress is optional for the server. The person at the host would have waited the whole recount with no sign of life.

Streaming also has to survive intermediaries, since a proxy that buffers responses holds progress back until the end. The [transport specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) says servers SHOULD send `X-Accel-Buffering: no` on event streams to stop that, and the SDK sends it, with `Cache-Control: no-cache, no-transform` (`mcp/server/_streamable_http_modern.py`, `_SSE_HEADERS`).

**Working rule:** Report progress from any tool that can run longer than a few seconds, with a `total` when you know it and a message a person can read. Keep the SDK's default response mode. Use `json_response=True` only for a server whose every tool is quick, and know that it drops every progress report and every cancellation without telling anyone.

## Cancel a call the client no longer needs {#cancel-a-call}

The recount in [Stream progress on a long call](#stream-progress) ran to the end because the client waited for it. Often, though, the host stops needing the answer partway through: the person closes the ticket, or the host's own deadline passes. A call that keeps running after that wastes the shop's API and holds whatever the tool holds.

On Streamable HTTP, a client cancels a request by closing that request's response stream. The [cancellation](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/cancellation) pattern in the specification calls the closed stream "the cancellation signal", says the server MUST treat a client disconnect as cancelling that request, and says no `notifications/cancelled` message is "required or expected". That differs from stdio, where a client still sends `notifications/cancelled`, and from the 2025 revisions, where HTTP clients sent it too. The SDK implements both halves. Its client aborts the POST when the awaiting task is cancelled or its read timeout passes, and sends nothing else (`mcp/client/streamable_http.py`). Its server watches for the disconnect and cancels the task that runs the handler (`mcp/server/_streamable_http_modern.py`, `watch_disconnect`).

Inside an `async def` tool, cancellation arrives as anyio's cancellation exception at the next `await`. The tool may record where it stopped, but it must re-raise. Cleanup that has to await something needs a shielded scope, such as `anyio.move_on_after(5, shield=True)`, or the cancellation cancels the cleanup too. A plain `def` tool runs in a worker thread and stops only if it calls `anyio.from_thread.check_cancelled()`. One that never calls it runs to the end, and its result is thrown away. The [SDK's cancellation guide](https://py.sdk.modelcontextprotocol.io/v2/handlers/cancellation/) and `mcp/server/_streamable_http_modern.py` (`watch_disconnect`) describe both cases.

To watch that path end to end, the host cancels the call at the fifth progress report, the way a host would when its person closes the ticket. Each product takes 0.1 seconds here, so the server is still inside the sixth product's recount when the stream closes. `recount_stock` records how each run ended, and the recorder logs what crossed the wire.

[Cancel the recount after five reports](../examples/cancel-the-stock-recount.py)

The tool stopped when the stream closed. The server saw the call {{out:cancel-the-stock-recount:server saw}}, and the tool had asked the shop's API for {{out:cancel-the-stock-recount:recounts asked of the API}} recounts. Cancellation reached the tool while it waited for the sixth, so the remaining products never went to the API.

On the wire there were two POSTs, {{out:cancel-the-stock-recount:POSTs}}, so no cancellation message crossed it. The tool call's stream was {{out:cancel-the-stock-recount:tools/call stream}}, and it carried {{out:cancel-the-stock-recount:tools/call messages}}. The client gets no result for a cancelled call, and the server sends none.

Two things undo this. With `json_response=True`, the SDK's JSON path has no disconnect watcher, so a closed connection never reaches the handler, and the handler runs to the end (`mcp/server/_streamable_http_modern.py`). And a stream that breaks for any other reason, such as a proxy timing it out, cancels the request in the same way. Streams can't be resumed at the pinned revision, so the client MUST send the request again with a new request ID ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). A tool that a broken stream can interrupt must be safe to run twice, and the recount is, because counting again gives the same count. For a recount that must survive the client going away, [Start a task instead of waiting](#start-a-task) moves it into a task.

Timeouts sit on top of cancellation. The [cancellation](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/cancellation) pattern says a sender SHOULD set a timeout for each request, MAY reset it when progress arrives, and SHOULD always enforce a maximum. `Client(read_timeout_seconds=...)`, and the same argument on `call_tool`, give that limit, and running out of time cancels the call by closing its stream (`mcp/client/streamable_http.py`).

**Working rule:** Cancel a call over Streamable HTTP by cancelling the task that awaits it, or with a timeout, and let the SDK close the stream. Write long tools as `async def`, re-raise cancellation, and put any awaited cleanup under a shielded scope. Make every tool that runs for long safe to retry, because a broken stream loses the call and the client sends it again.

## Run replicas without sticky sessions {#scale-without-sessions}

Every example so far, including the cancelled recount in [Cancel a call the client no longer needs](#cancel-a-call), ran one server process. The support team needs more than one, so that a restart or a slow recount doesn't stop every host. A load balancer in front of two replicas sends each request wherever it likes. With 2025-era sessions, that required **sticky sessions**, which route every request carrying the same `Mcp-Session-Id` to the replica that held the session. The pinned revision has no sessions, so any replica can serve any request. A server that needs state across calls mints an explicit handle instead, and the client passes it back as an ordinary argument ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).

The protocol keeping no state doesn't mean the application keeps none. The shop's server holds three kinds of state that a second replica doesn't see:

- **The key that seals `requestState`.** The refund confirmation from [Return an input request instead of a result](#return-an-input-request) sends the client a sealed `requestState` and opens it on the retry. By default `MCPServer` seals with a key that each process makes when it starts, and the state also names the server's name as its audience (`mcp/server/request_state.py`).
- **The handles the tools mint.** Chapter 3's quote store keeps each `quote_id` in the memory of the process that made it, as [What goes wrong in production](#design-tools-in-production) in chapter 3 warned.
- **The record of answered confirmations.** `confirmations.OnceOnly`, from [Keep round-trip state tamper-proof](#round-trip-state), remembers each answered `requestState` in one process's memory.

One refund, asked for on replica a and confirmed on replica b, touches all three kinds of state. Two replicas of chapter 5's refund server, each a process on its own port with one shop API behind both, run it. `lib.http_mcp.load_server` loads the server that `refund-asks-to-confirm.py` defines, and each replica runs it over HTTP. One client connects to each replica, and both read order O-1873. Then the client on replica a quotes a refund for order O-2289, whose amount is above the policy's limit, and replica a asks for confirmation. The retry with the support lead's yes goes to replica b, as a load balancer might send it. The sequence runs three times, fixing one kind of state each time:

1. each replica makes its own key;
2. both replicas read one key from `SHOP_REQUEST_STATE_KEY`, through `confirmations.state_security()`;
3. both also keep their quotes and their answered confirmations in one shared store, a SQLite file named by `SHOP_STATE_STORE`, and the client then sends the same answer a second time, to replica a.

The shared store is `lib.shared_state`. Its `SharedMap` and `SharedSet` keep entries in a SQLite file that every process on the machine opens, and each carries a lock on a file beside it, so that one replica's check-then-write can't interleave with another's. `shop_tools.create_server(quotes=...)` and `confirmations.OnceOnly(seen=...)` take any such container, and fall back to process memory without one, so chapters 3 and 5 run as before. Rows hold JSON, not pickles, and a quote's expiry is stored as a wall-clock time, because a monotonic deadline means nothing on another host. A SQLite file reaches only processes on one machine. A deployment puts the same two tables in a database its replicas share.

[Two replicas of the refund server: own keys, a shared key, and a shared store](../examples/two-replicas-one-client.py)

With their own keys, both reads worked ({{out:two-replicas-one-client:own keys reads on a and b}}), but the retry failed: {{out:two-replicas-one-client:own keys retry on b}}. Replica b couldn't open a state that replica a sealed, so the SDK refused the retry before the tool ran.

With one shared key, replica b opened the state, and the call failed one step later, inside the tool: "{{out:two-replicas-one-client:shared key retry on b}}" The quote lived in replica a's memory. The shared key fixed the first kind of state and exposed the second.

With the shared store as well, the retry on replica b released the refund, and its status became {{out:two-replicas-one-client:shared store retry on b}}. Replica b found replica a's quote in the shared store, and with it the refund the shop's API already held, so it released that refund without asking for a second one. The same answer sent again to replica a was refused: "{{out:two-replicas-one-client:shared store replay on a}}" Replica a had never seen the first answer. Without the shared record, its own `OnceOnly` check would have passed, and it would have asked the shop's API to release the refund again. Only the API's 409 for a refund it no longer holds would have stopped it. The refund completed once, across two replicas, with no sticky sessions. The specification asks for opaque, expiring handles ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)). Where their state lives is the server's choice, but with replicas it must be somewhere every replica reaches.

A deployment that hasn't moved some state yet can use a stopgap from the routing headers in [Read one HTTP exchange](#http-on-the-wire). It isn't stickiness: a gateway sends every request whose `Mcp-Name` names a tool that depends on that state to one replica, and spreads the rest. A `subscriptions/listen` stream is held by one replica, and the SDK ships only an in-memory bus, so events published on another replica never reach it ([deploy and scale](https://py.sdk.modelcontextprotocol.io/v2/run/deploy/); `mcp/server/subscriptions.py`, `InMemorySubscriptionBus`).

**Working rule:** Run replicas with no sticky sessions, and give every replica the same server name and the same `requestState` keys, injected from your secret store. Before you add a second replica, list every piece of state your tools keep in memory, such as handles, once-only records and subscriptions, and move each into storage that every replica reaches. Until one is moved, route the tools that depend on it to a single replica by `Mcp-Name`.

## Reject requests from other origins {#validate-origin}

The replicas in [Run replicas without sticky sessions](#scale-without-sessions) listen on 127.0.0.1, which feels private. It isn't. Any web page open in a browser on the same machine can send requests to a loopback port. With **DNS rebinding**, an attacker's domain can be made to resolve to 127.0.0.1 after the page loads, so the browser treats the local server as part of the attacker's site. The specification's tutorial on local servers says that binding to 127.0.0.1 "is not an authentication boundary" ([local server security](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/local-server-security)).

The browser hands the server its defence. It sends the page's `Origin` with each request it makes on the page's behalf. The [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) in the specification says servers MUST validate `Origin` on every incoming connection, MUST answer 403 when it is present and invalid, and SHOULD bind to 127.0.0.1 when they run locally. Checking `Host` as well stops the rebinding case, where the browser names the attacker's domain.

The SDK arms both checks by default. When the app's `host` is a loopback name and you pass no `transport_security`, it allows only `Host` values `127.0.0.1:*`, `localhost:*` and `[::1]:*`, and only `Origin` values with the same names under `http://` (`mcp/server/mcpserver/server.py`). Four requests probe that default: `tools/list` with no `Origin`, with the server's own origin, with `http://attacker.example`, and with a `Host` of `fernhill.example`. It then builds the same app with `host="0.0.0.0"`, the usual container setting, and sends the two foreign requests again. That app binds to 127.0.0.1, since only the setting is under test.

[Send requests from a foreign origin and a foreign host](../examples/reject-a-foreign-origin.py)

The loopback default turned away both foreign requests. A request with no `Origin` got {{out:reject-a-foreign-origin:no Origin}}, and so did the server's own origin: {{out:reject-a-foreign-origin:own Origin}}. The foreign origin got {{out:reject-a-foreign-origin:foreign Origin}}, and the foreign host got {{out:reject-a-foreign-origin:foreign Host}}, both as plain text rather than JSON-RPC (`mcp/server/transport_security.py`). The specification allows a body of either kind with the 403.

Built with `host="0.0.0.0"`, the app let both through: {{out:reject-a-foreign-origin:0.0.0.0 app, foreign Origin}} and {{out:reject-a-foreign-origin:0.0.0.0 app, foreign Host}}. A host the SDK doesn't recognise as loopback only stops it arming the default, and with no settings passed, the check is off (`mcp/server/transport_security.py`). That falls short of the specification's MUST, and nothing in the logs says so.

The request with no `Origin` shows what this defence covers. Browsers send `Origin`, while scripts, command-line tools and other servers don't, and the SDK lets a request without one through. Origin validation protects a server from web pages. It does nothing against a program that can reach the port, which is what authorization is for ([Authorize clients with OAuth](#authorization)).

**Working rule:** Keep the SDK's loopback default on a developer's machine. When you deploy on any other address, pass `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` with the names your server answers to, such as `mcp.fernhill.example`, and never rely on the default. Treat Origin validation as protection against browsers only, and put authorization in front of every server that anything but its own host can reach.

## Choose stdio or Streamable HTTP {#stdio-or-http}

The sections before this one moved the shop's server onto Streamable HTTP. The work that move took, from cancellation to replicas to origin checks, is the price of moving. stdio has none of it. The [stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio) in the specification has the client launch the server as a subprocess and exchange messages on its standard input and output. The host owns the process, so nothing else can reach it, the server inherits only what the host passes, and it lives as long as the host needs it.

The transports differ in who runs the server, and in what follows from that:

| | stdio | Streamable HTTP |
| --- | --- | --- |
| Started by | the host, one per host | you, once for many hosts |
| Reachable by | its own host | anything that reaches the address |
| Cancel | `notifications/cancelled` | close the response stream |
| Logs | standard error | your server's logs |
| Credentials | the host's environment | OAuth access tokens |
| Scales by | one process per host | replicas behind a load balancer |

We recommend stdio for a server that works for one user on that user's machine, such as one reading local files or using the user's own credentials, and for development. We recommend Streamable HTTP when several hosts share one server, when the server must run next to systems that the hosts can't reach, such as the shop's API inside its network, or when you need to deploy, scale and watch the server as a service. Then plan for authorization from the start, because a server on an address needs to know who is calling ([Find the authorization server from the resource](#protected-resource-metadata)).

With many hosts, the shop's API shouldn't be reachable from the support team's laptops, so the server moves to Streamable HTTP. The book keeps stdio for examples that need only one host and one server, because a subprocess is the shortest way to run one.

**Working rule:** Ship a server over stdio when it acts for one user on that user's machine. Ship it over Streamable HTTP when it serves several hosts, guards systems the hosts can't reach, or must scale, and give it origin checks and authorization before its first external user. The same server code can serve both, so choose per deployment, not per server.

## What goes wrong in production {#streamable-http-in-production}

The shop's server works on loopback with one client at a time. Behind real proxies, load balancers and clients it fails in a handful of ways, each with a sign you can watch for.

**Every request gets 421.** The deployment kept the SDK's loopback allowlist, and requests arrive with the server's public name in `Host`. The sign is `Invalid Host header` in plain text on every call and nothing in the tool logs. Pass `allowed_hosts` with the names the server answers to ([Reject requests from other origins](#validate-origin)).

**The checks are off without anyone deciding.** A server started with `host="0.0.0.0"`, the usual container setting, accepts every `Host` and `Origin` (`mcp/server/transport_security.py`). Nothing fails, so the only sign is a probe like `reject-a-foreign-origin` getting 200. Run that probe against each deployment, and set `transport_security` explicitly.

**Progress arrives all at once.** A proxy that buffers the response holds back every notification until the result. The SDK sends `X-Accel-Buffering: no`, the header the specification names for this, but proxies and CDNs that ignore it have settings of their own. The sign is a progress bar that jumps from nothing to done. Test progress through the real path, not on loopback.

**Long calls die at a round number of seconds.** Proxies and load balancers close idle connections after a fixed time. Once a stream is open, the SDK sends a `: ping` comment after every 15 seconds without another event, to keep it busy (`mcp/server/_streamable_http_modern.py`). A proxy with a shorter idle limit, or a total limit per request, still cuts the stream, and the cut cancels the tool. The sign is cancellations clustered at one duration. Raise the proxy's limits for the MCP path, or move the work into a task ([Start a task instead of waiting](#start-a-task)).

**A retry runs the work twice.** A broken stream can't be resumed, and the client sends the request again with a new ID ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). A tool that isn't safe to repeat does its side effect twice. The shop's `issue_refund` is safe because a quote refunds once, and with the shared store that holds on every replica. Give every tool with a side effect a handle or a key that makes the second call return the first call's result, and keep that record where every replica sees it.

**`json_response=True` silences progress and cancellation.** It is tempting behind a gateway that dislikes event streams, and the SDK gives no warning ([Stream progress on a long call](#stream-progress)). The sign is long calls that never report and keep running after clients leave.

**A gateway rewrites the body.** A gateway that edits JSON bodies but not headers makes requests fail with -32020, `HeaderMismatch`. The SDK's client resends once after fetching the tool list, so the sign is doubled `tools/call` requests and a steady trickle of -32020 in the server's responses.

**Clients on a 2025 revision need sessions.** The same app serves 2025-era clients through the old handshake, and by default it holds their sessions in one process's memory, which requires sticky routing (`mcp/server/streamable_http_manager.py`). The sign is `404` with "Session not found" from those clients only, after a request lands on another replica (`mcp/server/streamable_http_manager.py`). Set `stateless_http=True` if you serve them behind a load balancer, and know what it costs: those clients lose cancellation, so their handlers run to the end whatever the client did ([cancellation](https://py.sdk.modelcontextprotocol.io/v2/handlers/cancellation/)), and they lose server-to-client requests such as sampling and elicitation ([deploy and scale](https://py.sdk.modelcontextprotocol.io/v2/run/deploy/)). [Serve old and new clients through the window](#serve-both-revisions) weighs the trade.

**Large requests fail with 413.** The SDK caps a request body at 4 MiB by default (`mcp/server/transport_security.py`). A tool that takes a document as an argument hits it first. Raise `max_request_body_size` for that server, or pass a reference to the document instead of its bytes.

**Working rule:** Before the shop's server takes traffic on an address, test four things through the real proxy path: a foreign `Origin` gets 403, progress arrives while the call runs, a call longer than the proxy's idle limit survives, and closing a call's stream stops the tool. Then watch 421, 403 and -32020 by client, and cancellations by duration.

## Decisions this chapter made {#streamable-http-decisions}

- **The shop's server moves to Streamable HTTP** for the support team's hosts, with chapter 3's tools unchanged. stdio stays for examples with one host and one server.
- **`MCPServer.run(transport="streamable-http")` with the SDK's defaults:** loopback, path `/mcp`, and the default response mode, which streams. `stateless_http` stays unset until 2025-era clients need serving behind a load balancer, and then costs them cancellation.
- **`json_response=True` is never used,** because it drops progress and cancellation.
- **`recount_stock` reports progress after each product,** with a total and a message, and is safe to run twice.
- **Cancellation is a closed stream.** Long tools are `async def`, re-raise cancellation, and shield any awaited cleanup.
- **Replicas share their server name and `requestState` keys** through `SHOP_REQUEST_STATE_KEY`, and their quotes and answered confirmations through one shared store, `SHOP_STATE_STORE`. Every request, refunds included, runs on any replica. The examples' store is a SQLite file of JSON rows with wall-clock expiry; a deployment uses a database its replicas share.
- **Origin and Host checks stay on.** On any address but loopback, `transport_security` lists the server's names explicitly. Authorization, not Origin, keeps out callers that aren't browsers.
- **Gateways may route on `Mcp-Method` and `Mcp-Name`,** because the server rejects a request whose headers disagree with its body. No gateway rewrites a body.
- **HTTP traces come from `lib.wire.record_http`,** and hand-written requests from `lib.http_mcp.post`, only to show errors the SDK's client would never cause.
- **Examples run replicas as separate processes,** so that each has its own memory and its own key, as in a deployment.
