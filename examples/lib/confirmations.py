"""What chapter 5's servers need around a Multi Round-Trip Request: chapter 3's tools, a sealing key, a once-only record.

    from lib import confirmations
    server, held = confirmations.shop_server()           # chapter 3's tools but issue_refund; and issue_refund
    answered = confirmations.OnceOnly()                  # answered.claim(state) is True the first time only
    confirmations.release(refund)                        # the shop's API releases a refund it holds

- `RELEASE_FORM` is the form `issue_refund` asks a person to fill in: one required boolean, `release`. `say_yes` is a
  scripted user who accepts it, for a client's `elicitation_callback`.
- `QuoteId` is the `quote_id` parameter's type, as chapter 3's `issue_refund` declares it.
- `chapter3_tools()` returns the five tools of `lib.shop_tools.create_server()` as the SDK's `Tool` objects, so a
  server can reuse them unchanged or wrap one. They share one quote store, as in chapter 3, so a `quote_id` that
  `quote_refund` returns works with `issue_refund`.
- `shop_server(name, version, keys)` makes an `MCPServer` with those tools except `issue_refund`, sealing under
  `state_security(keys)`, and returns it with chapter 3's `issue_refund` tool, which the caller wraps (chapter 5's
  server asks for confirmation around it) and registers under the same name. `quotes=` gives the tools a quote store
  to share (chapter 6); without it, they use `lib.shared_state.SharedMap` on the file that `SHOP_STATE_STORE` names
  when that variable is set, and otherwise chapter 3's in-memory store.
- `launch(example, base_url)` is how a client starts a server example over stdio, with `--serve`, the shop's API in
  its environment, and `SHOP_REQUEST_STATE_KEY` and `SHOP_STATE_STORE` passed on when they are set.
- `state_security(keys)` is the policy `MCPServer` seals `requestState` with. With `keys` it seals under them
  (`keys[0]` seals, every key unseals, so keys can rotate); without, it reads the key from the environment variable
  `SHOP_REQUEST_STATE_KEY` if that is set, and otherwise makes a key that lives only as long as this process, which
  is the SDK's own default. Several replicas, or a server that restarts, need the same key (chapter 6).
- `require_elicitation(ctx, mode)` raises the JSON-RPC error -32021 unless the client declared elicitation in `mode`
  ("form" or "url"). A server that builds its own input requests must check, because the specification forbids
  asking for what the client didn't declare; the SDK's resolvers make the same check for you.
- `OnceOnly` remembers which round-trip states have been answered, in this process's memory, under a lock. Sealing
  stops a client from forging or changing a state, but not from sending the same one twice; the specification leaves
  that check to the server. Several replicas need a shared store instead: `OnceOnly(seen=...)` takes any container
  with `in` and `add`, and holds its `lock` if it has one; without it, it uses `lib.shared_state.SharedSet` on the
  file `SHOP_STATE_STORE` names when that is set, and otherwise this process's memory.
- `release(refund)` and `cancel(refund)` take a `lib.shop_tools.Refund` the shop's API holds and call
  `POST /refunds/{refund_id}/confirm` or `/cancel`. `release` returns the refund with its new status, "requested".
  When the API no longer holds the refund, both raise `ToolError`, so the model reads why.
"""
from __future__ import annotations

import os
import sys
import threading
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from typing import Annotated, Literal

import httpx2
from pydantic import Field

from mcp import MCPError, StdioServerParameters
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.request_state import RequestStateSecurity
from mcp.types import MISSING_REQUIRED_CLIENT_CAPABILITY, ElicitRequestParams, ElicitResult

from lib import shared_state, shop_api, shop_tools

STATE_KEY_VARIABLE = "SHOP_REQUEST_STATE_KEY"
STATE_TTL_SECONDS = 600.0                  # the SDK's default: each round's state is valid for 10 minutes

RELEASE_FORM = {"type": "object", "properties": {"release": {"type": "boolean", "title": "Release this refund"}},
                "required": ["release"]}      # the form issue_refund shows: one required yes-or-no field

QuoteId = Annotated[str, Field(pattern=r"^Q-[0-9a-f]{10}$", description="From quote_refund, such as Q-3f9a0c21be")]


async def say_yes(context, params: ElicitRequestParams) -> ElicitResult:
    """A scripted user, for a client's `elicitation_callback`: accepts every form with release set to true."""
    return ElicitResult(action="accept", content={"release": True})


def chapter3_tools(*, quotes: MutableMapping[str, dict] | None = None) -> dict[str, Tool]:
    """Chapter 3's five tools, by name, from one `shop_tools.create_server()`, so they share its quote store."""
    server = shop_tools.create_server(quotes=quotes)
    return {tool.name: tool for tool in server._tool_manager.list_tools()}   # the SDK has no public accessor


