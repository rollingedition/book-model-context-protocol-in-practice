"""The book's host loop as chapter 10 builds it: several servers, the host's own tool names, consent, input requests,
attached resources and a few turns per ticket. It builds on `lib.host` (chapter 1) and `lib.host_guard` (chapter 9).

    from lib import host_guard, ticket_host
    servers = {"shop": support_shop.server_params(base_url), "partner": partner.create_server()}
    async with ticket_host.TicketHost(servers, gate=gate, lead=lead, pins=host_guard.ToolPins()) as host:
        host.tools()                       # what the model sees: "shop.get_order_status", "partner.track_parcel", ...
        run = await host.work(model, ticket)          # a Run: every turn, every call and its outcome, the last reply

- **One client per server.** Each entry in `servers` gets its own `mcp.Client` in its default auto mode, so each
  connection settles its own protocol revision. The key is a prefix the host's configuration assigns; the host never
  names tools after `serverInfo.name`, which the specification says not to rely on.
- **The host's own tool names.** The model sees `{prefix}.{tool}`; `route(name)` maps a name back to its server and
  the tool's name on the wire. A name the host doesn't know goes back to the model as an error result.
- **Pins (chapter 9).** With `pins`, a server's tool definitions are pinned when the host first connects to it, and a
  definition that later differs from its pin is hidden from the model (`hidden` lists it).
- **Consent (chapter 9).** Every call goes through `gate` (a `host_guard.ConsentGate`) first; a declined call goes
  back to the model as an error result.
- **Input requests.** Each client's `elicitation_callback` hands the request to `lead(server, params)`, the person
  who answers for the host, with the prefix of the server that asks; `asked` records each request and answer.
  `Client.call_tool` retries the call with the answer itself.
- **Resources.** `attach(prefix)` reads each of the server's resources marked for the assistant with a priority of at
  least `ATTACH_PRIORITY` and puts its text in the system prompt, after the tools, in `<resource>` blocks.
- **The queue's setup.** `queue_servers(base_url)` is the two servers chapter 10 works the queue against: the shop's
  (`lib.support_shop`, over stdio) and the partner's (`lib.partner`, clean, in-process). `approve_every_call` is the
  scripted user the consent gate asks, and `decline_every_request` the scripted lead who answers input requests;
  both are fixed, so a recorded run replays exactly.
- **Scoring.** `expected_first_tool(ticket)` is the tool a correct run calls first: the ticket's tag, except that a
  refund request (tagged `issue_refund`) starts with `quote_refund`. Chapter 11 scores the same way.
  `promises_refund(reply)` says whether a reply tells the customer a refund will be made, by a few fixed
  phrases (`REFUND_PROMISE`); a host compares that with the calls that ran.
- **The loop.** `work` sends the ticket, runs each tool call the model makes, and returns the result to the model in a
  `<tool_response>` block, errors included, so the model can correct itself. A reply with no tool call ends the
  ticket, and so does `MAX_TURNS` model calls. Each request has a timeout of `CALL_TIMEOUT` seconds. A call that
  fails, times out or runs past the client's cap on input-request rounds goes back to the model as `failed`.
"""
from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Callable

from mcp import Client, InputRequiredRoundsExceededError, MCPError
from mcp.types import ElicitRequestParams, ElicitResult, Implementation, Tool

from lib import host, host_guard, partner, support_shop

SEPARATOR = "."                  # inside the specification's character set for tool names
MAX_TURNS = 4
CALL_TIMEOUT = 10.0
ATTACH_PRIORITY = 0.8
REFUND_PROMISE = re.compile(r"will be (processed|issued|refunded)|(I'll|we'll|we will) (process|refund|issue)", re.I)
CLIENT_INFO = Implementation(name="shop-host", version="0.10.0")

