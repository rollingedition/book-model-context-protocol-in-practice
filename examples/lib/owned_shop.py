"""The shop's MCP server as chapter 9 secures it: chapter 3's tools, acting only for the customer the token names.

Chapter 3's tools (`lib.shop_tools`) trust the caller: `find_orders` takes any `customer_id`, `quote_refund` quotes
any order, and whoever holds a `quote_id` can spend it. Behind chapter 8's OAuth that still holds, because the
server reaches the shop's API with its own key, which can read and refund every order. This module wraps the same
five tools, unchanged, so that the customer always comes from the verified access token:

- the caller is `get_access_token().subject`, the token's `sub`. It is a customer ID such as `C-0127` because the
  shop's own authorization server issued the token, and the verifier accepts that issuer only (`sub` is unique only
  per issuer).
- `find_orders` loses its `customer_id` argument and searches the caller's orders.
- `get_order_status` and `quote_refund` answer an order that belongs to someone else exactly as they answer an
  order that doesn't exist, so the answer reveals nothing about other customers' orders.
- each `quote_id` is recorded with the customer it was quoted for, and `issue_refund` refuses any other caller's
  quote as unknown: the specification's "a handle is a name, not a capability".
- `issue_refund` is chapter 5's confirming one: a refund above the policy limit, which the shop's API holds, is
  released only after a person confirms it through a Multi Round-Trip Request (`lib.confirmations`). A host's own
  consent comes on top of that, so such a refund is asked about twice, once by the host and once by the server.

The subject is the customer because this server is for a host that customers sign in to themselves. Chapter 8's
support host signs in a member of staff instead; there the customer comes from the ticket the server looks up by ID,
checked against what that staff member may handle, and still never from a tool argument.

    from lib import owned_shop
    with auth_server.serve() as issuer, owned_shop.serve(issuer.url) as url:    # url: ".../mcp"
        ...

`create_app(resource, issuer, owned=...)` builds the app as `lib.protected_shop.create_app` does (audience check,
endpoint scopes, `lib.tool_scopes` per tool). `owned=False` serves chapter 3's tools as they are, behind the same
OAuth, for the before-and-after. The tools call the shop's API with `SHOP_API_URL` and `SHOP_API_KEY` from this
process's environment.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated

from pydantic import Field

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from lib import auth_server, confirmations, protected_shop, shop_tools, tool_scopes
from lib.confirmations import chapter3_tools

VERSION = "0.9.0"
FIND_ORDERS = ("Search the signed-in customer's orders, newest first, when the ticket gives no order ID or asks about "
               "several orders. Filter by status or by the date the order was placed. Returns each order's ID, "
               "date, status, total and SKUs. To look up one order whose ID you know, use get_order_status instead.")


def caller() -> str:
    """The customer this request acts for: the verified token's subject. Never an argument."""
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("This server acts only for a signed-in customer.")
    return token.subject


def owned_order(order_id: str) -> None:
    """Raise the not-found error chapter 3's tools give, unless `order_id` is the caller's order."""
    response = shop_tools._api("GET", f"/orders/{order_id}")
    if response is None or response.json()["customer_id"] != caller():
        raise ToolError(f"The shop has no order {order_id}. Check the number with the customer, "
                        "or use find_orders to list their orders.")


