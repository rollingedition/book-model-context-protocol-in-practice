---
chapter_id: resources-and-prompts
---

# Serve data as resources and prompts

By the end of this chapter you can publish the shop's policies and records as Model Context Protocol resources, address many records with one resource template, complete an argument while a user types it, tell a client when a resource changes, and package a refund review as a prompt the user can pick. The code runs against revision {{out:list-policy-resources:protocol revision}} of the specification, using version {{version:mcp}} of the Python SDK, `mcp`.

The support team at [the shop](#the-shop), a small online seller of kitchen and garden goods, answers customer tickets, and wants its host to have the shop's data at hand. [Separate the host, the client and the server](#host-client-server) gave the shop's server, `shop-support`, one capability of each kind: the tool `get_order_status`, the refund policy as a resource, and a short `review_refund` prompt. Much of what the host needs isn't an action, though, and one document and one prompt don't cover it. Every refund answer must follow the refund policy, a ticket is about one order, and a stock question is about one product's count. If each of those is a tool, the model has to decide to fetch it, and it may not.

The Model Context Protocol (MCP) gives a server two other primitives for this, which differ from tools in who decides when they're used ([Put each capability in the right primitive](#choose-a-primitive)). A **resource** is data the server publishes under a URI, and the host decides whether to put it in front of a model. A **prompt** is a message template the server offers, and the user picks it. Chapter 2 showed one of each; this chapter builds both out for the shop.

The server keeps the name `shop-support` throughout. Each example defines only the part its section teaches, and runs itself as chapter 2's server examples do: with no arguments, the file starts a client that launches the same file with `--serve` over stdio.

## Expose the policies as resources {#policies-as-resources}

`shop-support` already publishes one of the rules an answer must follow, the refund policy, which [Resources are data the application chooses](#resources-application-chooses) showed how to serve, and the shop has five more. Each one suits a resource: data that a server publishes under a URI, with a `name`, an optional `title` and `description`, a `mimeType`, and contents that are either text or a base64 `blob` ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)). A client lists a server's resources with `resources/list` and reads one with `resources/read`.

Resources are application-driven: the host decides how they're used. The specification's resources page says a host might show a picker, search the resources, or include some automatically, based on heuristics or the model's own selection. The protocol gives the model no direct way to read a resource; the host decides, though it may let the model choose. A resource's URI follows RFC 3986, and a server may use a scheme of its own. The specification keeps `https://` for resources a client can fetch without the server, directly from the web.

The server publishes each policy as a static resource at `shop://policies/{slug}`. The refund policy keeps the URI `shop://policies/refund` and the name `refund-policy` that chapter 2 gave it. The SDK's `FileResource` reads the file again on every `resources/read`, so an edited policy reaches the next read without a restart (`mcp/server/mcpserver/resources/types.py`). Each resource also carries three **annotations**, which are hints the host may use or ignore ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)):

- `audience` says who the content is for. The policies are for `assistant`, the model.
- `priority`, from 0.0 to 1.0, says how important the content is, and 1 means "effectively required". We give the refund policy 1.0 and the others 0.5. That is a judgement: every refund answer must follow the refund policy, while the other five matter only for some tickets.
- `lastModified` is an ISO 8601 time, here each policy's `Updated:` date.

At the pinned revision, the results of `resources/list` and `resources/read` carry two cache hints. `ttlMs` says how long a result stays fresh, and `cacheScope` says whether a cache may share it across callers ([caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)). The SDK's default is a `ttlMs` of 0 with the `private` scope (`mcp/server/caching.py`). The policies are the same for every caller and change rarely, so this server marks both methods `public` for an hour. The run below serves the policies that way and shows the hints.

[Serve the shop's policies as resources](../examples/list-policy-resources.py)

The client sees {{out:list-policy-resources:resources}} resources, sorted by slug, and only the refund policy has priority 1.0. The list carries the scope `{{out:list-policy-resources:list cache scope}}` and a lifetime of {{out:list-policy-resources:list ttl ms}} milliseconds, so a client may reuse it for an hour and share it between users. [Cache list results](#cache-list-results) shows what a client does with the hints.

Reading `shop://policies/refund` returned the file itself, as `{{out:list-policy-resources:mime type}}` text that begins with the line `{{out:list-policy-resources:first line}}`. The read carries the same scope, `{{out:list-policy-resources:read cache scope}}`, because the hints set both methods to public.

That exchange never put the refund policy in front of a model. The server published it, and the host alone decides when to include it. [Put resources in the model's context](#resources-in-context) builds the host loop that does so for every refund ticket.

**Working rule:** Publish the documents a host may put in front of a model as static resources, under a scheme that names your system, with a MIME type and a description the host can show. Use `https://` only for resources the client can fetch without your server. Mark a result `public` only when every caller gets the same one, and give high priority only to the one or two documents every answer depends on, not to all of them.

## Address records with resource templates {#resource-templates}

The six policies in [the previous section](#policies-as-resources) suit a list, but the shop's orders don't. The data holds {{out:complete-order-ids:shop orders starting O-2}} orders whose IDs start with `O-2` alone, and a resource for each would be useless to a host and expensive to serve. A **resource template** names many resources with one URI template, written in the syntax of RFC 6570 ([RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)). A client lists templates with `resources/templates/list`, fills in the variables, and reads the result with `resources/read` like any other resource ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)).

In the Python SDK, the URI passed to `@server.resource()` picks the kind. Braces around a variable register a template, and the function's parameters must match the variables. A URI without braces registers a static resource (`mcp/server/mcpserver/server.py`, `resource`). The return value sets the contents: a `str` gives text, `bytes` give a blob, and anything else is converted to JSON.

A template also changes what a miss means. At the pinned revision, a read of a resource that doesn't exist fails with the JSON-RPC error -32602, Invalid Params, and the URI goes in the error's `data`. The server "MUST NOT return an empty `contents` array" instead ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)). Revision 2025-11-25 used -32002 for the same case, and clients should still accept that code from older servers ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). In `MCPServer`, a function gets -32602 by raising `ResourceNotFoundError`. Any other `ResourceError` becomes -32603, and a resource, unlike a tool, has no `isError` result to fail with ([handling errors](https://py.sdk.modelcontextprotocol.io/v2/servers/handling-errors/)).

The shop's order template is `shop://orders/{order_id}`, and its function wraps `GET /orders/{order_id}`, the endpoint that `get_order_status` wraps too. It raises `ResourceNotFoundError` when the API answers 404. An order belongs to one customer, so the read keeps the SDK's default cache hint, `private` with a lifetime of 0. The caching page names `private` as the scope for `resources/read` results "that depend on the authenticated user" ([caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)). Before the API sees anything, the function checks that the variable looks like an order ID, `O-` and four digits, and raises `ResourceNotFoundError` if it doesn't, so a malformed ID never reaches the API.

Four reads show what a client sees when a read succeeds and when it misses: a real order, one that doesn't exist, one ID in the wrong format, and one URI whose variable tries to climb out of the order's path.

[Address orders with a resource template](../examples/order-resource-template.py)

The template is listed as `{{out:order-resource-template:template}}`, and order O-2476 reads as {{out:order-resource-template:O-2476 status}}, with the cache scope `{{out:order-resource-template:read cache scope}}`.

The three misses fail with the same code, {{out:order-resource-template:unknown order code}}, but their messages come from different places. The unknown order, O-7144, gets the handler's own message, and its URI comes back in the error's data, `{{out:order-resource-template:unknown order data uri}}`. The ID `2476` gets the format check's message, `{{out:order-resource-template:malformed says}}`.

The traversal read fails too, but its message is the SDK's, `{{out:order-resource-template:traversal says}}`, not the handler's. The SDK decoded the variable to `../../refunds`, found `..` path segments in it, and refused the URI before the function ran. Without that refusal, the handler would have sent `../../refunds` in its request path to the shop's API.

That refusal is `ResourceSecurity`, which by default rejects `..` segments, absolute paths and NUL bytes in template variables, whatever encoding the URI used (`mcp/server/mcpserver/resources/templates.py`). The specification requires servers to validate every resource URI ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)), and the SDK's check backs that up without replacing it. It doesn't stop `2476`, which passes `ResourceSecurity`, so only the handler's format check catches that one.

This template reads any order for whoever holds the server's API key, which suits the support team's host. [The next section](#argument-completion) scopes reads to one customer.

**Working rule:** Use a resource template for records that share one shape and an ID. Return the API's own JSON, and raise `ResourceNotFoundError` for a miss, which gives the client -32602 with the URI. Keep the scope `private` for anything that belongs to a user. Leave the SDK's `ResourceSecurity` on, and validate the variable's format yourself too. Exempt a variable from the check only when it must carry a path, and then check the path yourself.

## Complete arguments for the user {#argument-completion}

A host that shows the order template from [the previous section](#resource-templates) to a person needs them to fill in `order_id`, and few people remember order IDs. **Argument completion** lets the host ask the server for suggestions while the user types. The host sends `completion/complete` with a reference, either `ref/resource` with a template's URI or `ref/prompt` with a prompt's name, plus the argument's name and its partial value. It may add `context.arguments`, the values the user has already chosen for other arguments. The result holds `values`, at most 100 of them, with an optional `total` and `hasMore`. A server that offers completion declares the `completions` capability ([completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion)).

In the Python SDK, one `@server.completion()` handler serves every template and prompt on the server. It receives the reference, the argument and the context, and returns a `Completion` or `None`. Registering it declares the capability. The SDK doesn't filter what it returns, so whatever goes in `values` is what the UI shows ([completions](https://py.sdk.modelcontextprotocol.io/v2/servers/completions/)). It doesn't enforce the 100-item cap either. The `Completion` type says it must not exceed 100 items, but nothing checks that (`mcp_types/_types.py`), so the handler has to cap the list itself.

Completion is also a lookup, and a lookup can leak. The specification requires servers to control access to sensitive suggestions, which keeps completion from disclosing information it shouldn't ([completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion)). A handler that completed order IDs from the whole shop would tell anyone who types `O-2` which of the shop's orders exist.

So the handler completes only the orders of the customer the server acts for. Over stdio, the host names that customer in the server's environment, as it passes the shop's API key. Here `SHOP_CUSTOMER_ID` is C-0127, the customer who placed order O-2476. Over HTTP, [Authorize clients with OAuth](#authorization) replaces the variable with what an access token says. A support host's token names a member of staff, so the customer comes from the ticket the server looks up. Only where customers sign in themselves is the token's subject the customer ([Keep the server from acting as a confused deputy](#confused-deputy)).

The handler asks the shop's API for that customer's orders and keeps those that start with what the user typed. The API returns at most 100 of a customer's orders, newest first (`examples/lib/shop_api.py`), so the answer can never pass the protocol's cap. The handler keeps that order too: for a support ticket the newest orders are the likeliest, and the specification asks for suggestions "sorted by relevance" ([completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion)).

The API's response also carries the customer's total number of orders. When that total is more than the API returned, older orders might match too, so the handler leaves `total` out and sets `has_more`. Otherwise it reports the number of matches as `total`. The order template applies the same scope to reads: another customer's order gets the same not-found answer as an order that doesn't exist. A shared module, `lib.shop_reads`, holds the async helper both handlers use to call the shop's API. Two cases test that scope: a prefix that matches many orders, and a read that crosses customers.

[Complete order IDs for the caller only](../examples/complete-order-ids.py)

Completion offers each caller only their own orders. Over the whole shop, `O-2` would match {{out:complete-order-ids:shop orders starting O-2}} orders, more than the cap allows in one answer, but customer C-0127 typing `O-2` is offered {{out:complete-order-ids:O-2 offers}} and nothing else. Typing `o-24` in lower case still gets {{out:complete-order-ids:o-24 offers}}, because the handler upper-cases what the user typed first.

Reading another customer's order, O-1767, returns `{{out:complete-order-ids:O-1767 answer}}`, and reading O-7144, which doesn't exist, returns `{{out:complete-order-ids:O-7144 answer}}`. The two answers differ only in the ID, so the caller can't tell an order that exists from one that doesn't.

The cap matters only to a customer with more than 100 orders. The most any one customer has in the shop's data is {{out:complete-order-ids:most orders for one customer}}, so for every customer the API returns all their orders, and the handler reports a `total`. A customer with a 101st order would be offered matches from the newest 100 only, with no `total` and `has_more` true. The run can't show that case, because no customer in the shop's data has that many.

`context.arguments` earns its place with a prompt that takes more than one argument, such as one that narrows order IDs to a customer the user picked first. Treat it as the user's input, never as authorization, because whoever calls the server chooses what it says. The specification also asks servers to rate-limit completion requests and clients to debounce them, since a host may send one per keystroke ([completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion)).

**Working rule:** Complete arguments only from what the caller may read, decided by who the server acts for, not by anything in the request. Filter by the typed prefix yourself, and keep the list within 100 values, because the SDK won't. Set `has_more` whenever the source you filtered was itself cut short, and report a `total` only when you counted every match. Give an inaccessible record the same not-found answer as a missing one, on reads and in completions alike.

## Tell clients when a resource changes {#resource-change-notifications}

A host that has put a resource in front of a model, such as an order from [the order template](#resource-templates), must hear about changes, or it keeps showing a stale copy. At the pinned revision, a client asks for change notifications with one request, `subscriptions/listen`. Its filter can name resource URIs to watch (`resourceSubscriptions`) and ask for list changes (`resourcesListChanged`, `toolsListChanged`, `promptsListChanged`), and the response is a long-lived stream of notifications ([subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)).

`subscriptions/listen` replaces three things from the 2025 revisions: `resources/subscribe`, `resources/unsubscribe` and the HTTP GET stream ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). The SDK's `Client.subscribe_resource` is deprecated, and it talks only to 2025-era servers (`mcp/client/client.py`). [Inventory what the old server depends on](#inventory-2025-features) covers the move away from it.

The stream has a fixed shape ([subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)):

- The server first sends `notifications/subscriptions/acknowledged`, naming the subset of the filter it will honour.
- It then tags every notification with `io.modelcontextprotocol/subscriptionId`, the listen request's JSON-RPC ID, and "MUST NOT send notification types the client has not explicitly requested."
- A `notifications/resources/updated` message carries the URI and nothing else. It says that the resource changed, not what it holds, so the client reads it again.
- On stdio, the server keeps no subscription state across reconnections. After a dropped stream, the client sends `subscriptions/listen` again and refetches what it depends on.

In the Python SDK, server code publishes a change with `await ctx.notify_resource_updated(uri)`. That hands the update to a subscription bus, which every open stream reads from (`mcp/server/mcpserver/context.py`). On the client, `async with client.listen(resource_subscriptions=[...]) as changes` sends the request and waits for the acknowledgment. `changes.honored` then holds what the server agreed to, and iterating over `changes` yields events. A graceful close by the server ends the loop, and an abrupt drop raises `SubscriptionLost` (`mcp/client/client.py`, `listen`). Nothing is replayed, and the SDK says a dropped stream is not resumable (`mcp/server/subscriptions.py`). The run below shows what that costs.

The shop's stock policy says a negative count means a recount is due, and KG-1018 has one in the `south` warehouse. To show a change within one process, the example keeps the counts in the server's memory, standing in for the shop's stock system. It publishes each product's counts as `shop://stock/{sku}`, and it adds a tool, `set_on_hand`, that a warehouse's host would call after a recount. The tool replaces one count and publishes an update for that product's URI. The client watches KG-1018 and KG-9999, which doesn't exist. It records a recount of another product, then one of KG-1018, and later closes the stream and opens it again. The run shows what a client sees and misses.

[Watch a product's stock for changes](../examples/stock-resource-changes.py)

The SDK honours every URI a client asks for, even one that doesn't exist. Here the acknowledgment honours both, `{{out:stock-resource-changes:honoured}}`, including the product the shop doesn't sell, and the SDK doesn't check whether the caller may read either (`mcp/server/subscriptions.py`). [What goes wrong in production](#resources-and-prompts-in-production) returns to that.

A change made while a stream is open reaches the client as an event naming only the URI, and the client re-reads. The recount of KG-1026 sent nothing on this stream, because nobody asked to watch it, and the first event names `{{out:stock-resource-changes:first event}}`. KG-1018 reads `{{out:stock-resource-changes:before}}` before the recount and `{{out:stock-resource-changes:after}}` after it.

The notification for a change made while nobody listens is gone for good. The client closed the stream, and a second recount set the `south` count to 3. On the reopened stream, a wait of a second turned up {{out:stock-resource-changes:events after re-listening}} events, and only a fresh read, `{{out:stock-resource-changes:re-read}}`, shows the change.

The in-memory bus reaches only the streams in its own process. With two replicas of the server, a change on one never reaches a stream on the other, so replicas need a shared bus ([subscriptions](https://py.sdk.modelcontextprotocol.io/v2/handlers/subscriptions/)). [Run replicas without sticky sessions](#scale-without-sessions) runs the shop's server that way.

**Working rule:** Watch only the resources the host has put in front of a model or a user, and treat each event as a cue to read again, never as the new value. Re-read everything you depend on whenever you open a stream, the first time and after every drop, because nothing is replayed. Publish an update for the exact URI clients read, from the code path that makes the change.

## Package a workflow as a prompt {#workflows-as-prompts}

The resources in [the previous sections](#policies-as-resources) give a host the shop's data. Some of the support team's work, though, is a fixed procedure that a person starts, such as reviewing a refund before anyone issues it. A **prompt** packages such a procedure as a named message template that the server offers and the user picks, for example as a slash command. The user decides when it's used, and the server writes it, as [Prompts are templates the user chooses](#prompts-user-chooses) quoted.

A prompt has a `name`, an optional `title` and `description`, and `arguments`, each with a name, a description and whether it's required. A client lists prompts with `prompts/list` and fills one in with `prompts/get`, which returns `messages`. Each message has the role `user` or `assistant` and one content block: text, an image, audio, a resource link, or an embedded resource that carries a resource's contents inside the message. There is no `system` role, so a prompt is not a system prompt, and the host keeps its own. The same page says implementations "MUST carefully validate all prompt inputs and outputs to prevent injection attacks or unauthorized access to resources."

In the Python SDK, `@server.prompt()` takes the prompt's name from the function, its arguments from the parameters and its description from the docstring. The function returns the messages, and a bare string or content block becomes one `user` message (`mcp/server/mcpserver/prompts/base.py`). An `MCPError` the function raises reaches the client unchanged. But for an unknown prompt or a missing required argument, the SDK raises a plain `ValueError` (`mcp/server/mcpserver/server.py`, `get_prompt`), though the specification assigns -32602 to both ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema)).

The support team reviews each refund request against the refund policy, which says that a refund above €150.00 needs a support lead to confirm it. Chapter 2's `review_refund` took only an `order_id`, and its one message told the model which tool and resource to fetch. Here the prompt gains a second argument, `amount`, and carries what the review needs itself. Before it calls anything, it checks that both arguments look like the shop's formats. Then it looks the order up through the shop's API and returns two `user` messages. The first embeds the refund policy under its URI, `shop://policies/refund`, so the host needn't read it separately. The second quotes the order and asks the review's three questions.

Filling the prompt in for order O-1145, whose customer asks for €343.49, shows the messages a model would receive. Three bad calls follow: a path where an order ID belongs, a missing argument and a misspelled prompt name.

[A prompt for reviewing a refund](../examples/refund-review-prompt.py)

The filled-in prompt is two messages, and the first is the refund policy itself. `{{out:refund-review-prompt:message 1}}` is a user message whose content is the embedded policy, and `{{out:refund-review-prompt:message 2}}` carries the order and the questions. Nothing here calls a model. These messages are what a host sends a model when a person on the support team picks the prompt, and [Run the host loop](#run-the-host-loop) makes that turn.

The failures show where the SDK and the specification part. The path, `../refunds`, never reached the shop's API, because the format check raised `MCPError` with `INVALID_PARAMS`, and the client got `{{out:refund-review-prompt:path as order_id}}`. The two failures the SDK handles itself came back differently. A missing amount gave `{{out:refund-review-prompt:missing amount}}`, and the misspelled name gave `{{out:refund-review-prompt:unknown prompt}}`. Both carry the internal-error code rather than the -32602 the specification assigns, and the SDK's own message is hidden behind a generic one. So a host can't tell either mistake from a crash in the server.

Prompt arguments also become text that a model reads. A customer's words pasted into a free-text argument would reach the model inside a `user` message, which is one reason this prompt takes only an order ID and a decimal amount. [Treat ticket text as untrusted data](#untrusted-tool-output) covers that path in general.

**Working rule:** Offer a prompt for a procedure a person starts by name, and keep its arguments to values with a format you can check. Embed the resources the procedure depends on, so the host needn't fetch them. Validate every argument before you use it, and raise `MCPError` with `INVALID_PARAMS` for a bad one, because the SDK's own checks answer with an internal error.

## Choose between a resource and a tool {#resource-or-tool}

[Put each capability in the right primitive](#choose-a-primitive) settled most of the choice by asking who decides when the data is used. It left one case open, data that is both. [The previous sections](#policies-as-resources) published the same kinds of shop data that the tools in [Shape tools around tasks, not endpoints](#tasks-not-endpoints) return: an order, from `get_order_status`, and a product's stock, from `check_stock`. What follows is judgement, not measurement.

The order template lets a host attach the order a ticket is about before the model reads the ticket. `get_order_status` lets the model look up an order it finds in the ticket's text instead. Keep both reading through the same API call, so they can't disagree.

When a tool finds records the host may want to keep, it can return resource links to them instead of their full contents, and the host reads the ones it needs. The specification doesn't guarantee that such links appear in a `resources/list` result ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)), so a server can link to records that only a template addresses.

**Working rule:** Offer a record as both a resource and a tool when hosts attach it and models look it up, and serve both from one code path so they can't disagree. When a tool finds records the host may keep, return resource links to them rather than their contents.

## What goes wrong in production {#resources-and-prompts-in-production}

The shop's resources and prompts work on one machine with one caller. In production, with many callers, caches, replicas and hosts the shop didn't write, they fail in a handful of ways, and each has a sign you can watch for.

**A per-user read gets a public cache scope.** A cache "MUST NOT" share a result across authorization contexts, and `public` tells it that the result may be shared ([caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching)). `MCPServer` can't set the hint on each function, so `cache_hints` sets one hint per method, and a server that serves public policies and private orders gives the same hint on every `resources/read` (`mcp/server/mcpserver/server.py`, `_handle_read_resource`). Keep `resources/read` private on a server that serves anything per user, or give the policies a server of their own. The sign is a user who sees an order that isn't theirs, which no test with one user finds. And `ttlMs` is not a polling interval: clients "SHOULD NOT" poll on it.

**Lists differ between connections.** `resources/list` and `prompts/list` must not vary per connection, as [Cache list results](#cache-list-results) said of the tool list. A list may vary by the authorization on the request, and it may change over time if the server sends a list-changed notification ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources), [prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts)). A server that adds a resource after a tool call breaks every client's cache. The sign is a list that changes after a tool call, or changes with no list-changed notification.

**A client watches what it can't read.** The SDK honours every URI a client asks to watch, as [the stock example](#resource-change-notifications) showed with a product the shop doesn't sell. A client watching another customer's order would learn that the order exists, and when it changed. Put middleware on `subscriptions/listen` that rejects URIs the caller may not read ([subscriptions](https://py.sdk.modelcontextprotocol.io/v2/handlers/subscriptions/)). The sign is an acknowledgment that echoes URIs the caller could never read.

**An update never matches.** `MCPServer` compares URIs as exact strings ([subscriptions](https://py.sdk.modelcontextprotocol.io/v2/handlers/subscriptions/)), so a client watching `shop://stock/kg-1018` never hears about `shop://stock/KG-1018`. The specification also allows an update to name a sub-resource of the watched URI ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema)), and `MCPServer` never matches one. The sign is a client that refreshes only when it reconnects. Publish the exact URI your templates produce, and normalize IDs before you build a URI.

**A dropped stream goes unnoticed.** Nothing is replayed, so a host that loses its stream and never re-listens shows stale data indefinitely. One that re-listens without re-reading misses every change made while it was away, as [the stock example](#resource-change-notifications) showed (`mcp/server/subscriptions.py`). Catch `SubscriptionLost`, re-listen, then re-read.

**Completion becomes an enumeration endpoint.** A handler that completes from every record, or trusts `context.arguments` for access, lets anyone list what exists, one keystroke at a time. A host that sends a request per keystroke also multiplies the load ([completion](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/completion)). Scope suggestions to the caller, cap them, rate-limit per caller, and watch completion request rates as you would login attempts.

**Prompt errors look like crashes.** The SDK answers an unknown prompt or a missing argument with -32603, as [the prompt example](#workflows-as-prompts) showed, so a host's logs mix users' mistakes with server faults. Raise `MCPError` with `INVALID_PARAMS` for every argument you reject, and alert on the internal errors that remain.

**Working rule:** Before resources and prompts go to production, test them with two callers. Neither may see, complete or watch the other's records, and neither should see a list change without a list-changed notification. Check that every `resources/read` of a user's data carries the `private` scope, and that a host recovers from a dropped stream by re-listening and re-reading.

## Decisions this chapter made {#resources-and-prompts-decisions}

- **The shop's policies are six static resources** at `shop://policies/{slug}`, served from Markdown files written for the book, with the refund policy at priority 1.0 as a judgement.
- **The policies' list and reads are `public` for an hour,** because they are the same for every caller. Orders keep the `private` default.
- **Orders are a resource template,** `shop://orders/{order_id}`, over the same API endpoint as `get_order_status`, and a miss raises `ResourceNotFoundError` for -32602.
- **The SDK's `ResourceSecurity` stays on,** and handlers still check the format of what they're given.
- **Completion offers only the caller's own orders,** newest first and bounded by the API's limit of 100, with `has_more` when the API held more back. Another customer's order reads as not found.
- **Who the server acts for comes from the environment** over stdio. Over HTTP, the token's subject says who is calling: for the support host, a member of staff, with the customer taken from the ticket record ([Authorize clients with OAuth](#authorization), [Keep the server from acting as a confused deputy](#confused-deputy)).
- **The stock example keeps counts in the server's memory,** standing in for the shop's stock system, and the `set_on_hand` tool publishes the update from the code path that changes the count.
- **Change notifications use `subscriptions/listen`,** never `resources/subscribe`, and the client re-reads on every event and every new stream.
- **No model call in this chapter.** The prompt's messages are the input to a model turn that the book's host loop makes later.
- **The `review_refund` prompt embeds the refund policy,** checks its arguments' formats first, and raises `MCPError` with `INVALID_PARAMS` itself.
- **Data the host attaches is a resource, and data the model looks up is a tool.** A record can be both, served from one code path.