QUEUE_PROMPT = host.SYSTEM_PROMPT + """

Each tool's name starts with the server it belongs to, such as shop. The host runs each call and sends you its result \
in a <tool_response> block. Then call the next tool the ticket needs, or, once you have what the ticket needs, reply \
to the customer in two or three sentences with no tool call. Use only order IDs, amounts and quote_ids that the \
ticket or a tool result gave you."""


@dataclass
class Turn:
    reply: str                          # the model's raw reply
    tool: str | None = None             # the name the model used, such as "shop.quote_refund"
    arguments: dict[str, Any] | None = None
    outcome: str = "answered"           # answered, result, tool error, declined, unknown tool, failed
    result: str = ""                    # what went back to the model


@dataclass
class Run:
    ticket_id: str
    turns: list[Turn] = field(default_factory=list)

    @property
    def calls(self) -> list[Turn]:
        return [turn for turn in self.turns if turn.tool is not None]

    @property
    def answer(self) -> str | None:
        last = self.turns[-1] if self.turns else None
        return last.reply if last is not None and last.tool is None else None


Lead = Callable[[str, ElicitRequestParams], ElicitResult]


class TicketHost:
    def __init__(self, servers: dict[str, Any], *, gate: host_guard.ConsentGate, lead: Lead,
                 pins: host_guard.ToolPins | None = None):
        self.servers, self.gate, self.lead, self.pins = servers, gate, lead, pins
        self.clients: dict[str, Client] = {}
        self.listed: dict[str, list[Tool]] = {}
        self.hidden: list[str] = []
        self.asked: list[tuple[str, str, str]] = []      # (server, message, action)
        self.context = ""                                  # attached resources, as the system prompt shows them
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> TicketHost:
        await self._stack.__aenter__()
        for prefix, server in self.servers.items():
            client = Client(server, client_info=CLIENT_INFO, read_timeout_seconds=CALL_TIMEOUT,
                            elicitation_callback=self._answerer(prefix))
            self.clients[prefix] = await self._stack.enter_async_context(client)
            tools = (await client.list_tools()).tools
            if self.pins is not None:
                if not any(server_name == prefix for server_name, _ in self.pins.approved):
                    self.pins.approve(prefix, tools)               # first connection: pin what the user saw
                usable = self.pins.usable(prefix, tools)
                self.hidden += [f"{prefix}{SEPARATOR}{t.name}" for t in tools if t not in usable]
                tools = usable
            self.listed[prefix] = tools
        return self

    async def __aexit__(self, *exc) -> None:
        await self._stack.__aexit__(*exc)

    def _answerer(self, prefix: str):
        async def answer(context, params: ElicitRequestParams) -> ElicitResult:
            result = self.lead(prefix, params)                     # the lead sees which server is asking
            self.asked.append((prefix, params.message, result.action))
            return result
        return answer

    def tools(self) -> list[Tool]:
        """Every usable tool, under the host's name for it, in the order of `servers`."""
        return [tool.model_copy(update={"name": f"{prefix}{SEPARATOR}{tool.name}"})
                for prefix, tools in self.listed.items() for tool in tools]

    def route(self, name: str) -> tuple[str, str] | None:
        """The server prefix and wire name for a name the model used, or None if no usable tool has it."""
        prefix, _, wire_name = name.partition(SEPARATOR)
        if any(tool.name == wire_name for tool in self.listed.get(prefix, ())):
            return prefix, wire_name
        return None

    async def attach(self, prefix: str) -> list[str]:
        """Put the server's resources for the assistant with priority >= ATTACH_PRIORITY in the system prompt."""
        chosen = []
        for resource in (await self.clients[prefix].list_resources()).resources:
            notes = resource.annotations
            if notes and "assistant" in (notes.audience or []) and (notes.priority or 0) >= ATTACH_PRIORITY:
                text = (await self.clients[prefix].read_resource(str(resource.uri))).contents[0].text
                self.context += f'\n\n<resource uri="{resource.uri}">\n{text.strip()}\n</resource>'
                chosen.append(str(resource.uri))
        return chosen

    def messages(self, ticket) -> list[dict[str, str]]:
        specs = "\n".join(json.dumps(spec, ensure_ascii=False) for spec in host.tool_specs(self.tools()))
        system = QUEUE_PROMPT.format(tools=specs)
        if self.context:
            system += "\n\nThe shop's documents for this ticket:" + self.context
        return [{"role": "system", "content": system}, {"role": "user", "content": host.ticket_message(ticket)}]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, str]:
        """Run one tool call the model made: (outcome, the text that goes back to the model)."""
        route = self.route(name)
        if route is None:
            return "unknown tool", f"There is no tool {name}. Use one of the tools listed, with its full name."
        prefix, wire_name = route
        if not self.gate.allows(prefix, wire_name, arguments):
            return "declined", f"The user declined this call to {name}. Don't retry it; tell the customer."
        try:
            result = await self.clients[prefix].call_tool(wire_name, arguments)
        except (MCPError, TimeoutError, InputRequiredRoundsExceededError) as error:
            return "failed", f"The call to {name} failed: {error}"
        if result.structured_content is not None and not result.is_error:
            text = json.dumps(result.structured_content, ensure_ascii=False)
        else:
            text = "\n".join(getattr(block, "text", "") for block in result.content)
        return ("tool error" if result.is_error else "result"), text

    async def work(self, model: host.Model, ticket) -> Run:
        """Work one ticket: up to MAX_TURNS model calls, each tool call run through the host."""
        run, messages = Run(ticket.ticket_id), self.messages(ticket)
        for _ in range(MAX_TURNS):
            choice = host.parse_reply(model.complete(messages))
            turn = Turn(choice.reply, choice.tool, choice.arguments)
            run.turns.append(turn)
            if choice.tool is None:
                break
            turn.outcome, turn.result = await self.call(choice.tool, choice.arguments)
            messages = messages + [{"role": "assistant", "content": choice.reply}, {"role": "user", "content": (
                f'<tool_response name="{choice.tool}" outcome="{turn.outcome}">\n{turn.result}\n</tool_response>')}]
        return run


