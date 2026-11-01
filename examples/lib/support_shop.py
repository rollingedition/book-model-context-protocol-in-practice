"""The shop's MCP server as chapter 10's host meets it: chapter 3's tools, chapter 5's confirmation, chapter 4's policies.

Chapter 10 puts no new feature in the server. It gathers what earlier chapters built, so the host has one server to
work the ticket queue against:

- `find_orders`, `get_order_status` and `check_stock`, unchanged from `lib.shop_tools` (chapter 3);
- `quote_refund` from chapter 3, with one change for the recordings: its `quote_id` is a counter in this process,
  hashed with the shop's seed, not a value from `secrets`. It looks random but repeats exactly on every run, so a
  replayed run sees the quote IDs the recorded run saw; and the counter starts again at 1 with each server process,
  so after a restart the same IDs come back naming different quotes. The quotes and the once-only record live in
  this process too, and a restart loses them. That is what a replay needs and what a server you ship must never do.
  Chapter 3 explains why it keeps them random: an ID anyone can predict can be spent by anyone who holds it;
- `issue_refund` as chapter 5's `refund-asks-to-confirm` wraps it: a refund the shop's API holds, because it is above
  the policy limit, returns an input request with `confirmations.RELEASE_FORM` and is released only on an accepted
  answer, once;
- the six policies as resources at `shop://policies/{slug}`, with the annotations chapter 4 gives them (audience
  `assistant`, priority 1.0 for the refund policy and 0.5 for the others) and an hour's cache hint.

    from lib import support_shop
    params = support_shop.server_params(base_url)       # launch over stdio: python -m lib.support_shop --serve

The tools call the shop's API with `SHOP_API_URL` and `SHOP_API_KEY` from the environment, as chapter 3's do.
"""
from __future__ import annotations

import hashlib
import itertools
import sys
from typing import Annotated

from pydantic import Field

from mcp import StdioServerParameters
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resources import FileResource
from mcp.types import Annotations, ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from lib import confirmations, shop_api, shop_tools
from lib.policies import load_policies
from lib.shop_data import SHOP_SEED

HOUR_MS = 3_600_000


def create_server() -> MCPServer:
    quotes: dict[str, dict] = {}
    tools = confirmations.chapter3_tools(quotes=quotes)
    quote, held = tools.pop("quote_refund"), tools.pop("issue_refund")
    numbers = itertools.count(1)
    answered = confirmations.OnceOnly()
    server = MCPServer("shop-support", version="0.10.0", tools=list(tools.values()),
                       request_state_security=confirmations.state_security(), cache_hints={
                           "resources/list": CacheHint(ttl_ms=HOUR_MS, scope="public"),
                           "resources/read": CacheHint(ttl_ms=HOUR_MS, scope="public")})

    @server.tool(title="Quote a refund", description=shop_tools.DESCRIPTIONS["quote_refund"],
                 annotations=quote.annotations)
    def quote_refund(order_id: shop_tools.OrderId,
                     sku: Annotated[shop_tools.Sku | None, Field(description="Refund only this product's line; leave "
                                                                             "out to refund the whole order")] = None,
                     reason: Annotated[str, Field(min_length=3, max_length=200)] = "customer request"
                     ) -> shop_tools.RefundQuote:
        made = quote.fn(order_id, sku, reason)
        repeatable = "Q-" + hashlib.sha256(f"{SHOP_SEED}:{next(numbers)}".encode()).hexdigest()[:10]
        quotes[repeatable] = quotes.pop(made.quote_id)          # the same quote, under a repeatable ID
        return made.model_copy(update={"quote_id": repeatable})

    @server.tool(title="Issue a refund", description=shop_tools.DESCRIPTIONS["issue_refund"],
                 annotations=held.annotations)
    def issue_refund(quote_id: confirmations.QuoteId, ctx: Context) -> shop_tools.Refund | InputRequiredResult:
        refund = held.fn(quote_id)
        if refund.status != "needs_confirmation":
            return refund
        answer = (ctx.input_responses or {}).get("confirm")
        if answer is None or ctx.request_state != refund.refund_id:
            confirmations.require_elicitation(ctx, "form")
            ask = ElicitRequestFormParams(requested_schema=confirmations.RELEASE_FORM, message=f"Refund "
                                          f"{refund.amount} on order {refund.order_id}? It is above the policy limit, "
                                          "so a lead must confirm it.")
            return InputRequiredResult(input_requests={"confirm": ElicitRequest(params=ask)},
                                       request_state=refund.refund_id)
        if answer.action != "accept" or not (answer.content or {}).get("release"):
            raise ToolError(f"Nobody confirmed refund {refund.refund_id}, so the shop's API still holds it.")
        if not answered.claim(ctx.request_state):
            raise ToolError(f"Refund {refund.refund_id} was already confirmed. Don't send the same answer again.")
        return confirmations.release(refund)

    for policy in load_policies():
        server.add_resource(FileResource(
            uri=f"shop://policies/{policy.slug}", name=f"{policy.slug}-policy", title=policy.title,
            description=policy.summary, mime_type="text/markdown", path=policy.path,
            annotations=Annotations(audience=["assistant"], priority=1.0 if policy.slug == "refund" else 0.5,
                                    last_modified=f"{policy.updated}T00:00:00Z")))
    return server


def server_params(base_url: str) -> StdioServerParameters:
    """How a client launches this server over stdio, with the shop's API address and key in its environment."""
    return StdioServerParameters(command=sys.executable, args=["-m", "lib.support_shop", "--serve"],
                                 env=shop_api.server_env(base_url), cwd=shop_tools.EXAMPLES)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        create_server().run()
