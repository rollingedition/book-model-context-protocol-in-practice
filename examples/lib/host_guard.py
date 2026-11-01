"""What the book's host checks before a model sees a tool or a tool runs (chapter 9): pinned tool definitions and
consent before side effects. Neither the specification nor the Python SDK does either for you.

    from lib import host_guard
    pins = host_guard.ToolPins()
    pins.approve("partner", tools)              # what the user approved, by SHA-256 of each definition
    pins.check("partner", tools)                # {"track_parcel": "unchanged" | "changed" | "new"}
    pins.usable("partner", tools)               # only the tools whose definition matches what was approved

    gate = host_guard.ConsentGate(host_guard.NO_SIDE_EFFECTS, ask=user)
    gate.allows("shop", "issue_refund", {"quote_id": ...})   # True or False; every decision is in gate.log

- `definition_sha256(tool)` hashes the canonical JSON (sorted keys, no spaces) of the parts of a tool definition that
  a model reads or a host acts on: `name`, `title`, `description`, `inputSchema`, `outputSchema` and `annotations`.
  The pinned revision asks servers to list tools in a deterministic order, but a hash per tool doesn't depend on it.
- `ToolPins` keeps one hash per (server, tool) that the user approved. A changed or new definition isn't usable
  until the user approves it again; `changes()` names the fields that differ from the approved definition.
- `ConsentGate` lets a tool run without asking only if the host's own list, `allow_without_asking`, names it for that
  server. It never reads a server's annotations to decide, because annotations from a server the host doesn't trust
  are claims, not facts. Otherwise it shows the user the server, the tool and the exact arguments, through `ask`,
  and records the decision. `NO_SIDE_EFFECTS` is that list for the shop's own server.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

FIELDS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations")
NO_SIDE_EFFECTS = {("shop", "find_orders"), ("shop", "get_order_status"), ("shop", "quote_refund"),
                   ("shop", "check_stock")}


def definition(tool) -> dict[str, Any]:
    """The parts of a tool definition the host pins, as JSON values."""
    dumped = tool.model_dump(by_alias=True, exclude_none=True, mode="json")
    return {key: dumped[key] for key in FIELDS if key in dumped}


def definition_sha256(tool) -> str:
    canonical = json.dumps(definition(tool), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ToolPins:
    """The tool definitions a user approved, one SHA-256 per (server, tool)."""

    def __init__(self):
        self.approved: dict[tuple[str, str], tuple[str, dict]] = {}

    def approve(self, server: str, tools) -> None:
        for tool in tools:
            self.approved[(server, tool.name)] = (definition_sha256(tool), definition(tool))

    def check(self, server: str, tools) -> dict[str, str]:
        found = {}
        for tool in tools:
            pinned = self.approved.get((server, tool.name))
            found[tool.name] = ("new" if pinned is None
                                else "unchanged" if pinned[0] == definition_sha256(tool) else "changed")
        return found

    def changes(self, server: str, tool) -> list[str]:
        """The fields of `tool` that differ from the definition the user approved."""
        before = self.approved[(server, tool.name)][1]
        now = definition(tool)
        return [key for key in FIELDS if before.get(key) != now.get(key)]

    def usable(self, server: str, tools) -> list:
        status = self.check(server, tools)
        return [tool for tool in tools if status[tool.name] == "unchanged"]


@dataclass(frozen=True)
class Request:
    server: str
    tool: str
    arguments: dict[str, Any]


@dataclass
class ConsentGate:
    """Asks the user before any tool call the host's own list doesn't allow, and records every decision."""
    allow_without_asking: Collection[tuple[str, str]]
    ask: Callable[[Request], bool]
    log: list[tuple[Request, str]] = field(default_factory=list)

    def allows(self, server: str, tool: str, arguments: dict[str, Any]) -> bool:
        request = Request(server, tool, dict(arguments))
        if (server, tool) in self.allow_without_asking:
            self.log.append((request, "allowed by the host's list"))
            return True
        approved = self.ask(request)
        self.log.append((request, "approved by the user" if approved else "declined by the user"))
        return approved