def queue_servers(base_url: str) -> dict[str, Any]:
    """The servers chapter 10's host works the queue against, under the host's own prefixes."""
    return {"shop": support_shop.server_params(base_url), "partner": partner.create_server("clean")}


def approve_every_call(request: host_guard.Request) -> bool:
    """The scripted user the consent gate asks: approves every call it is shown."""
    return True


def decline_every_request(server: str, params: ElicitRequestParams) -> ElicitResult:
    """The scripted lead: declines every input request, so a refund above the limit stays held for a person."""
    return ElicitResult(action="decline")


def queue_host(base_url: str, servers: dict[str, Any] | None = None, **options) -> TicketHost:
    """The host as chapter 10 runs the queue: consent for anything but the shop's reads, pins, the scripted people.
    `servers` replaces `queue_servers(base_url)`, and any other option replaces the host's own."""
    gate = host_guard.ConsentGate(host_guard.NO_SIDE_EFFECTS, ask=approve_every_call)
    options = {"gate": gate, "lead": decline_every_request, "pins": host_guard.ToolPins(), **options}
    return TicketHost(servers or queue_servers(base_url), **options)


def expected_first_tool(ticket) -> str:
    """The tool a correct run calls first, under the host's name. `lib.shop_data` tags a refund request with
    `issue_refund`, the tool that makes the refund; but `issue_refund` takes a `quote_id`, so a correct run starts
    with `quote_refund`, and this is what the queue scores against."""
    first = "quote_refund" if ticket.expected_tool == "issue_refund" else ticket.expected_tool
    return f"shop{SEPARATOR}{first}"


def promises_refund(reply: str | None) -> bool:
    """Whether a reply tells the customer a refund will be made, by the phrases in `REFUND_PROMISE`."""
    return bool(reply and REFUND_PROMISE.search(reply))
