---
chapter_id: multi-round-trip-requests
---

# Ask the user in the middle of a call

By the end of this chapter you can make the shop's refund tool stop in the middle of a call and ask the person at the host to confirm a refund, with Model Context Protocol elicitation inside a Multi Round-Trip Request, on a server that keeps no call open while it waits for the answer. Everything holds for the specification at revision {{out:refund-needs-confirmation:protocol revision}} and the Python SDK, `mcp` {{version:mcp}}.

This book follows one case study throughout: a small online shop for kitchen and garden goods, which we call **the shop**, and whose support team answers customer tickets through a host. [Meet the shop and its API](#the-shop) introduces it. The shop's refund policy says that any refund above €150.00 needs a support lead to confirm it before it is issued. The shop's API enforces that limit by holding such a refund with the status `needs_confirmation`. In [Design tools a model can use](#design-tools), the shop's `issue_refund` tool passes that hold back to the model and stops there, so a refund the model was right to make waits until someone finds it in the back office.

The person who could confirm it is already at the host, reading the conversation. What the tool needs is a way to put one question to that person in the middle of the call, and carry on with the answer. The Model Context Protocol (MCP) gives a server that through **elicitation**, a structured question that the client shows the user. At the pinned revision the question travels inside a **Multi Round-Trip Request**: the server answers the call with an **input request** instead of a result, and the client calls again with the answer.

The chapter's server examples run themselves as earlier chapters' do: with no arguments, the file starts a client that launches the same file with `--serve` over stdio. The shop's API runs on loopback beside them.

## See why a stateless server can't wait for an answer {#why-calls-cannot-wait}

Before the pinned revision, a server that needed the user's input sent its own request to the client, `elicitation/create`, and waited for the reply while the tool call stayed open. The pinned revision removed that pattern. The specification says servers "MUST" send their requests to the client, `elicitation/create` among them, through the Multi Round-Trip Request pattern, that the previous pattern "is no longer supported", and that "This is a breaking change" ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)). Elicitation is the one such request this chapter uses, and it isn't deprecated. The other two, `sampling/createMessage` and `roots/list`, are, and [Replace sampling, roots and logging](#replace-deprecated-features) gives their replacements: a direct call to a model provider's API, and tool parameters, resource URIs or server configuration ([deprecated features](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)).

The reason is statelessness. At the pinned revision there is no handshake and no session, and every request carries its own version and capabilities in `_meta` ([Carry the version and capabilities on every request](#request-meta)). A request that waits on a reply from the client ties one server process to one open connection for as long as a person takes to answer. The specification states the aim: a server can ask for input "without requiring a shared storage layer across server instances or requiring stateful load balancing" ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)). The proposal behind the change, SEP-2322, adds that Streamable HTTP then depends less on long-lived streams, "which cause problems in a lot of environments" ([SEP-2322](https://modelcontextprotocol.io/seps/2322-MRTR)).

The Python SDK still has the old call. `ctx.elicit()` sends `elicitation/create` as a request from the server. On a connection at the pinned revision it fails with `NoBackChannelError`, an Invalid Request error, because there "the protocol forbids server-initiated requests" (`mcp/shared/transport_context.py`, `mcp/shared/exceptions.py`).

The shop's first attempt at a confirmation is written that way. The example's server takes chapter 3's tools from a shared module, `lib.confirmations`, which holds what this chapter's servers have in common: those tools, the key that protects round-trip state, and a record of answers already used. Its `issue_refund` calls chapter 3's version, which posts the refund to the shop's API. When the API holds the refund, it calls `ctx.elicit()` and waits. The client has an elicitation callback that plays a scripted user, who would release the refund if asked. It quotes order O-2289, whose whole refund is above the limit, and calls `issue_refund`.

[The 2025 way to confirm, on a connection at the pinned revision](../examples/refund-needs-confirmation.py)

The call failed with JSON-RPC error {{out:refund-needs-confirmation:error code}}, Invalid Request, and the message "{{out:refund-needs-confirmation:error message}}" The scripted user was asked {{out:refund-needs-confirmation:questions the user saw}} questions. Nobody saw the refund. Because the failure is a protocol error, not a tool result, the model never saw it either ([Report failures as tool results](#tool-errors)). The refund stays held in the shop's API, as it did in chapter 3.

The failure isn't in the tool's logic. The tool asked the protocol for something the pinned revision doesn't have: a channel from server to client in the middle of a call. Any code that waits for an answer inside a tool call has the same problem, whatever SDK it uses.

**Working rule:** Never wait inside a tool call for something only the client can give you. On a connection at the pinned revision, treat every call to `ctx.elicit()` or `ctx.elicit_url()` as a bug, and return an input request instead, as the next section does. Keep the old call only on a server that must also answer 2025-era clients, and only behind a check of `ctx.protocol_version` ([Serve old and new clients through the window](#serve-both-revisions)).

## Return an input request instead of a result {#return-an-input-request}

The failed call in [the previous section](#why-calls-cannot-wait) needed a channel the protocol doesn't have. A Multi Round-Trip Request turns the question around. Instead of a result, the server returns an `InputRequiredResult`, whose `resultType` is `"input_required"`, and the call is over. The result carries `inputRequests`, a map from keys the server chooses to the requests it needs answered, and `requestState`, an opaque string the client must send back. The server "MUST" include at least one of the two ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr); [schema](https://modelcontextprotocol.io/specification/2026-07-28/schema), `InputRequiredResult`).

Three rules bound what a server may ask, and when. Only `tools/call`, `prompts/get` and `resources/read` may answer with an input request, and servers "MUST NOT" send one on any other request. A server "MUST NOT" include an `elicitation/create` request if the client didn't declare the `elicitation` capability ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)). And because every result at the pinned revision carries `resultType`, a client treats an absent one, from an older server, as `"complete"`, and treats any value it doesn't recognize as invalid ([overview](https://modelcontextprotocol.io/specification/2026-07-28/basic)).

The shop's `issue_refund` uses all of this. It still calls chapter 3's version first, so the shop's API decides, with the policy's limit, whether the refund needs confirming, and the server never repeats the limit. Within one server process, chapter 3's tool returns the same refund for the same `quote_id` every time, so calling it on every round is safe; across processes it doesn't ([What goes wrong in production](#multi-round-trip-requests-in-production), "Records that only one process sees"). When the API holds the refund, the tool checks that the client declared form-mode elicitation, then builds the input request by hand: one `ElicitRequest` under the key `confirm`, whose form is one required yes-or-no field, `release`, and whose message names the amount and the order. As `requestState` it returns the refund's ID. On the retry, the tool checks that the state names the refund it found, and uses the state as the key of its record of answers.

The server passes `request_state_security=` to `MCPServer` with the policy that `confirmations.state_security()` makes, so that several replicas can later share one key. Here it is the SDK's default, a key made when the process starts. The client declares elicitation by passing a callback, and calls the tool through `client.session.call_tool(..., allow_input_required=True)`, which hands back the input request instead of answering it.

[A refund that asks for confirmation](../examples/refund-asks-to-confirm.py)

The call came back with result type `{{out:refund-asks-to-confirm:result type}}`, and its one input request is `{{out:refund-asks-to-confirm:input request confirm}}`. Its message reads "{{out:refund-asks-to-confirm:message}}" That is the question the host's user would see.

The question goes to whoever is at the host, and the answer is only as trustworthy as the host. An `accept` doesn't tell the server that a support lead answered, or that any person did: this chapter's own scripted callbacks answer by code. The specification says servers "MUST bind elicitation requests to the client and user identity" ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)). Over stdio, as here, the user is the host's local user, who launched the server, and the server has no other identity to bind to, so the shop trusts the host to put the question to a lead. Over HTTP, the server binds the question to the authenticated caller. The SDK's seal already includes the OAuth caller, so another user's retry fails. A server that needs a lead also checks for `refunds:write`, the scope only support leads hold, which gates `issue_refund` itself ([Scope tools by what the token allows](#scopes-per-tool); [Draw the trust boundaries](#trust-boundaries)).

The `requestState` the client received is not the refund ID the tool returned. The check that it starts with the SDK's `v1.` token prefix printed `{{out:refund-asks-to-confirm:request state sealed}}`: the SDK sealed the string on its way out. `MCPServer` encrypts every outgoing `requestState` with AES-256-GCM and verifies every one that comes back, binding it to the method, the tool's name, a digest of the arguments, the server's name and, when OAuth is in use, the caller (`mcp/server/request_state.py`). The tool reads and writes plaintext, and the client gets a token it can neither read nor change. The specification says clients "MUST NOT inspect, parse, modify, or make any assumptions about the `requestState` contents" ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)), and the seal makes that hold whatever the client intends.

Nothing waits on the server after this answer: no call stays open, and no connection is held for the lead. The shop's API holds the refund, as it did before the tool asked, and if no one ever answers, it stays held. That is the safe default for a step that pays money out.

The server does keep two records between the rounds, both in its own memory. The retry finds the refund through chapter 3's quote store, not in the state, and checks the answer against the record of answered states that [Keep round-trip state tamper-proof](#round-trip-state) explains. A retry that reaches another process finds neither record. [Run replicas without sticky sessions](#scale-without-sessions) moves both into storage that every replica shares.

**Working rule:** When a tool can't finish without the user, return an `InputRequiredResult` with one input request per question and a `requestState` that says what the retry must finish. Check the client's declared capabilities before you ask. Put in the state only what the tool needs to carry on, and let the SDK seal it. Make every side effect before the question either idempotent or harmless when no one answers, because the client may never call again.

## Resume the call with the answer {#resume-with-the-answer}

The input request in [the previous section](#return-an-input-request) ended the first call. The client finishes the work by sending the same request again: the same method, the same tool and the same `arguments`, plus `inputResponses`, keyed like the input requests, and the `requestState` echoed back exactly. The specification says the JSON-RPC `id` "MUST be different" on the retry, because the two "are independent requests", and that a `requestState` "MUST NOT" be used for any other request the client is sending ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)). The server may then finish, or answer with another input request.

For the shop, the second round is where a lead's yes turns into a refund. The tool from [the previous section](#return-an-input-request) finds the answer under `confirm` in `ctx.input_responses`. It gets the refund again from chapter 3's tool, and checks that `ctx.request_state` holds that refund's ID. When the answer is `accept` with `release` set, it asks the shop's API to release the held refund, `POST /refunds/{refund_id}/confirm`, and returns the refund. Anything else, and the refund stays held.

The example launches that server through `lib.wire`, the book's relay that records every JSON-RPC message, and plays the lead with a scripted answer. First, for order O-2289, it drives the loop by hand: one call, then one retry with the answer and the state. Then it quotes order O-1145 and calls `Client.call_tool`, with an elicitation callback that prints the question and answers yes.

[Retry with the answer, by hand and by the SDK](../examples/refund-confirmed-round-trip.py)

By hand, the refund for order O-2289 came back as {{out:refund-confirmed-round-trip:by hand}}: `requested` is the status of a released refund, no longer held. The trace shows the two requests behind it. The first call was {{out:refund-confirmed-round-trip:by hand, call}}. The retry was {{out:refund-confirmed-round-trip:by hand, retry}}. The two JSON-RPC IDs differ, and only the retry carries the answer and the state.

`Client.call_tool` hid the same loop. The callback was asked "{{out:refund-confirmed-round-trip:user was asked}}", the call returned {{out:refund-confirmed-round-trip:by Client.call_tool}}, and the code that called it saw one call and one result. On the wire there were still two requests: {{out:refund-confirmed-round-trip:Client.call_tool, call}}, then {{out:refund-confirmed-round-trip:Client.call_tool, retry}}. The SDK's client sends each input request to the matching callback, retries with the answers and the state, and gives up after `input_required_max_rounds`, 10 by default, with `InputRequiredRoundsExceededError` (`mcp/client/_input_required.py`). A round that carries only `requestState` and no questions is legal, and the schema's example for it is titled load shedding ([schema](https://modelcontextprotocol.io/specification/2026-07-28/schema)). The SDK's client waits 50 milliseconds before retrying such a round, doubling the wait up to 250.

The retry repeats the original request; it isn't a fresh tool call. In the SDK, the digest of the arguments is inside the sealed state, so a retry that changes them fails, as [Keep round-trip state tamper-proof](#round-trip-state) shows. A client that wants to send different arguments makes another call and gets another question.

**Working rule:** Use `Client.call_tool` with an elicitation callback in a host, and let the SDK run the rounds. Drive the loop yourself with `client.session.call_tool(..., allow_input_required=True)` only when the host must keep the state across a restart or show each round, and then repeat the arguments exactly. On the server, read the answer and the state together. When your server always sends a state, treat an answer that arrives without it, or with a state for another record, as a question never asked.

## Ask for structured input with elicitation {#elicitation-forms}

The confirmation in [the previous section](#resume-with-the-answer) asks one yes-or-no question. Elicitation can ask for more, in two modes ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)). In **form mode** the server sends a message and a schema, the client renders a form, and the answer returns through the client. In **URL mode**, which [the next subsection](#url-elicitation) covers, the server sends the user to a web page instead.

A form's schema is a flat object whose properties are primitives only: strings, with the formats `email`, `uri`, `date` and `date-time`; numbers and integers; booleans; and single- or multiple-choice enums. Every one of these types can carry a `default`. The user answers `accept`, with the content; `decline`, an explicit no; or `cancel`, a dismissed form. Servers "MUST handle cases where the user declines or cancels". The client "MUST" show which server is asking, offer decline and cancel, and let the user review a form before sending it ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation); [Answer input requests for the user](#answer-input-requests)).

The SDK has a shorter way. A tool parameter declared as `Annotated[T, Resolve(fn)]` is filled by running `fn`. When `fn` returns `Elicit(message, Model)`, the SDK renders the pydantic model as the form, checks the client's capability, returns the input request, and fills in the parameter on the retry. Annotating the parameter as `ElicitationResult[Model]` hands the tool all three outcomes to branch on, while a plain `Model` turns decline and cancel into a tool error (`mcp/server/mcpserver/resolve.py`).

In the shop, only whoever opens a returned parcel knows whether the item arrived damaged or wrong, and whether it can go back on sale, and the policy's reason decides whether shipping is refunded too. The example's `record_return` tool, for the line of KG-1043 on order O-1145, asks with a resolver. The form has three fields: `reason`, one of the refund policy's five reasons; `restock`, a boolean; and an optional free-text `note` of at most 200 characters. A scripted user accepts, then declines, then cancels; then a client without an elicitation callback calls.

[A form for what a returned parcel held](../examples/elicit-a-refund-reason.py)

The form reached the client with the fields {{out:elicit-a-refund-reason:form fields}}, of which only {{out:elicit-a-refund-reason:required}} are required, because the pydantic model gives `note` a default. Accept gave "{{out:elicit-a-refund-reason:accept}}" Decline gave "{{out:elicit-a-refund-reason:decline}}" Cancel gave "{{out:elicit-a-refund-reason:cancel}}" Each string tells the model what to do next: a decline stands, and a cancel leaves the question open.

The client without a callback declared no elicitation capability, and the SDK refused the call with JSON-RPC error {{out:elicit-a-refund-reason:client without elicitation}}, Missing Required Client Capability, before the tool ran (`mcp/server/mcpserver/resolve.py`). The shop's `issue_refund` makes the same check by hand.

**Working rule:** Use form mode for answers only the person at the host can give, and keep each form to the few fields the tool acts on, with enums wherever the answer is one of a known set. Declare forms with a resolver and a pydantic model, and take `ElicitationResult` when decline and cancel should lead different ways. Build the input request by hand only when you need to control the state yourself.

### Send sensitive steps to a URL {#url-elicitation}

A form's answer passes through the client, and possibly in front of the model. Servers "MUST NOT" use form mode for "passwords, API keys, access tokens, or payment credentials", and "MUST" use URL mode for them ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)). URL mode sends a message and a URL. The client "MUST NOT" pre-fetch the URL or its metadata, "MUST NOT" open it without the user's explicit consent, "MUST" show the full URL, and opens it so that neither the client nor the model can see the page. The server keeps personal data and credentials out of the URL, never sends a URL that signs the user in by itself, and "MUST" make sure that the user who completes the flow is the user who started it.

URL mode isn't how a client gets authorized to an MCP server ([Find the authorization server from the resource](#protected-resource-metadata)); it serves the server's own needs, such as a third-party service or a payment. In URL mode, `accept` means "the user has consented to the interaction", not that the interaction is finished ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)). The pinned revision removed the `elicitationId` field and the `notifications/elicitation/complete` notification, and the changelog says servers that need to match a flow across retries "encode their own identifier in `requestState`" ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)).

Paying out is the shop's step after a release: `pay_refund` pays a released refund, status `requested`, back to the order's card. The provider pays only under a lead's own account, signed in on its own page. The tool makes a random ID for the flow, puts it in `requestState`, and sends the lead to `https://pay.fernhill.example/connect/` followed by that ID, a reserved domain that never resolves. A set in memory stands in for the provider's record of finished flows; the example adds the flow to it before the third call.

[Send the lead to the provider's page](../examples/elicit-by-url.py)

The first call returned `{{out:elicit-by-url:first call}}`, with the URL `{{out:elicit-by-url:url}}`, cut before the random ID. After the scripted user accepted, the retry still returned `{{out:elicit-by-url:after accept}}`, because accepting meant only that the lead agreed to open the page. Once the provider had recorded the sign-in, the next retry gave `{{out:elicit-by-url:after sign-in}}`.

The example leaves out the check that the person who signs in is the one who was asked; it needs the caller's identity from [Get a token with PKCE](#authorization-code-with-pkce).

**Working rule:** Send anything secret, and anything that signs a person in to another service, through URL mode, never through a form. Put the flow's own ID in `requestState`, treat `accept` as "the user went to the page", and decide on each retry from the server's own records whether the flow has finished. Check that the person who finishes a flow is the one who started it.

## Keep round-trip state tamper-proof {#round-trip-state}

The confirmed refund in [Resume the call with the answer](#resume-with-the-answer) depended on the client returning the `requestState` it was given, and nothing obliges a client to be honest. The specification says servers "MUST treat `requestState` as an attacker-controlled input". When the state influences authorization, resource access or business logic, servers "MUST protect its integrity (e.g. HMAC or AEAD)" and reject state that fails the check. To narrow replays, a server "SHOULD" bind the state to the authenticated user, a short expiry and the request it came from. None of that makes a state single-use, and a server for which a state must be used at most once "MUST enforce that invariant server-side" ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)).

The SDK's seal covers the first part. Every check it makes, for a changed token, an expired one, the wrong request, the wrong caller or an unknown key, gives the client the same JSON-RPC error, -32602 with the message "Invalid or expired requestState", and writes the real reason only to the server's log (`mcp/server/request_state.py`). A client learns nothing from a failed attempt. The seal keeps no record of which tokens it has already accepted, though, so the second part is the server's job.

For the shop, a replayed confirmation would be a second release of money. The example sends the retry from [Resume the call with the answer](#resume-with-the-answer) wrongly in three ways, then correctly, then correctly again:

1. with one character of the sealed `requestState` changed;
2. with the scripted lead's yes but no state, as though answering a question the server never sent;
3. with the right state but another quote's `quote_id`;
4. as an honest retry;
5. as the same honest retry, sent a second time.

[Tamper with the state, then replay it](../examples/tampered-round-trip-state.py)

The changed token came back as `{{out:tampered-round-trip-state:one character changed}}`, and so did the swapped arguments: `{{out:tampered-round-trip-state:state with other arguments}}`. The SDK logs a different reason for each, `seal` for the changed character and `request binding` for the other arguments, and the client gets neither (`mcp/server/request_state.py`). The answer without a state got `{{out:tampered-round-trip-state:answer without state}}`. The tool treats an answer to a question it never asked as no answer, and the specification says a server that is missing an answer "SHOULD" ask again rather than return an error ([Multi Round-Trip Requests](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)).

The honest retry released the refund: {{out:tampered-round-trip-state:honest retry}}. The same retry, sent again, passed the seal, because nothing about it had changed. The server's own record of answered states refused it, with the tool error "{{out:tampered-round-trip-state:same retry again}}" That record is `confirmations.OnceOnly`, a set of states kept under a lock in the server's memory, and the tool checks it before it asks the shop's API to release anything. Behind it, the shop's API answers 409 to a second release of the same refund, so even a server that lost its record couldn't pay twice.

**Working rule:** Let the SDK seal every `requestState`, and never turn the seal off for state that touches money, access or data. Keep the state small and opaque: an ID, not the record. For any step that must happen once, keep your own record of answered states on the server, and check it before the side effect, not after.

## Choose elicitation or a tool argument {#elicitation-or-argument}

Each question in this chapter could have been a tool argument instead, such as `confirmed: true` on `issue_refund` from [Return an input request instead of a result](#return-an-input-request), or `reason` on `record_return` from [Ask for structured input with elicitation](#elicitation-forms). A tool argument costs no extra round trip and no user interface, but the model fills it in. Elicitation costs a round trip and a person's attention, and only the host's user is meant to answer it. So the question to ask is who can know the value.

This is a rule of thumb, not a measurement. If the model can read the value from the conversation, make it an argument. If only the person at the host can give it, elicit it. If it is a secret, or a sign-in to another service, use URL mode.

| What the tool needs | In the shop | Use |
| --- | --- | --- |
| A value in the ticket | the order ID a customer wrote | a tool argument |
| A decision the policy gives a person | releasing a refund above the limit | a form |
| A fact only the person present has | what a returned parcel held | a form |
| A secret or a sign-in | the lead's payment provider account | URL mode |

A `confirmed` argument on `issue_refund` would let the model confirm its own refund, which is the decision the refund policy keeps for a person. The order ID goes the other way. Asking the lead to retype an ID the customer already wrote adds a step and a chance for a typo, and the model can read it. When a value could come from either, take the argument and let the tool check it, as chapter 3's tools check every ID's format.

Elicitation is the server asking the user through the host. It isn't the host's own **consent**, the step where the host asks the user before a tool with side effects runs, which [Ask for consent before side effects](#consent-before-side-effects) builds. The shop's confirmation is the server's own check, and a careful host still asks before it calls `issue_refund` at all.

**Working rule:** Make a value a tool argument when the model can know it, and validate it in the tool. Elicit it when only the person can give it, or when the policy says a person must decide, and never accept that kind of value as an argument. Use URL mode for every secret. When you aren't sure, ask who would be at fault if the value were wrong.

## What goes wrong in production {#multi-round-trip-requests-in-production}

The shop's confirmation works with one stdio server, one client and a scripted lead who answers at once. Real leads take time, real servers restart, and real clients vary. Multi Round-Trip Requests fail in production in a few recognizable ways.

**State sealed by a key that died.** `MCPServer`'s default key is made when the process starts and lives only in its memory (`mcp/server/request_state.py`). If the server restarts between the question and the answer, or the retry reaches another replica, the server can't open the state, and the lead's answer fails with -32602. The sign is "Invalid or expired requestState" rising after deploys, or with the number of replicas. Give every replica the same keys through `RequestStateSecurity(keys=[...])`, which `confirmations.state_security()`, the sealing policy from [Return an input request instead of a result](#return-an-input-request), builds from `SHOP_REQUEST_STATE_KEY`. The first key seals and every key opens, so a key can rotate without dropping answers ([Run replicas without sticky sessions](#scale-without-sessions)).

**A lead slower than the state's lifetime.** The SDK's state lasts 600 seconds per round by default. A lead who reads the question, takes a phone call and answers fifteen minutes later gets the same -32602, and the server's log says `expired`. Set `ttl=` to the longest a person reasonably takes, and let the host turn the error into a fresh call, which asks again.

**Records that only one process sees.** The retry needs two records from the first round, and both live in one server's memory: chapter 3's quote store, through which the retry finds the refund, and `confirmations.OnceOnly`, the record of answered states from [Keep round-trip state tamper-proof](#round-trip-state). Behind two replicas, a retry that reaches the other one fails with "There is no quote", and a replayed answer that reaches it would pass the once-only check. Keep both records in shared storage, as [Run replicas without sticky sessions](#scale-without-sessions) does, and keep the shop's API's own 409 behind them.

**An answer from someone who isn't a lead.** The tool releases a refund on any `accept` the host sends, and the host may answer by code. Over stdio that is as far as a server can check. Over HTTP, bind every question to the authenticated caller, and check that the caller's token carries `refunds:write`, the scope only support leads hold ([Scope tools by what the token allows](#scopes-per-tool)).

**A client that can't ask.** A host whose client has no elicitation callback declares no elicitation capability (`mcp/client/session.py`), and the call fails with -32021, Missing Required Client Capability. A resolver's check runs before the tool; a hand-built check like `issue_refund`'s runs inside it, after chapter 3's tool has held the refund (`confirmations.require_elicitation`). The sign is that error from one host and not from others. A host that serves people should declare elicitation and show the questions ([Answer input requests for the user](#answer-input-requests)). A server whose tool has a safe default, such as leaving a refund held, can return that as the result instead of failing.

**A URL-mode flow that changes.** The specification marks URL mode as a feature whose design "may change in future protocol revisions" ([elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)), and the pinned revision already removed two of its parts. Keep URL-mode code in one place, and check it against each revision's changelog.

**Loops that never end.** A URL-mode flow the user abandons asks again on every retry, and the SDK's client stops after 10 rounds with `InputRequiredRoundsExceededError`. Count the rounds of each flow in `requestState`, and after a few, return a result that says the step is unfinished.

**An old client on the same server.** An `InputRequiredResult` returned to a client that connected with the 2025 handshake reaches it as -32603, "Handler returned an invalid result": the SDK checks the result against the 2025 `CallToolResult`, which requires `content` (`mcp/server/runner.py`; [multi-round-trip requests](https://py.sdk.modelcontextprotocol.io/v2/handlers/multi-round-trip/)). A server that serves both checks `ctx.protocol_version`, or uses resolvers, which pick the right path for each connection (`mcp/server/mcpserver/resolve.py`). [Serve old and new clients through the window](#serve-both-revisions) covers both.

**Rejections no one investigates.** Every rejected state gives the client the same message, so the only record of why is the server's log, under the logger `mcp.server.request_state`. Ship that log, and alert on `seal` and `request binding`, which mean someone changed a token, separately from `expired`, which usually means a slow person.

**Working rule:** Before a server that asks questions goes to production, give its replicas one shared key that can rotate, set the state's lifetime to how long people take, and move the quote store and every once-only record into shared storage. Bind each question to the caller wherever the transport has one. Then watch -32602 by its logged reason, -32021 by host, and the number of rounds per call.

## Decisions this chapter made {#multi-round-trip-requests-decisions}

- **The shop's API decides which refunds need confirming.** `issue_refund` calls chapter 3's version first and asks only when the API holds the refund, so the policy's limit lives in one place.
- **The refund is held before the question,** so a question no one answers leaves it held, as in chapter 3.
- **The confirmation is a hand-built input request:** one form-mode elicitation under the key `confirm`, with the refund's ID as `requestState`, which the retry checks against the refund it finds. The returned-parcel form uses a resolver, where the SDK's capability check and rendering save code.
- **The SDK seals every `requestState`,** under keys a deployment can inject through `confirmations.state_security()` or `SHOP_REQUEST_STATE_KEY`, and otherwise under a key that lives as long as the process.
- **Answers are once-only on the server,** through `confirmations.OnceOnly`, checked before the release, with the API's 409 behind it.
- **An answer without the server's state, or with another refund's, is a question never asked,** and the tool asks again.
- **The server keeps no call open, but keeps two records:** chapter 3's quote store and the once-only record, both in memory here and shared across replicas in chapter 6.
- **On stdio, the host's user is the one who confirms.** Over HTTP, the question is bound to the authenticated caller, and `refunds:write`, the scope only support leads hold, gates the tool ([Scope tools by what the token allows](#scopes-per-tool)).
- **Decline and cancel lead different ways:** a decline stands, and a cancel leaves the question open.
- **Secrets and sign-ins go through URL mode,** with the flow's ID in `requestState`, and `accept` never counts as finished.
- **The shop's API gained two endpoints,** `POST /refunds/{refund_id}/confirm` and `POST /refunds/{refund_id}/cancel`, which act only on a held refund and answer 409 otherwise.
- **Values the model can read stay tool arguments,** and values only a person can give are elicited.