def shop_server(name: str = "shop-support", version: str = "0.5.0",
                keys: Sequence[bytes | str] | None = None, *,
                quotes: MutableMapping[str, dict] | None = None) -> tuple[MCPServer, Tool]:
    """A server with chapter 3's tools except `issue_refund`, sealing `requestState` with `state_security(keys)`,
    and chapter 3's `issue_refund` tool, for the caller to wrap and register under the same name."""
    if quotes is None and os.environ.get(shared_state.STORE_VARIABLE):
        quotes = shared_state.SharedMap(os.environ[shared_state.STORE_VARIABLE], "quotes")
    tools = chapter3_tools(quotes=quotes)
    held = tools.pop("issue_refund")
    return MCPServer(name, version=version, tools=list(tools.values()),
                     request_state_security=state_security(keys)), held


def launch(example: str, base_url: str) -> StdioServerParameters:
    """How a client launches a chapter 5 server example over stdio (`python {example} --serve`), with the shop's API
    address and key, and SHOP_REQUEST_STATE_KEY when it is set, in the server's environment."""
    env = shop_api.server_env(base_url)
    for variable in (STATE_KEY_VARIABLE, shared_state.STORE_VARIABLE):
        if os.environ.get(variable):
            env[variable] = os.environ[variable]
    return StdioServerParameters(command=sys.executable, args=[str(Path(example).resolve()), "--serve"], env=env,
                                 cwd=shop_tools.EXAMPLES)


def state_security(keys: Sequence[bytes | str] | None = None, ttl: float = STATE_TTL_SECONDS) -> RequestStateSecurity:
    """How the server seals `requestState`: under `keys`, else the key in SHOP_REQUEST_STATE_KEY, else a key that
    lives only as long as this process. A key is at least 32 bytes of secret randomness."""
    if keys is None and os.environ.get(STATE_KEY_VARIABLE):
        keys = [os.environ[STATE_KEY_VARIABLE]]
    if keys is None:
        return RequestStateSecurity.ephemeral(ttl=ttl)
    return RequestStateSecurity(keys=list(keys), ttl=ttl)


def require_elicitation(ctx: Context, mode: Literal["form", "url"]) -> None:
    """Raise the JSON-RPC error -32021 unless the client declared elicitation in `mode`, as the SDK's resolvers do. A
    bare `elicitation: {}`, the only shape before modes existed, counts as form mode."""
    capabilities = ctx.client_capabilities
    elicitation = capabilities.elicitation if capabilities is not None else None
    if elicitation is not None and (getattr(elicitation, mode) is not None
                                    or (mode == "form" and elicitation.url is None)):
        return
    raise MCPError(code=MISSING_REQUIRED_CLIENT_CAPABILITY,
                   message=f"Client did not declare the {mode} elicitation capability this tool needs",
                   data={"requiredCapabilities": {"elicitation": {mode: {}}}})


class OnceOnly:
    """A record of the round-trip states already answered. `claim(state)` is True the first time, False after."""

    def __init__(self, *, seen=None) -> None:
        if seen is None and os.environ.get(shared_state.STORE_VARIABLE):
            seen = shared_state.SharedSet(os.environ[shared_state.STORE_VARIABLE], "answered")
        self._seen = set() if seen is None else seen
        self._lock = getattr(self._seen, "lock", None) or threading.Lock()   # tools run on worker threads

    def claim(self, state: str) -> bool:
        with self._lock:
            if state in self._seen:
                return False
            self._seen.add(state)
            return True


def _decide(refund: shop_tools.Refund, decision: str) -> dict:
    response = httpx2.post(f"{os.environ['SHOP_API_URL']}/refunds/{refund.refund_id}/{decision}",
                           headers={"X-API-Key": os.environ["SHOP_API_KEY"]}, timeout=5.0)
    if response.status_code == 409:
        raise ToolError(f"The shop's API no longer holds refund {refund.refund_id}: it was already confirmed or "
                        "cancelled. Tell the user; don't ask again.")
    response.raise_for_status()
    return response.json()


def release(refund: shop_tools.Refund) -> shop_tools.Refund:
    """Release a refund the shop's API holds for confirmation: the same refund, now "requested"."""
    return refund.model_copy(update={"status": _decide(refund, "confirm")["status"]})


def cancel(refund: shop_tools.Refund) -> None:
    """Cancel a refund the shop's API holds for confirmation."""
    _decide(refund, "cancel")
