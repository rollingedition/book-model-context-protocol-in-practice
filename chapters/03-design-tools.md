---
chapter_id: design-tools
---

# Design tools a model can use

By the end of this chapter you can turn the API of [the shop](#the-shop), a small online store for kitchen and garden goods, into Model Context Protocol tools whose names, descriptions, input schemas, results and errors a model can act on, and measure how a change to one description changes which tool a model picks. What follows holds for revision {{out:tools-from-endpoints:protocol revision}} of the specification and for the Python SDK, `mcp` {{version:mcp}}.

Its support team answers customer tickets through a host, so every tool in this chapter exists to help a model answer a ticket.

A Model Context Protocol (MCP) server's tools are the only part of the shop a model sees. The model never reads the shop's code or its API. It reads each tool's name, description and input schema, picks one, and fills in its arguments. Then it reads whatever comes back, including any error. So a tool is an interface designed for a reader that can't ask questions, and every part of the definition is a place to help that reader or mislead it.

The shop's server, `shop-support`, has one tool so far: `get_order_status`, from [Wrap one endpoint as a tool](#wrap-an-endpoint-as-a-tool). [What MCP adds to an API](#what-mcp-adds) gave it a resource and a prompt as well, but one tool can't answer most tickets. Customers also ask which order was which, what a refund would be, to be refunded, and whether a product is in stock. This chapter builds the full tool set for those tickets, and tests each design choice.

## Shape tools around tasks, not endpoints {#tasks-not-endpoints}

The shop's API has five endpoints for orders, stock and new refunds, and the quickest way to give a model all five is one tool per endpoint. Generators that turn an API's routes into MCP tools do exactly that. Tools shaped like the API suit a programmer who already knows the workflow. A model has to rebuild the workflow from the tools' names every time: look this up, then compute that, then post it.

The alternative is to shape each tool around a task the model performs for the person it's helping. A task tool may call one endpoint, combine two, or split one in two, and it hides the steps a model would get wrong. Tools are model-controlled: the model decides which to call and with what ([server features](https://modelcontextprotocol.io/specification/2026-07-28/server)). The shape of the tools decides which decisions are left to the model.

This chapter rebuilds `shop-support` in `lib.shop_tools`, a shared module, so that every example and every later chapter uses the same five tools. The book still calls it **the shop's server**. Its resource and prompt return in [Serve data as resources and prompts](#resources-and-prompts). Each of its tools serves one kind of ticket:

- `find_orders` searches one customer's orders by status or by the date placed. It calls the API's order list and adds a date filter the API doesn't have.
- `get_order_status` looks up one order by its ID, as in chapter 1.
- `quote_refund` works out what a refund would be, and changes nothing.
- `issue_refund` makes the refund from a quote. Above the policy's limit the shop's API holds it for a person ([Return an input request instead of a result](#return-an-input-request)); within the limit, nothing in this chapter asks anyone. **Consent**, the host asking the user before a call that changes something, arrives in [Ask for consent before side effects](#consent-before-side-effects).
- `check_stock` reports one product's stock in each warehouse.

The module also holds `endpoint_tools()`, the list a one-tool-per-endpoint generator writes for the same API, so the two shapes can be compared. Both lists print with each tool's required arguments. Then ticket T-0024, "please refund the aluminium muffin tray on o2415", runs both ways.

[Two tool lists for the shop's API](../examples/tools-from-endpoints.py)

The endpoint tools mirror the API. `get_orders` requires no argument at all, so a model can list every customer's orders. `post_refunds` requires an `order_id` and an `amount`. And `post_stock_by_sku_recount` puts a slow warehouse job in front of a support model. When a model sends the whole order's total to `post_refunds`, the API accepts it with status {{out:tools-from-endpoints:post_refunds status}} and records a refund of €{{out:tools-from-endpoints:post_refunds amount}}, for a ticket about one product. The API checks only that the amount isn't more than the order's total, so the model's arithmetic is the only check on the money.

The task tools move those decisions into the server. `find_orders` requires a `customer_id`, so a search covers one customer, though the model still picks which one. `quote_refund` takes the order and, optionally, one SKU, and the server works out the amount itself: €{{out:tools-from-endpoints:quote_refund amount}} for the muffin tray's line. That amount is within the refund policy's limit, as the quote's `within_limit` field says. `issue_refund` takes no amount at all, only the quote's ID. The stock recount stays off this server; [Stream progress on a long call](#stream-progress) puts it on a server of its own.

Splitting the refund in two also follows most of the specification's guidance for state across calls. The pinned revision has no protocol session, so a tool that needs state from an earlier call gets it as an explicit handle: one tool returns an ID, and the next takes it as an argument. The guidance asks that the creating tool's description state how long the handle lives, and that a call with an expired or unknown handle return a tool execution error that says so ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Stateful tools"). In the shop's server, `quote_refund` returns a `quote_id` valid for {{out:refund-quote-structured:quote lifetime minutes}} minutes, and its description says so.

What the server doesn't do yet matters as much. It trusts the `customer_id` and order IDs the caller sends, so a model, or a ticket written to mislead one, can list any customer's orders and quote any order. Whoever holds a `quote_id` can spend it. The guidance asks for a handle "with sufficient entropy (e.g., a UUIDv4)" on a server without authentication, and, on one with it, a check of the caller's authorization against the handle "on every call" ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Stateful tools"). The shop's quote IDs come from Python's `secrets` module, so no one can work one out from the order, but they're only 40 bits and bound to no customer. [Secure tools against misuse](#mcp-security) takes the acting user from the verified token's subject, never from an argument. Where customers sign in, that is the customer. At the support desk it is a member of staff, and the customer comes from the ticket record the server looks up and checks ([Keep the server from acting as a confused deputy](#confused-deputy)).

**Working rule:** Start from the tasks in your tickets or logs, not from your routes, and give each task one tool. Move every decision the model shouldn't make into the server, such as an amount or a sequence of calls. Use a handle when one task needs the result of another, state its lifetime in the description of the tool that creates it, make it unguessable, and check on every call that it belongs to the caller. Expose an endpoint as it stands only when the task and the endpoint are the same, as `check_stock` and `GET /stock/{sku}` are.

## Write descriptions the model reads {#write-tool-descriptions}

The task tools from [the previous section](#tasks-not-endpoints) help only if the model picks the right one, and it picks from what the host shows it. The book's host loop, `lib.host`, shows the model each tool's name, description and input schema. The specification calls the description a "hint" that clients can use "to improve the LLM's understanding of available tools" ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `Tool.description`).

Most published descriptions are poor. One study of 856 tools on 103 servers found that 97.1% had at least one defect, and that 56% didn't say plainly what the tool is for ([Hasan and others, 2026](https://arxiv.org/abs/2602.14878)). In a controlled test with two tools that had identical interfaces, editing only one tool's description gave it more than 10 times the usage of the original with two of the models tested ([Faghih and others, 2025](https://arxiv.org/abs/2505.18135)). Longer isn't automatically better. In the first study, fully rewritten descriptions raised task success by a median 5.85 points, but added 67% more steps and made 1 case in 6 worse.

A description that helps says four things: what the tool does, when to use it rather than its neighbour, what its inputs look like, and what comes back. In the Python SDK a tool's description is its function's docstring, unless you pass `description=` to the decorator ([tools](https://py.sdk.modelcontextprotocol.io/v2/servers/tools/)). On Python {{version:python}}, the book's runtime, the SDK passes the docstring through as written (`mcp/server/mcpserver/tools/base.py`), so a docstring that runs over several lines sends its line breaks and indentation to the model. The shop's server keeps its descriptions in one dictionary, `DESCRIPTIONS`, and passes each one as `description=`.

The example shows eight tickets and the shop's five tools to the model three times, with a different set of descriptions each time. Only the descriptions differ.

- The **vague** set has one line per tool, of the kind an endpoint generator writes, such as "Refund quote."
- The **draft** set is the shop's first draft, written as docstrings.
- The **revised** set is the shop's second draft, written after reading the draft's results.

The eight were picked by hand from the shop's ticket queue, not sampled: two ask which orders a customer has, two where an order is, three about refunds, and one about stock. None carries injected instructions or a mistyped order ID. Before you run it, predict how many first calls the vague set and the draft each get right.

The model is the one every recording in this book uses: Qwen3-4B-Instruct-2507, run on the CPU with llama.cpp, as [Let a model choose the tool](#let-a-model-choose) set it up. The script `recordings/description_choices.py` made this recording, `description-choices`, sampling one reply per ticket and set at temperature {{out:vague-description-wrong-tool:sampling temperature}} with one fixed seed. Scoring looks only at the first tool the model calls, not at its arguments. A ticket's right first tool is the one the shop's data tags it with, with one change: `issue_refund` needs a `quote_id`, so a refund request starts with `quote_refund`.

[The same tickets with three sets of descriptions](../examples/vague-description-wrong-tool.py)

The vague set chose the right first tool for {{out:vague-description-wrong-tool:vague right}} tickets, and the draft did the same, {{out:vague-description-wrong-tool:draft right}}. Names and parameters alone carried the four order tickets and the stock ticket, so all three sets chose the same right tool for each. The draft's longer wording didn't help with the three refund tickets, where the choices differed. Ticket T-0006, about an order that "arrived with the enamelled saute pan cracked. what can you refund me", got `{{out:vague-description-wrong-tool:T-0006 vague}}` from the vague set and `{{out:vague-description-wrong-tool:T-0006 draft}}` from the draft.

The draft said what `quote_refund` does, but not that it makes looking the order up unnecessary. The revision says so in both tools. `get_order_status` sends refund questions to `quote_refund`, and `quote_refund` asks to be called first because "it checks the order itself". The revision changed more than that, though. It rewrote the opening of `quote_refund`'s description, and, passed as `description=` instead of as a docstring, it dropped the draft's line breaks and indentation. With all three changes, the revised set chose the right first tool for {{out:vague-description-wrong-tool:revised right}} tickets. The run doesn't show which change mattered.

The revision fixed the choice of tool but not the arguments: none of the three refund calls would have worked. For T-0006 the model sent the SKU {{out:vague-description-wrong-tool:T-0006 revised sku}}, the example in the `sku` parameter's own description, and none of the three SKUs it sent was on its order. [Report failures as tool results](#tool-errors) shows how the shop's server catches that mistake. T-0013's date was wrong with all three sets, as the next section shows.

Read these counts as one measurement. They come from one model at one seed, on eight tickets picked by hand, and another seed could change some choices. The revision was written after reading the results on the same eight tickets, so its score flatters it. [Measure how often the right tool is chosen](#tool-selection-accuracy) measures choices over the whole ticket queue, which is the test that decides.

**Working rule:** Write each description in two to four sentences: what the tool does, when to use it instead of the tool it's most often confused with, what its inputs look like, and what it returns. Pass it as `description=` rather than relying on a multi-line docstring, so the model reads exactly the text you wrote. Then record the model you ship choosing tools for real tickets, read the wrong choices, and change the descriptions those choices point to. Change one thing per recording when you need to know which change worked, and check the result on tickets you didn't use to write the change.

## Type inputs with JSON Schema {#type-tool-inputs}

A description from [the previous section](#write-tool-descriptions) tells the model what a tool wants, and an input schema makes the server enforce it. Every tool has an `inputSchema`, a JSON Schema object whose root has `"type": "object"`. At the pinned revision any JSON Schema 2020-12 keyword may appear in it ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)), including `oneOf`, `if`, `then`, `else` and `$ref` ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `Tool.inputSchema`). A schema with no `$schema` field is read as 2020-12, and implementations "MUST NOT" automatically follow a `$ref` that points to a network URI ([base protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic)), so by default a schema can't make a client download anything.

The schema does two jobs. It shows the model the shape of a valid call, and it lets the server reject an invalid one before any of the tool's code runs. The specification makes the server's half a requirement: servers "MUST" validate all tool inputs ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Security considerations").

In the Python SDK the schema comes from the function's type hints, and pydantic's `Annotated[..., Field(...)]` adds constraints to them ([tools](https://py.sdk.modelcontextprotocol.io/v2/servers/tools/)). The shop's server defines its ID types once. `OrderId` is a string with `pattern=r"^O-\d{4}$"`, and `CustomerId` and `Sku` work the same way. `find_orders` takes `status` as a `Literal` of the five order statuses, `placed_since` as a `date`, and `limit` as an integer with `ge=1, le=50`. The schema the SDK built from those hints prints first. Then `find_orders` is called three ways: with three bad arguments at once, with a number sent as a string, and with the date the recorded model sent for ticket T-0013 in [Write descriptions the model reads](#write-tool-descriptions). That ticket asked for orders "since 12 Jun".

[Typed inputs reject bad arguments](../examples/reject-bad-arguments.py)

Each hint became a schema keyword: `pattern` for the customer ID, `enum` for the status, `"format": "date"` for the date, and `minimum` and `maximum` for the limit. The call with three bad arguments came back as one failed result, and its text names every argument that failed, the rule it broke and the value sent. A model can correct all three in its next call.

The SDK is more lenient than the schema in one way. The schema says `limit` is an integer, but the call with `"5"` succeeded and returned {{out:reject-bad-arguments:string limit orders}} orders. Pydantic, which validates the arguments, converts a numeric string to an integer by default. That's harmless here. Where a string and a number must stay distinct, declare the field with `Field(strict=True)`. Pydantic also drops, without an error, any argument the schema doesn't declare (`mcp/server/mcpserver/utilities/func_metadata.py`), which [Keep the server from acting as a confused deputy](#confused-deputy) relies on.

The date is the mistake no schema catches. The ticket's "12 Jun" has no year, and the model sent `2023-06-12`, a valid date three years before the shop's data ends. The call passed validation and returned {{out:reject-bad-arguments:since 2023-06-12 orders}} orders, every order the customer has, instead of the {{out:reject-bad-arguments:since 2026-06-12 orders}} placed since June 12 of the shop's year. The schema checks the form. The meaning has to come from somewhere else, such as the host putting the ticket's date in the prompt, or the description saying how to read a date without a year.

The specification isn't consistent about where a rejected argument goes. Its tools page lists input validation among tool execution errors, which come back as a result. Its schema reference lists "invalid tool arguments" under the JSON-RPC error `-32602` ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `InvalidParamsError`). The SDK follows the tools page, and so does this book. Clients "SHOULD" pass execution errors to the model, but only "MAY" pass protocol errors, which the specification says are "less likely to result in successful recovery" ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Error handling"). A result is the path a model can count on reading.

**Working rule:** Type every argument as narrowly as the API allows: a pattern for IDs, an enum for fixed values, bounds for counts and a format for dates. Let the SDK reject bad calls before your code runs, and return every failure at once. Don't trust the schema with meaning, because a valid date can still be the wrong date. Check what the schema can't express inside the tool, and say in the description how to fill a value that tickets often leave incomplete.

## Return structured content with an output schema {#structured-output}

The inputs from [the previous section](#type-tool-inputs) have a schema, and results can have one too. A tool may declare an `outputSchema`, and its result then carries `structuredContent`: the same data as JSON that a program can read without parsing text ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Structured content"). When a tool declares an output schema, the server "MUST" return results that conform to it, and clients "SHOULD" validate them. A tool that returns structured content "SHOULD" also return it serialized as JSON in a text block, for clients that read only text. The same section notes that `structuredContent` is the server's result data, unrelated to a model's "structured outputs".

The output schema serves the host's code more than the model. Code can branch on a field called `within_limit` instead of searching a sentence for "exceeds", and a test can check a field instead of a string. At the pinned revision `structuredContent` may be any JSON value ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)). Revision 2025-11-25 required an object ([tools at 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)), which [Migrate a 2025-era server](#migrate-from-2025) covers.

The Python SDK builds the output schema from the function's return type. Primitive types, `None`, lists and unions are wrapped in `{"result": ...}`. Pydantic models, `TypedDict`s, dataclasses and `dict[str, ...]` aren't ([structured output](https://py.sdk.modelcontextprotocol.io/v2/servers/structured-output/); `mcp/server/mcpserver/utilities/func_metadata.py`). `quote_refund` returns `RefundQuote`, a pydantic model with the quote's ID, the order, the SKU, the amount, the policy limit, `within_limit` and the quote's lifetime in seconds. Quoting order O-2289 for ticket T-0006 with no SKU, so the quote covers the whole order, shows the structured result. A second server then has one tool that returns the same amount as a bare string, to show the wrapper.

[A refund quote as structured content](../examples/refund-quote-structured.py)

The quote's output schema requires {{out:refund-quote-structured:output schema requires}}, and the structured content has each of those fields. Its amount, €{{out:refund-quote-structured:amount}}, is more than the policy's limit, so `within_limit` is false, and [Return an input request instead of a result](#return-an-input-request) is where that flag starts a person's confirmation. The text block holds the same JSON, as the code checks.

The bare tool shows where the SDK lags the specification. The pinned revision allows a string as structured content, but the SDK still wraps any value that isn't an object in `{"result": ...}`, and publishes an object schema to match (`mcp/server/mcpserver/utilities/func_metadata.py`). The bare tool's structured content is `{{out:refund-quote-structured:bare structured content}}`, not the bare string. A host written to the specification that expects a string gets an object instead. Return a model from every tool and the question never comes up.

Both sides check structured content. The SDK's client validates every successful result against the output schema it cached from `tools/list`. It raises a `RuntimeError` when the structured content doesn't match, or when a tool with an output schema returns none (`mcp/client/session.py`, `validate_tool_result`). The SDK's server also checks a tool's return value against the tool's own model before sending it (`mcp/server/mcpserver/utilities/func_metadata.py`), so a mismatch fails on whichever side changed.

**Working rule:** Give every tool a pydantic model as its return type, so the SDK publishes an output schema, returns structured content with no wrapper, and adds the text block for you. Put a field in the model for each decision the host's code makes, such as `within_limit`, rather than leaving it in a sentence. Return a bare string only from a tool whose result no code reads.

## Report failures as tool results {#tool-errors}

The quote from [the previous section](#structured-output) is the result when a call works. When a call fails, the specification gives it one of two paths ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Error handling"). A **protocol error** is a JSON-RPC error, for an unknown tool, a request that doesn't fit the `tools/call` schema, or a server failure. A **tool execution error** is an ordinary result with `isError` set to true, for an API failure, an invalid input or a broken business rule. Execution errors, the specification says, "contain actionable feedback that language models can use to self-correct", and clients "SHOULD" pass them to the model.

Because clients SHOULD pass execution errors to the model and only MAY pass protocol errors, the path decides who can fix the failure. In the Python SDK, raising `ToolError` produces an execution error with your message. Raising `MCPError` produces a protocol error. Any other exception counts as a crash: the result says only "Error executing tool" and the tool's name, and the exception stays in the server's log ([handling errors](https://py.sdk.modelcontextprotocol.io/v2/servers/handling-errors/)). The SDK's guide puts the choice as a question: could a smarter model have avoided this failure? If so, raise `ToolError`, and if not, raise `MCPError`.

The shop's server follows that test. A missing order, an order that isn't refundable, a SKU that isn't on the order, and an unknown or expired quote are all `ToolError`s, each with a message saying what to do instead. A 401 from the shop's API means the server's key is wrong, which no model can fix, so the server raises `MCPError` with JSON-RPC's internal error code. Anything else, such as the API being down, stays a crash. Five calls fail on purpose, listed in the order the code makes them:

1. ticket T-0006's recorded call from the revised descriptions in [Write descriptions the model reads](#write-tool-descriptions), with its invented SKU;
2. `issue_refund` with a quote the server never issued;
3. a tool that doesn't exist;
4. a call to a server started with the wrong key;
5. a call after the shop's API has stopped.

[Five failures, and which path each takes](../examples/tool-error-versus-protocol-error.py)

The invented SKU came back as an execution error, and its text gives the model what it lacked: "{{out:tool-error-versus-protocol-error:wrong SKU says}}" A model that reads that can call again with the right SKU. The unknown quote's message works the same way: "{{out:tool-error-versus-protocol-error:unknown quote says}}"

The unknown tool shows a deviation from the specification. The specification's example answers an unknown tool with the JSON-RPC error `-32602`, but the SDK's server returns an execution error instead (`mcp/server/mcpserver/tools/tool_manager.py`). The result is flagged as an error, and its text is "{{out:tool-error-versus-protocol-error:unknown tool says}}". For a model that's the more useful answer, since it shows that the name was wrong. A host that counts protocol errors to spot a confused model won't see these, so count execution errors too.

The wrong key took the other path. The client raised `MCPError`, and the example caught it as the JSON-RPC error `{{out:tool-error-versus-protocol-error:rejected key JSON-RPC error code}}`, with the message "{{out:tool-error-versus-protocol-error:rejected key JSON-RPC error message}}" The host's code sees that, and the model sees it only if the host passes it on. When the API was down, the model got only "{{out:tool-error-versus-protocol-error:API down says}}", and the exception stayed in the server's log ([handling errors](https://py.sdk.modelcontextprotocol.io/v2/servers/handling-errors/)).

One more mistake skips both paths: a tool that returns an error message as an ordinary string. The SDK sends a returned string with `isError` false, so the model reads the error as a successful answer ([handling errors](https://py.sdk.modelcontextprotocol.io/v2/servers/handling-errors/)). Raise instead.

**Working rule:** Raise `ToolError` for every failure a model could correct, with a message that names what was wrong and what to send instead, including the valid values when there are few. Raise `MCPError` only for failures no model can fix, such as configuration, and let unexpected exceptions stay generic so internal details stay on the server. Never return an error as a plain string.

## Mark what a tool changes with annotations {#tool-annotations}

The errors in [the previous section](#tool-errors) tell the model what went wrong after a call. Annotations tell the host what a call will do before it's made, so the host can decide whether to ask for consent first. The specification wants a person able to say no to any tool call, as [Let a model choose the tool](#let-a-model-choose) quoted. A tool's `annotations` hold a title and four hints ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `ToolAnnotations`):

- `readOnlyHint`: the tool doesn't change its environment. The default is false.
- `destructiveHint`: a tool that changes something may destroy or overwrite data, rather than only add to it. The default is true.
- `idempotentHint`: calling the tool again with the same arguments has no further effect. The default is false.
- `openWorldHint`: the tool reaches entities outside a closed domain, such as the web. The default is true.

`destructiveHint` and `idempotentHint` mean something only when `readOnlyHint` is false. The defaults describe the worst case, so to a careful host a tool with no annotations is destructive, not idempotent, and reaches the open world. In the Python SDK you pass `ToolAnnotations(read_only_hint=..., destructive_hint=..., idempotent_hint=..., open_world_hint=...)` to the `tool()` decorator ([tools](https://py.sdk.modelcontextprotocol.io/v2/servers/tools/)).

The shop's four reading tools carry `read_only_hint=True` and `open_world_hint=False`, because they only read the shop's own API. `issue_refund` is the one tool that changes something, and its hints are judgements. We set `destructive_hint=False`, because a refund adds a record and never overwrites one, and `open_world_hint=False`, because the tool talks only to the shop's API, which records the request for the shop's staff to pay. `idempotent_hint=True` is the hint that needs a guarantee behind it: the server returns the same refund for the same `quote_id`.

The code works out what a host should assume about each tool, filling in the default wherever a hint is missing, and applies a consent rule to the result. It includes the endpoint tool `post_refunds`, which has no annotations. Then it calls `issue_refund` twice with one quote, and `POST /refunds` twice with one amount.

[What the annotations tell a host](../examples/annotate-the-refund-tool.py)

Each of the four reading tools comes out as `{{out:annotate-the-refund-tool:find_orders assumes}}`, and `issue_refund` as `{{out:annotate-the-refund-tool:issue_refund assumes}}`: it isn't read-only, but it is neither destructive nor open-world. The unannotated `post_refunds` comes out as `{{out:annotate-the-refund-tool:post_refunds assumes}}`, because that's what the defaults say. A host that asks for consent before any tool that isn't read-only asks before both refund tools and none of the others. The shop's host gets that rule in [Ask for consent before side effects](#consent-before-side-effects).

The two pairs of calls show why `idempotent_hint=True` is safe to claim for `issue_refund` and wouldn't be for the endpoint. Two calls of `issue_refund` with one quote returned {{out:annotate-the-refund-tool:issue_refund first refund}} and {{out:annotate-the-refund-tool:issue_refund second refund}}: one refund, twice. Two identical posts to the API created {{out:annotate-the-refund-tool:post_refunds first refund}} and {{out:annotate-the-refund-tool:post_refunds second refund}}: two refunds. The shop's API has no once-only check, so the server adds one. It stores the refund against its quote, under a lock, because the SDK runs synchronous tools on worker threads and two calls can arrive together.

### Treat annotations as hints, not guarantees {#annotations-are-hints}

Nothing in the protocol checks an annotation against what the tool does. The specification says annotations "are not guaranteed to provide a faithful description of tool behavior", and that clients "MUST" consider them untrusted unless they come from trusted servers ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `ToolAnnotations`; [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)). A server that marks a refund tool read-only gets past any host that believes it. [Catch poisoned tool descriptions](#tool-poisoning) shows a server whose tool definitions lie on purpose.

For the server's author, a hint is a promise the code has to keep. The shop's `issue_refund` is idempotent because the quote store makes it so, not because the annotation says so. If a restart lost the store, a retried call would get "There is no quote" instead of a second refund, which is still safe. Keep the check in the server, and treat the annotation as a description of it.

**Working rule:** Annotate every tool, because leaving the hints out tells a careful host to assume the worst. Mark a tool idempotent only when the server enforces it, and keep refunds, payments and anything else that must happen once behind a check on the server. As a host, use annotations from a server you trust to decide what to show the user, never as permission to skip consent ([Ask for consent before side effects](#consent-before-side-effects)), and treat every other server's annotations as unverified claims.

## Keep the tool list small {#keep-the-tool-list-small}

The host puts every tool from [the previous sections](#tool-annotations), with its description and input schema, in the model's prompt on every turn, and the model reads the whole list before it chooses. More tools cost more tokens, and they also make the choice harder. In one test with MCP servers, retrieving only the tools relevant to a request more than tripled selection accuracy, from 13.62% to 43.13% ([Gan and Sun, 2025](https://arxiv.org/abs/2505.03275)). On edge devices, offering small models fewer tools raised their function-calling success and cut execution time by up to 70% ([Paramanayakam and others, 2025](https://arxiv.org/abs/2411.15399)). Both are single studies with their own setups, so read them as the direction of the effect, not as numbers for the shop.

The cost is easier to measure than to guess. When the recording script ran, it also counted, with the recording model's tokenizer, how many tokens each tool takes in the host's prompt. The check adds up those counts for the revised tools, the vague ones from [Write descriptions the model reads](#write-tool-descriptions) and the endpoint tools, and measures their bytes. It refuses to run if a tool has changed since its tokens were counted.

[What the tool list costs in the prompt](../examples/tool-list-size.py)

Most of the cost is in the schemas. The shop's five revised tools take {{out:tool-list-size:revised prompt tokens}} tokens in the prompt, against {{out:tool-list-size:prompt without tools tokens}} for the rest of the host's instructions. With vague descriptions they take {{out:tool-list-size:vague prompt tokens}}, so the revised descriptions make up about a third of the list's cost. The endpoint tools take {{out:tool-list-size:endpoint prompt tokens}}: one-line descriptions, and schemas with no patterns, enums or descriptions of their own. The revised schemas are the same ones that caught the bad arguments in [Type inputs with JSON Schema](#type-tool-inputs). The full `tools/list` result is larger still, because it also carries output schemas, titles and annotations that the host's prompt leaves out, as the output's byte counts show.

At about {{out:tool-list-size:revised tokens per tool}} tokens a tool, 20 tools like these would take about {{out:tool-list-size:20 such tools tokens}} tokens before the model reads the ticket: nearly all of the {{out:tool-list-size:recording context tokens}}-token context the recordings run with. That figure is arithmetic, not a measurement, and real tools vary in size. A shorter list also lowers the chance that two descriptions overlap, which was the draft's problem with `get_order_status` and `quote_refund` ([Write descriptions the model reads](#write-tool-descriptions)).

A server keeps its list short by serving one audience. The shop's server serves support tickets, so the stock recount isn't on it. At the pinned revision a server can't trim its list for one connection, though the list may vary by the authorization a request presents, and it comes in a fixed order ([Cache list results](#cache-list-results)). That section covers the cache hints on the result, and [Scope tools by what the token allows](#scopes-per-tool) shows a list that varies by token.

**Working rule:** Give each server one audience and the few tools that audience's tasks need, and measure what the list costs in your host's prompt. Spend the tokens on schemas and on the sentence that separates two tools a model confuses, and cut description text that repeats the schema. When a host needs more tools than its model chooses among well, split them across servers and connect only the servers a conversation needs, rather than making one server's list depend on the connection.

## What goes wrong in production {#design-tools-in-production}

The shop's server works for eight tickets on one machine. Across a whole ticket queue and a real deployment, tool design fails in a few recognizable ways.

**Two tools that a model can't tell apart.** The draft descriptions in [Write descriptions the model reads](#write-tool-descriptions) let the model look up orders it should have quoted. In production the sign is a tool called far more or far less often than the tickets it serves, or two tools called one after the other where one would do. Count tool choices against labelled tickets ([Measure how often the right tool is chosen](#tool-selection-accuracy)), and fix the sentence that separates the two tools.

**Example values the model sends as real ones.** For one of the three refund tickets, the model sent the example SKU from the `sku` parameter's description as if the customer had written it. KG-1031 is a real product, so without the check that the SKU is on the order, the tool would have quoted the wrong one. The shop's descriptions keep their real example IDs only because the recording was made with them. The sign is an example value that turns up in arguments far more often than real traffic explains. Keep checks that tie each argument to the record it belongs to, and choose examples that can't be real, such as IDs outside the range in use.

**An output schema that drifts from the code.** The SDK's client validates each result against the output schema it cached from `tools/list`, and raises `RuntimeError` when they disagree (`mcp/client/session.py`). A server released with a removed or changed field, under a client that cached the old list, fails every call to that tool. The sign is `RuntimeError: Invalid structured content` in the host after a server release. Treat output schemas as a contract and test them ([Check schemas as a contract](#schema-contract-tests)).

**Crashes the model can't read.** Every exception that isn't a `ToolError` or an `MCPError` reaches the model as "Error executing tool" and nothing more. The sign is a model that retries the same call, or gives up, with no reason in the conversation. Read the server's standard error, and turn each failure a model could fix into a `ToolError`.

**Handles that die with the process.** The shop's quotes live in the server's memory. A restart loses every open quote, and the model gets "There is no quote" for a quote it made minutes earlier. Several replicas behind one address lose more, because a quote made on one replica is unknown to the next. Keep handles in shared storage once the server runs as more than one process ([Run replicas without sticky sessions](#scale-without-sessions)).

**Tool names that collide across servers.** A host connected to two servers can see two tools called `get_order_status`. The specification says hosts "SHOULD" disambiguate, for example by prefixing each name with a server identifier ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), "Tool names"), and [Name tools across servers](#namespace-tools) builds that.

**Personal data in headers.** A parameter marked `x-mcp-header` has its value copied into an HTTP header on Streamable HTTP, where proxies and logs can see it. The specification says servers "SHOULD NOT" mark sensitive parameters, personal data included, that way ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)), so never mark a customer ID or an email. [Serve over Streamable HTTP](#streamable-http) covers the header.

**Working rule:** Before the shop's tools go to production, record the model you ship choosing tools for a labelled sample of real tickets, check that every failure a model could fix comes back as a `ToolError` with a useful message, and put each output schema under a contract test. After release, watch tool-choice counts, example values in arguments, and `RuntimeError`s in the host.

## Decisions this chapter made {#design-tools-decisions}

- **Five task tools, not one tool per endpoint:** `find_orders`, `get_order_status`, `quote_refund`, `issue_refund` and `check_stock`, in `lib.shop_tools`. The stock recount stays off the support server.
- **Refunds split into a quote and an issue.** `quote_refund` computes the amount and returns a `quote_id` valid for {{out:refund-quote-structured:quote lifetime minutes}} minutes; `issue_refund` takes only that handle.
- **The server trusts the caller's `customer_id`,** and a `quote_id` is random but short and bound to no customer. [Secure tools against misuse](#mcp-security) addresses it by taking the acting user from the verified token, not from an argument.
- **No consent yet.** Within the policy's limit, `issue_refund` runs without asking a person; the host's consent comes in [Ask for consent before side effects](#consent-before-side-effects).
- **Descriptions are passed as `description=`,** from one dictionary. Each says what the tool does, when to use it instead of its neighbour, its inputs and its result. They were revised once, against one model's recorded choices on eight tickets, and the run credits the revision as a whole, not any one sentence of it.
- **Every argument is typed narrowly** with `Annotated[..., Field(...)]`: patterns for IDs, an enum for status, bounds for `limit`, a date for `placed_since`.
- **Every tool returns a pydantic model,** so the SDK publishes an output schema and sends structured content with no `{"result": ...}` wrapper.
- **Rejected arguments come back as execution errors,** as the specification's tools page and the SDK have them, so the model can read them and correct its call.
- **`ToolError` for what a model can fix,** with the valid values in the message; `MCPError` for a rejected API key; everything else stays a generic crash.
- **Every tool is annotated.** The reading tools are read-only and closed-world. `issue_refund` is additive, closed-world and idempotent, with the server's once-only check behind the hint.
- **Annotations from other servers are untrusted,** and consent never depends on them alone.
- **Quotes live in the server's memory,** which holds for one stdio process. Replicas need a shared store.
