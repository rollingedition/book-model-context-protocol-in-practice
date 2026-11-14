---
chapter_id: tasks-and-extensions
---

# Run long work as tasks

By the end of this chapter you can negotiate a Model Context Protocol extension, run a slow restock report as a task that the client polls, let tasks expire and cancel them, and say what MCP Apps add to a tool. The code here speaks revision {{out:declare-the-tasks-extension:protocol revision}} of the specification, through version {{version:mcp}} of the Python SDK, `mcp`.

Before the weekly order to suppliers, a lead at [the shop](#the-shop), a small online seller of kitchen and garden goods whose support team answers customer tickets through a host, asks the host for a **restock report**: every product recounted, and the ones with fewer than 30 units across both warehouses listed for reordering. The shop's API has a slow endpoint, `POST /stock/{sku}/recount`, which recounts one product in both warehouses and by default takes 3 seconds. In [Serve over Streamable HTTP](#streamable-http), the shop's `recount_stock` tool walks all 64 products through that endpoint and streams a progress report after each one, while the client keeps the HTTP response open.

At the API's default speed, 64 products take more than three minutes, and a call that long has to survive the host's timeout, every proxy between the host and the server, and a lead who closes a laptop. Chapter 6 showed, in [Cancel a call the client no longer needs](#cancel-a-call), that a Streamable HTTP client cancels a call by closing its stream, so a call whose connection drops takes its work with it.

The Model Context Protocol (MCP) offers another shape for this work. With the **Tasks extension**, the server answers the call at once with a handle to a **task**. The client asks for the task's status as often as the server suggests, and the result waits on the server until the client fetches it. Tasks is an **extension**, an optional addition to the protocol that both sides must agree to use. So this chapter negotiates one, runs the restock report as a task, and ends with when not to.

Every example serves the shop's MCP server over loopback Streamable HTTP, as chapter 6's do, with the shop's API beside it. Setup they share lives in `examples/lib/`, and two modules there are new. `lib.tasks` is the book's own small Tasks extension, which [Negotiate an extension](#negotiate-an-extension) introduces. `lib.restock` holds the restock report's work: it recounts every product through chapter 6's `lib.recount`, sets the task's status message after each one, and lists the products to reorder.

## Negotiate an extension {#negotiate-an-extension}

The core protocol is what every client and server must implement. An extension is something the protocol's maintainers, or anyone else, want to standardize without making it mandatory. Extensions became part of the protocol at revision 2026-07-28, when `ClientCapabilities` and `ServerCapabilities` gained an `extensions` field, as the specification's changelog records ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). The field maps each extension's identifier to a settings object, and an empty one means the extension is supported with no settings. An identifier is a vendor prefix, a slash and a name. Official extensions use the prefix `io.modelcontextprotocol`, and anyone else uses a reversed domain they own ([Extensions overview](https://modelcontextprotocol.io/extensions/overview)).

At the pinned revision, a client declares its extensions in every request, under `_meta["io.modelcontextprotocol/clientCapabilities"].extensions`, the same place it declares every other capability ([Carry the version and capabilities on every request](#request-meta)). A server lists its own in the result of `server/discover` ([Extensions overview](https://modelcontextprotocol.io/extensions/overview)). Both sides leave extensions off by default and need an explicit opt-in. When only one side supports an extension, the specification says that side "MUST either revert to core protocol behavior or reject the request with an appropriate error" ([versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)). So an extension is negotiated, not forked: a server that uses one still answers clients that don't.

Extensions also have a lifecycle. A policy adopted in September 2026, after the pinned revision, gives each extension a stage, Experimental, Beta or Stable, or a path into the core protocol ([SEP-3392](https://modelcontextprotocol.io/seps/3392-extension-lifecycle)). Tasks is at Beta, to Core, and MCP Apps, which [Know what MCP Apps add](#mcp-apps) covers, is Stable ([Extensions overview](https://modelcontextprotocol.io/extensions/overview)). A Beta extension may still change in ways that break clients.

The Tasks extension's identifier is `io.modelcontextprotocol/tasks`, and it defines no settings ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). The Python SDK, `mcp` {{version:mcp}}, ships the framework for writing extensions, but not the Tasks extension itself. A server-side extension subclasses `mcp.server.extension.Extension`, sets `identifier`, and can add tools, resources and new request methods, or wrap `tools/call`. A client-side extension is a `ClientExtension`, which declares the identifier and can claim result shapes that the core protocol doesn't have (`mcp/server/extension.py`, `mcp/client/extension.py`).

The SDK has no `tasks/get` handler and no types for the extension's handle. The task types it does define belong to the experimental tasks of revision 2025-11-25 (`mcp_types`). The extension's only official SDK package, `@modelcontextprotocol/ext-tasks`, is TypeScript, covers only the requesting side at the pinned revision, and its receiver support is for the 2025-11-25 tasks, so no official package implements the server side there ([ext-tasks](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/README.md)).

So this book builds a small one. `lib.tasks` implements, on the SDK's framework, the part of the extension this chapter teaches: a `Tasks` server extension, a `TasksClient` client extension, and the methods `tasks/get` and `tasks/cancel`. It leaves out `tasks/update` and pushed notifications, and it keeps tasks in one process's memory. Use it to learn the protocol, and replace it with the SDK's own when a release ships one.

The shop's server passes `tasks.Tasks({"restock_report"})` to `MCPServer(extensions=[...])`, which tells it to answer every call to `restock_report` with a task. The tool itself calls `lib.restock`. Serving the shop's server to one client with `TasksClient` and to one without shows both halves of the negotiation. The client without the extension also sends one `tasks/get`.

[The shop's server declares the Tasks extension](../examples/declare-the-tasks-extension.py)

The server declared `{{out:declare-the-tasks-extension:server declares}}`, and the client with the extension sent `{{out:declare-the-tasks-extension:client declares}}` in the `_meta` of its `tools/list` request. Both are the identifier with an empty settings object.

The client without the extension got only a JSON-RPC error: {{out:declare-the-tasks-extension:client without it}}. The error's data lists what that client lacked, `{{out:declare-the-tasks-extension:required}}`. This is the specification's Missing Required Client Capability error, and the SDK's `require_client_extension()` raises it with the `requiredCapabilities` field filled in (`mcp/server/mcpserver/server.py`). The task methods check too. The same client's `tasks/get` got {{out:declare-the-tasks-extension:tasks/get without it}}, because the specification says servers MUST return that error for `tasks/get`, `tasks/update` and `tasks/cancel` from clients that didn't declare the extension ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). The SDK doesn't make that check for an extension's own methods, so `lib.tasks` calls `require_client_extension()` in each of them.

The shop rejects the call rather than falling back, because the fallback, a plain three-minute call, is the problem this chapter started from. A tool whose work is sometimes short could fall back instead, and answer clients without the extension the ordinary way.

**Working rule:** Turn an extension on only on a side that implements it, through the SDK's extension classes, never by writing the identifier into capabilities by hand. Decide, for each tool on the server, what a client without the extension gets: an ordinary result when the work can finish within a normal call, and error -32021 when it can't. Check the client's declaration on every request, because at the pinned revision each request declares its own.

## Start a task instead of waiting {#start-a-task}

The client in [Negotiate an extension](#negotiate-an-extension) declared that it can handle a task, and declaring is all the client does. At the pinned revision the server alone decides, call by call, whether to answer with a task. A client that declared the extension "MUST be prepared to handle either `CallToolResult` or `CreateTaskResult`" ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). The same tool can answer one call at once and the next with a task, and nothing in its definition says which. In the experimental tasks of revision 2025-11-25, the client asked for a task with a `task` parameter on the request. That design is gone and not wire-compatible with the extension.

Three rules limit the server. It MUST NOT return a task to a client that didn't declare the extension on that request, even if the client declared it on an earlier one. Only `tools/call` can be answered with a task in this revision. And the server MUST NOT return the handle until the task is durably created, so that a `tasks/get` for it would already find it ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)).

The handle is a `CreateTaskResult`: a result whose `resultType` is `"task"` instead of `"complete"`. It carries the task's `taskId`, its `status`, an optional `statusMessage`, the timestamps `createdAt` and `lastUpdatedAt`, its lifetime in `ttlMs`, and a suggested `pollIntervalMs` ([Tasks schema](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/schema/2026-07-28/schema.ts)). The specification lets extensions add `resultType` values, and a client MUST treat a value it doesn't recognize as invalid ([overview](https://modelcontextprotocol.io/specification/2026-07-28/basic)). That rule is why a server never sends a task to a client that hasn't declared the extension.

`lib.tasks` puts all of this in `Tasks.intercept_tool_call`, the SDK's one hook around `tools/call`. For a call to `restock_report`, it checks the request's declaration, creates a task record with an ID from `secrets.token_urlsafe(24)`, and stores it. Then it starts the tool's ordinary handler in the background and returns the handle. Because the background work runs the same handler as a plain call, the task's result is exactly the `CallToolResult` a plain call returns. Timestamps come from `tasks.Clock`, a fake clock that starts on the shop's reference date, 30 June 2026, and moves only when an example moves it, so the output is the same on every run.

Loading the server from the previous example, a client calls `restock_report` with `allow_claimed=True`, which returns the handle itself rather than the finished report. It then sends one `tasks/get` straight after, to check that the server already holds the task.

[Start the restock report as a task](../examples/start-a-restock-report.py)

The call came back at once as a task, not a result. Its `resultType` was `{{out:start-a-restock-report:result type}}`, and its `status` was `{{out:start-a-restock-report:status}}`. The handle's fields were {{out:start-a-restock-report:handle fields}}. The `_meta` field is the SDK's `serverInfo` stamp, added to every result at the pinned revision (`mcp/server/runner.py`).

The task was created at {{out:start-a-restock-report:created at}} on the fake clock. Its `ttlMs` was {{out:start-a-restock-report:ttl ms}}, one hour, and its `pollIntervalMs` was {{out:start-a-restock-report:poll interval ms}}. The `tasks/get` sent straight after found the task `{{out:start-a-restock-report:tasks/get straight after}}`, which shows the server stored it before the handle left.

The task ID was {{out:start-a-restock-report:task id length}} characters long, which encodes 192 random bits. The specification says task IDs may act as bearer handles, so servers MUST generate them with sufficient entropy that a third party cannot enumerate or guess them ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). Over Streamable HTTP, the client MUST also copy the ID into the `Mcp-Name` header of `tasks/get`, `tasks/update` and `tasks/cancel`, so that a load balancer can route every request for one task the same way. An assert checks that the header on its `tasks/get` equals the task ID. `lib.tasks` sets `name_param = "taskId"` on its request classes, and the SDK's client fills the header from that field (`mcp_types/_types.py`).

**Working rule:** Answer with a task when the work can outlive the connection, and decide per call, not per tool, when some calls are short. Store the task before you return the handle, and generate its ID from a cryptographic random source, with at least 128 bits. Run the same code a plain call runs, so a task's result never differs from a plain result. Never return a task to a request that didn't declare the extension.

## Poll a task and fetch its result {#poll-a-task}

The handle from [Start a task instead of waiting](#start-a-task) said the restock report was `working`. A task has five statuses: `working`, `input_required`, `completed`, `failed` and `cancelled`. The last three are terminal, and once a task reaches one, its state doesn't change ([Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview)). `failed` means a JSON-RPC error. A tool that ran and returned a result with `isError: true` ends `completed`, with that result inside, and the specification says `failed` MUST NOT be used for it ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). It is the same split chapter 3 drew between tool errors and protocol errors ([Report failures as tool results](#tool-errors)).

The client finds out where a task stands by polling. It sends `tasks/get` with the `taskId`, and it SHOULD wait the server's `pollIntervalMs` between polls, a value that may change from one reply to the next. Servers MAY rate-limit clients that poll faster. Each reply is the task, with `resultType` `"complete"`. When the task has completed, the reply carries `result`, which has the same structure as the result type of the original request ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension); [Tasks schema](https://raw.githubusercontent.com/modelcontextprotocol/ext-tasks/main/schema/2026-07-28/schema.ts)). For a tool, that is a `CallToolResult`. Clients SHOULD store task IDs durably, so that polling can resume after a crash or a restart.

A server may also push status changes. The client subscribes with `subscriptions/listen` for the task IDs it holds, and the server sends `notifications/tasks`, each carrying the full task ([Tasks overview](https://modelcontextprotocol.io/extensions/tasks/overview)). Polling stays the default, and `lib.tasks` implements only polling. A task that needs the user's input moves to `input_required` and carries input requests shaped like a Multi Round-Trip Request's ([Return an input request instead of a result](#return-an-input-request)), which the client answers with `tasks/update`. `lib.tasks` doesn't implement that either, and the restock report never asks.

In the SDK, polling belongs in a client extension. `TasksClient` claims the result type `"task"` with a `ResultClaim`. The claim's resolver gets the handle and a session for follow-up requests, and it must return the call's ordinary `CallToolResult` (`mcp/client/extension.py`). The resolver waits `pollIntervalMs`, sends `tasks/get`, and repeats until the task is terminal. `Client.call_tool` then returns the result as if the call had been plain. A client without a claim for `"task"` can't parse the handle: the SDK validates it as a `CallToolResult` and raises pydantic's `ValidationError`. `UnexpectedClaimedResult`, which carries the handle, is for a client that has the claim but calls `session.call_tool` without `allow_claimed=True` (`mcp/client/session.py`).

A host makes this call whenever a lead asks for the restock report, so the client connects with `TasksClient`, passing `on_poll=` to keep every `tasks/get` reply, and calls `restock_report` with a threshold of 30 units.

[Poll the restock report until it completes](../examples/poll-the-restock-report.py)

The polls show the task go from `working` to `completed`. The statuses seen were {{out:poll-the-restock-report:statuses}}, and the last status message read "{{out:poll-the-restock-report:last message}}". Two asserts also check that the report was still working on more than one poll, and that its status messages only counted up, so the count in each message never went down. The number of polls varies with the machine's speed, and the example prints none.

What came back from `Client.call_tool` was a `{{out:poll-the-restock-report:result type}}`. The report recounted {{out:poll-the-restock-report:skus recounted}} products and listed {{out:poll-the-restock-report:to reorder}} to reorder, the first being {{out:poll-the-restock-report:first to reorder}}. The code that made the call never saw a task, which is the point of the claim: a host written against plain tool calls, such as the one in [Build a host that works through tickets](#build-a-host), gets tasks by adding one extension to its client.

**Working rule:** Poll at the server's `pollIntervalMs`, re-read it on every reply, and stop at the first terminal status. Treat `completed` as the original call's result, `isError` and all, and `failed` as a protocol error. Hide the polling in a client extension so the rest of the host sees plain calls. When a host must survive a restart, store each task ID before the first poll, and resume from it.

## Expire and cancel tasks {#task-lifetime}

The restock report in [Poll a task and fetch its result](#poll-a-task) finished and was fetched. Not every task is. A client may crash and never come back, or a lead may close a report they no longer need, and a server that keeps every task forever runs out of storage. The extension gives a task two ways to end early: its lifetime runs out, or the client cancels it.

A task's lifetime is its `ttlMs`, counted from `createdAt`, or `null` for no limit, and the server may change it. After the TTL elapses, servers MAY mark a task as `failed` at any point after that, and delete it at any time. A server that has purged a task must answer a `tasks/get` for it with error -32602, Invalid Params, and it may say the task can't be found rather than that it expired ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). So a client can't count on a result outliving the TTL, however the task went.

Cancelling uses `tasks/cancel` with the `taskId`, and the specification says `notifications/cancelled` MUST NOT be used for it. The reply is an empty acknowledgement, and it promises little: "A server is not obligated to actually stop the work; it is only obligated to acknowledge the request." The task may stay `working` for a while, and it may still end `completed` or `failed`. Once it has sent the cancel, the client may forget the task ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). This is cooperative cancellation, unlike chapter 6's, where closing the stream cancelled the call's work in the server ([Cancel a call the client no longer needs](#cancel-a-call)).

`lib.tasks` makes both concrete. On a `tasks/get` after the TTL, it deletes the task, stops its work, and answers -32602 with the message the specification's example uses. On `tasks/cancel`, it sets a flag and acknowledges. The tool's work reads the flag through `tasks.cancel_requested()`, and `lib.restock` checks it after each product, so the restock report stops at the end of the product it is recounting, and the task becomes `cancelled` then.

A one-minute `ttlMs` shows expiry without a long wait. It also holds each report before every product, with `restock.Steps`, a gate in `lib.restock` that lets one more product start each time `allow()` is called, so the output doesn't depend on machine speed. It starts one report that is never allowed a product, polls it, moves the fake clock 61 seconds on, and polls again. Then it starts a second report, lets it recount one product, waits for its first status message, and cancels it. It polls at once, lets the report start its next product, and polls until the task is terminal.

[Expire one task and cancel another](../examples/expire-a-task.py)

The first task's `ttlMs` was {{out:expire-a-task:first, ttl ms}}, and it was `{{out:expire-a-task:first, first poll}}` on its first poll. After 61 seconds on the fake clock, `tasks/get` answered {{out:expire-a-task:first, 61 s later}}. A task whose lifetime runs out is purged, and a later `tasks/get` for it fails. Its work went with it, and so would its result have, had it finished.

The second task was {{out:expire-a-task:second, before cancel}} when the client cancelled it. Besides the SDK's `_meta` stamp, the acknowledgement held only {{out:expire-a-task:cancel acknowledged, besides _meta}}: an empty result, apart from the field every result carries. A poll straight after found the task still `{{out:expire-a-task:second, right after}}`. The cancel only set a flag, and the report hadn't reached its next check yet. A real report finishes its current product first. This one was held before its second.

The last poll found {{out:expire-a-task:second, finally}}. The report recounted one more product after the cancel, then stopped, as the specification allows.

**Working rule:** Give every task a TTL that covers the longest wait you expect between the work finishing and the client fetching it, and purge after it; for the shop's restock report, that is an hour. Make long work check for cancellation at each natural step, such as each product, and clean up there. In the client, treat a cancel's acknowledgement as "asked", not "stopped", and treat -32602 from `tasks/get` as a task that is gone for good.

## Know what MCP Apps add {#mcp-apps}

Tasks change when a tool's result arrives, as [Start a task instead of waiting](#start-a-task) showed. Another official extension, MCP Apps, changes how a result is shown. Its identifier is `io.modelcontextprotocol/ui`. A tool names a user interface in `_meta.ui.resourceUri`: a `ui://` resource, served with the MIME type `text/html;profile=mcp-app`. A host that supports Apps renders that HTML in a sandboxed iframe, and talks to it only through `postMessage`, in JSON-RPC: MCP's own methods, such as `tools/call`, plus methods whose names start with `ui/`. Through the host, the app can call the server's tools ([MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview); [Apps specification](https://raw.githubusercontent.com/modelcontextprotocol/ext-apps/main/specification/2026-01-26/apps.mdx)).

A tool's `_meta.ui.visibility` says who may call it, `["model", "app"]` by default. A tool for the app alone is hidden from the model. The Apps specification puts both directions on the host: it MUST NOT include such a tool in the model's tool list, and it MUST reject an app's call to a tool whose visibility leaves out `"app"` ([Apps specification](https://raw.githubusercontent.com/modelcontextprotocol/ext-apps/main/specification/2026-01-26/apps.mdx)). A UI-enabled tool should still return meaningful text for clients that don't support the extension ([Extensions overview](https://modelcontextprotocol.io/extensions/overview)).

The Apps specification is dated 2026-01-26 and marked Stable, and its negotiation examples use the 2025 `initialize` handshake. At the pinned revision, a client declares Apps per request, like any extension ([Negotiate an extension](#negotiate-an-extension)). Unlike Tasks, Apps ships in the Python SDK, in `mcp.server.apps`. `Apps()` is the extension, `@apps.tool(resource_uri=...)` declares a UI-enabled tool, `apps.add_html_resource()` serves the HTML, and `client_supports_apps(ctx)` says whether this request's client declared Apps with the right MIME type (`mcp/server/apps.py`).

The restock report is a candidate. As an app, it could show the products to reorder as a table, with a button beside each that adds the product to the supplier order. That button would call a tool such as `add_to_supplier_order`, with a visibility of `["app"]`, so that the model never places orders on its own. The report would keep its text and structured content, so a host without Apps would read the same report as in [Poll a task and fetch its result](#poll-a-task). The book doesn't build this view, since its host loop in chapter 10 has no screen.

MCP Apps and elicitation do different jobs. Elicitation is the server asking the user one question in the middle of a call, through the client's own form ([Ask for structured input with elicitation](#elicitation-forms)). An app is a view of a tool's result, which the server writes and the host renders.

**Working rule:** Reach for MCP Apps when a result needs more than text to act on, such as a table to sort or a choice per row, and the hosts your users run support the extension. Keep every UI-enabled tool's text result complete, so a host without Apps loses only the view. Give app-only tools a visibility of `["app"]` when the model shouldn't call them, and remember that the host enforces it, not your server.

## Choose a task, progress or a plain call {#task-or-call}

The shop now runs work three ways: a plain call, such as `get_order_status`; a call that streams progress, chapter 6's `recount_stock`; and a task, the restock report from [Poll a task and fetch its result](#poll-a-task). They differ in what the connection must survive and what the caller sees while waiting.

Progress settles most of the choice. At this revision, the specification doesn't support `notifications/progress` or `notifications/message` on tasks in general ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). A task reports how far it has got only through its `statusMessage`, which the client reads when it polls. The restock report's "recounted 12 of 64 SKUs" is that kind of message: a string, seen only as often as the client polls, with no number a progress bar can use. Log messages are no way around it ([Replace sampling, roots and logging](#replace-deprecated-features)).

The other difference is who must support what. A plain call and progress are core protocol. A task needs both sides to implement an extension, and host support for extensions varies ([Extension support matrix](https://modelcontextprotocol.io/extensions/client-matrix)). The Tasks overview lists the cases a task is for: work that outlives a connection, work that must survive a client restart, and work that already runs as a job in a queue.

Our rule of thumb, not a measurement, sets the three ways side by side in the table.

| | Plain call | Progress | Task |
| --- | --- | --- | --- |
| Typical length | seconds | up to a few minutes | minutes or more |
| Connection must stay open | yes | yes | no |
| Caller sees while waiting | nothing | progress and total | a status message |
| Survives a client restart | no | no | yes, if the client stored the ID |
| Needs an extension | no | no | yes, on both sides |

`get_order_status` stays a plain call, because it answers in milliseconds. `recount_stock` keeps chapter 6's progress, because a lead who starts it watches a count rise and waits. The restock report becomes a task, because it runs for minutes at the API's real speed, the lead wants it later rather than watched, and a dropped connection shouldn't cost three minutes of recounting.

**Working rule:** Use a plain call when the result comes back well within every timeout between the host and the server. Use progress when the work is long, the caller waits for it on a connection you trust to stay open, and wants a number to show. Use a task when the work can outlive the connection, or when the caller wants to leave and come back. Accept that a task reports only a status message, and keep a plain-call fallback or a clear -32021 for clients without the extension.

## What goes wrong in production {#tasks-and-extensions-in-production}

The restock report in this chapter ran in one process, with tasks in memory and a fake clock. Spread across replicas, run for days and called by many users, it can fail in the ways that follow, each with a sign you can look for.

**Tasks are stored on one replica.** `lib.tasks` keeps tasks in a dictionary. Behind chapter 6's two replicas ([Run replicas without sticky sessions](#scale-without-sessions)), a `tasks/get` that reaches the other replica finds nothing and answers -32602. Store tasks where every replica can read them, such as a database or a job queue's own store, or route on the `Mcp-Name` header, which carries the task ID on every task request. You'll notice it as tasks that "expire" within seconds, at about the rate your load balancer switches replicas.

**Task IDs leak another caller's result.** A task ID can be the only thing between a caller and a stored result. The specification says servers MUST perform authentication and authorization checks on each task-related request, and it removed `tasks/list`, which, scoped badly, could show one caller another's task IDs ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). Record the caller with the task, from the token's subject once [Authorize clients with OAuth](#authorization) is in place, and refuse every `tasks/get` and `tasks/cancel` from anyone else. An input request that arrives through a task gets the same trust as one in a direct call, and no more: "A task is not a higher-trust channel."

**The SDK doesn't check the declaration for you.** In `mcp` {{version:mcp}}, the server runner passes an extension's `resultType` through unchecked, and a note in the source says that rejecting it for clients that didn't declare the extension is still to do (`mcp/server/runner.py`). The extension must call `require_client_extension()` itself, on the call and on each of its own methods, as `lib.tasks` does. A client that didn't declare Tasks and gets a task anyway must treat the result as invalid. The SDK's client does, because without a claim for `"task"` it validates the handle as a `CallToolResult` and raises a `ValidationError`.

**Polling costs more than the work.** Thousands of clients polling every 100 milliseconds make a load of their own. Raise `pollIntervalMs` as a task runs longer, rate-limit clients that ignore it as the specification allows, and offer `notifications/tasks` once your server can push. The sign is `tasks/get` outnumbering every other method in your traces.

**Tasks pile up.** A TTL of `null`, or one longer than any client waits, keeps every abandoned task's result. Set a TTL, purge on a schedule as well as on read, and alert on the number of stored tasks. Clients that lose task IDs on restart make the pile grow faster, so store IDs on the client before the first poll.

**Cancelled work keeps running.** A tool that never checks for cancellation runs to the end after every `tasks/cancel`, and the shop's API recounts products nobody wants. Check at each step, and log how long tasks run after a cancel.

**Clients speak the 2025-11-25 tasks.** That revision's experimental tasks used `tasks/result`, `tasks/list` and a `task` parameter on the request, and they aren't wire-compatible with the extension ([SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension)). A 2025-era client never declares `io.modelcontextprotocol/tasks`, so it meets the server's -32021. [Migrate a 2025-era server](#migrate-from-2025) covers the rest of the old protocol.

**The extension changes under you.** Tasks is Beta and on its way into the core protocol, and the SDK may ship its own Tasks extension in a later release. Either is a reason to update this chapter. When the SDK ships one, replace `lib.tasks` with it and keep the shop's tool as it is, since the tool never knew it ran as a task.

**Working rule:** Before tasks go to production, move their storage to where every replica can read it, record each task's owner and check it on every task request, and set a TTL with a purge that runs on a schedule. Then watch -32602 from `tasks/get` by replica, the ratio of `tasks/get` to `tools/call`, the number of stored tasks, and how long work runs after a cancel.

## Decisions this chapter made {#tasks-and-extensions-decisions}

- The shop's restock report runs as a task, through the Tasks extension, because its work outlives a connection.
- The shop's server refuses `restock_report` with error -32021 for clients without the extension, instead of running a three-minute plain call.
- The book builds its own small Tasks extension, `lib.tasks`, on the SDK's extension framework, because `mcp` {{version:mcp}} ships none. It implements `tasks/get` and `tasks/cancel`, and leaves out `tasks/update` and pushed notifications.
- A task runs the tool's ordinary handler, so its result is the same `CallToolResult` a plain call returns.
- Task IDs carry 192 random bits, and every task request carries its ID in the `Mcp-Name` header.
- The client polls at the server's `pollIntervalMs` inside a client extension, so the host sees plain tool calls.
- Tasks expire one hour after they are created, and cancelling is cooperative: the restock report checks after each product.
- `recount_stock` keeps chapter 6's progress, and `get_order_status` stays a plain call.
- MCP Apps are described, not built, because the book's host loop renders no HTML. A restock view would keep the report's text, and hide its ordering tool from the model with a visibility of `["app"]`.
- In production, tasks move to storage that both of chapter 6's replicas share, and every task request is checked against the caller who started the task.

- The lesson is where the waiting goes: a task moves it off the connection and onto the server, which keeps the state, sets how long it lasts, and decides who may read it.