def create_server(*, auth: AuthSettings | None = None, token_verifier=None) -> MCPServer:
    """Chapter 3's five tools, each acting for the token's subject only, with chapter 5's confirming refund."""
    tools = chapter3_tools()                 # chapter 3's tools, sharing one quote store
    server = MCPServer("shop-support", version=VERSION, auth=auth, token_verifier=token_verifier,
                       request_state_security=confirmations.state_security())
    quoted_for: dict[str, str] = {}          # quote_id -> the customer it was quoted for
    answered = confirmations.OnceOnly()      # the round-trip states already answered (chapter 5)

    def find_orders(status: shop_tools.Status | None = None,
                    placed_since: Annotated[date | None, Field(description="Only orders placed on or after this "
                                                                           "date, YYYY-MM-DD")] = None,
                    limit: Annotated[int, Field(ge=1, le=50)] = 10) -> shop_tools.OrderList:
        return tools["find_orders"].fn(customer_id=caller(), status=status, placed_since=placed_since, limit=limit)

    def get_order_status(order_id: shop_tools.OrderId) -> shop_tools.OrderDetail:
        owned_order(order_id)
        return tools["get_order_status"].fn(order_id=order_id)

    def quote_refund(order_id: shop_tools.OrderId,
                     sku: Annotated[shop_tools.Sku | None, Field(description="Refund only this product's line; leave "
                                                                             "out to refund the whole order")] = None,
                     reason: Annotated[str, Field(min_length=3, max_length=200)] = "customer request"
                     ) -> shop_tools.RefundQuote:
        owned_order(order_id)
        quote = tools["quote_refund"].fn(order_id=order_id, sku=sku, reason=reason)
        quoted_for[quote.quote_id] = caller()
        return quote

    def issue_refund(quote_id: confirmations.QuoteId, ctx: Context) -> shop_tools.Refund | InputRequiredResult:
        if quoted_for.get(quote_id) != caller():
            raise ToolError(f"There is no quote {quote_id}. Call quote_refund for the order to get a quote_id.")
        refund = tools["issue_refund"].fn(quote_id=quote_id)    # the same quote_id always gives the same refund
        if refund.status != "needs_confirmation":
            return refund
        answer = (ctx.input_responses or {}).get("confirm")    # chapter 5's confirmation, from here on
        if answer is None or ctx.request_state != refund.refund_id:
            confirmations.require_elicitation(ctx, "form")
            ask = ElicitRequestFormParams(requested_schema=confirmations.RELEASE_FORM, message=f"Refund "
                                          f"{refund.amount} on order {refund.order_id}? It is above the policy "
                                          "limit, so a person must confirm it.")
            return InputRequiredResult(input_requests={"confirm": ElicitRequest(params=ask)},
                                       request_state=refund.refund_id)
        if answer.action != "accept" or not (answer.content or {}).get("release"):
            raise ToolError(f"Nobody confirmed refund {refund.refund_id}, so the shop's API still holds it.")
        if not answered.claim(ctx.request_state):
            raise ToolError(f"Refund {refund.refund_id} was already confirmed. Don't send the same answer again.")
        return confirmations.release(refund)

    wrapped = {"find_orders": find_orders, "get_order_status": get_order_status, "quote_refund": quote_refund,
               "issue_refund": issue_refund, "check_stock": tools["check_stock"].fn}
    for name, fn in wrapped.items():         # same names, titles and annotations; only find_orders' text changes
        tool = tools[name]
        server.add_tool(fn, name=name, title=tool.title, annotations=tool.annotations,
                        description=FIND_ORDERS if name == "find_orders" else tool.description)
    return server


def create_app(resource: str, issuer: str, *, owned: bool = True):
    """The server's Streamable HTTP app behind chapter 8's OAuth; `owned=False` serves chapter 3's tools as they are."""
    verifier = auth_server.JwtVerifier(issuer)
    settings = AuthSettings(issuer_url=issuer, resource_server_url=resource,
                            required_scopes=protected_shop.ENDPOINT_SCOPES, validate_token_resource=True)
    server = (create_server(auth=settings, token_verifier=verifier) if owned
              else shop_tools.create_server(version=VERSION, auth=settings, token_verifier=verifier))
    return tool_scopes.require(server.streamable_http_app(), protected_shop.TOOL_SCOPES, verifier=verifier,
                               resource=resource)


@contextmanager
def serve(issuer: str, **options) -> Iterator[str]:
    """Serve the server on loopback and yield its endpoint URL."""
    with auth_server.serve_built(lambda base_url: create_app(base_url + "/mcp", issuer, **options)) as base_url:
        yield base_url + "/mcp"
