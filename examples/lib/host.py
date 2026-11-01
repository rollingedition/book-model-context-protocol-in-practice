"""The book's host loop, as small as chapter 1 needs: the book's own prompt, one model turn, and replayed recordings.

The book keeps its own prompt and parses the model's raw reply itself, so the same code drives the open model when a
recording is made (`recordings/`) and the replay when an example runs. Examples never call a model:

    from lib.host import ReplayModel, choose_tool
    choice = choose_tool(ReplayModel("pick-a-tool"), ticket, tools)   # tools: from client.list_tools()
    choice.tool, choice.arguments                                     # "get_order_status", {"order_id": "O-1942"}

- `build_messages(ticket, tools)` renders the system prompt with the tools (name, description and parameters only,
  with JSON Schema `title`s dropped, so an SDK release that changes generated titles doesn't change the prompt) and
  the ticket as the user's message.
- `parse_reply(text)` reads a `<tool_call>{"name": …, "arguments": {…}}</tool_call>` block, the format the prompt asks
  for, into a `Choice`; a reply without one is an answer in words (`Choice.tool` is None).
- `ReplayModel(name)` answers from `examples/data/recorded/{name}/replies.jsonl`, matched by the SHA-256 of the exact
  messages. A prompt that differs from the recorded one raises `RecordingMismatch`: re-run the recording script.

Later chapters add more turns, several servers, namespacing, consent and input requests (chapter 10).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

RECORDED = Path(__file__).resolve().parent.parent / "data" / "recorded"

SYSTEM_PROMPT = """You are the support assistant for Fernhill Supply, an online shop for kitchen and garden goods. \
You work on one customer ticket at a time.

You can call these tools, described in JSON:
<tools>
{tools}
</tools>

To call a tool, reply with only this block and nothing before or after it:
<tool_call>
{{"name": "<tool name>", "arguments": {{<arguments as JSON>}}}}
</tool_call>

Call a tool only when its description fits what the ticket asks. Write order IDs in the shop's form, such as O-1873. \
If no tool fits, don't call one: reply in one or two sentences saying what the ticket needs."""


@dataclass(frozen=True)
class Choice:
    tool: str | None                 # the tool the model chose, or None when it answered in words
    arguments: dict[str, Any] | None
    reply: str                       # the model's raw reply


class Model(Protocol):
    name: str

    def complete(self, messages: list[dict[str, str]]) -> str: ...


class RecordingMismatch(LookupError):
    pass


def _drop_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _drop_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_drop_titles(v) for v in schema]
    return schema


def tool_specs(tools) -> list[dict[str, Any]]:
    """MCP tools (from `list_tools()`) as the prompt shows them: name, description and parameters."""
    return [{"name": t.name, "description": t.description or "", "parameters": _drop_titles(t.input_schema)}
            for t in tools]


def ticket_message(ticket) -> str:
    """A ticket as the user's message: its ID, its customer, its subject and its text, as written."""
    return f"Ticket {ticket.ticket_id} from customer {ticket.customer_id}\nSubject: {ticket.subject}\n\n{ticket.body}"


def build_messages(ticket, tools) -> list[dict[str, str]]:
    specs = "\n".join(json.dumps(spec, ensure_ascii=False) for spec in tool_specs(tools))
    return [{"role": "system", "content": SYSTEM_PROMPT.format(tools=specs)},
            {"role": "user", "content": ticket_message(ticket)}]


def messages_sha256(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*\})\s*</tool_call>", re.DOTALL)


def parse_reply(reply: str) -> Choice:
    """The model's choice: a tool and its arguments from a <tool_call> block, or no tool."""
    found = TOOL_CALL.search(reply)
    if not found:
        return Choice(None, None, reply)
    try:
        call = json.loads(found.group(1))
    except json.JSONDecodeError:
        return Choice(None, None, reply)
    return Choice(call.get("name"), call.get("arguments") or {}, reply)


class ReplayModel:
    """A model that answers from a recording, and only for the exact messages it recorded."""

    def __init__(self, recording: str, root: Path = RECORDED):
        self.name = f"replay:{recording}"
        self.folder = root / recording
        with open(self.folder / "replies.jsonl", encoding="utf-8") as f:
            self.replies = {entry["messages_sha256"]: entry["reply"] for entry in map(json.loads, f)}

    def complete(self, messages: list[dict[str, str]]) -> str:
        key = messages_sha256(messages)
        if key not in self.replies:
            raise RecordingMismatch(f"{self.folder.name} has no reply for these messages ({key[:12]}): the prompt, "
                                    "the ticket or the tools changed since it was recorded; re-run its script in "
                                    "recordings/")
        return self.replies[key]


def choose_tool(model: Model, ticket, tools) -> Choice:
    """One model turn: show the model the ticket and the tools, and read which tool it chooses."""
    return parse_reply(model.complete(build_messages(ticket, tools)))
