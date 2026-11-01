"""The shop's MCP server as chapter 3 designs it: five tools shaped around the support team's tasks.

    find_orders        search one customer's orders (by status, by date placed)          GET /orders
    get_order_status   one order by its ID                                               GET /orders/{order_id}
    quote_refund       what a refund would be, and a quote_id; changes nothing           GET /orders/{order_id}
    issue_refund       refund by quote_id; the same quote never refunds twice            POST /refunds
    check_stock        on-hand count per warehouse for one SKU                           GET /stock/{sku}

Each tool has a description written for a model, typed inputs (`Annotated[..., Field(...)]`, so patterns, bounds and
enums reach the JSON Schema), a pydantic model as its return type (so the SDK publishes an output schema and returns
`structuredContent` with no `{"result": ...}` wrapper) and annotations. Failures the model can fix raise `ToolError`;
a failure only an operator can fix (the shop's API rejecting the server's key) raises `MCPError`, a JSON-RPC error.

Quotes are handles in the sense of the specification's stateful-tools guidance: `quote_refund` returns an opaque
`quote_id`, valid for `QUOTE_TTL_SECONDS`, and `issue_refund` takes it instead of an amount. A `quote_id` is random
(40 bits from `secrets`, in the `Q-` + 10 hex digits form chapter 5's `QuoteId` expects), so no one can work it out
from the order. Nothing binds it, or a `customer_id`, to the customer a ticket comes from: this server trusts what the
caller sends (chapter 9). Quotes live in this server process's memory, which is enough for one stdio server; several
replicas need a shared store (chapter 6): pass `create_server(quotes=...)` any mutable mapping that every replica
reaches, such as `lib.shared_state.SharedMap`. If it has a `lock` (a reusable context manager), the tools hold it instead of
this process's own lock, so the once-only check holds across processes.

    from lib import shop_tools
    params = shop_tools.server_params(base_url)          # launch over stdio: python -m lib.shop_tools --serve
    server = shop_tools.create_server()                  # or use the server object in-process

The descriptions the model reads are in `DESCRIPTIONS`. Also here, for the chapter's comparisons: `endpoint_tools()`,
the tool list a generator that maps each endpoint of the shop's API to one tool produces; `VAGUE_DESCRIPTIONS`,
one-line descriptions of the kind such generators write; `DRAFT_DESCRIPTIONS`, the first draft of `DESCRIPTIONS`;
and `with_descriptions(tools, descriptions)`, which swaps only the descriptions in a tool list.
Run as `python -m lib.shop_tools --serve` from `examples/`, this file serves the five tools over stdio.
"""
from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from collections.abc import MutableMapping
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import httpx2
from pydantic import BaseModel, Field

from mcp import MCPError, StdioServerParameters
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import INTERNAL_ERROR, Tool, ToolAnnotations

from lib.shop_data import REFUND_LIMIT_CENTS

EXAMPLES = Path(__file__).resolve().parent.parent
QUOTE_TTL_SECONDS = 900                    # a quote_id is valid for 15 minutes
REFUNDABLE = ("delivered", "returned")

OrderId = Annotated[str, Field(pattern=r"^O-\d{4}$", description="The shop's order ID, such as O-1873")]
CustomerId = Annotated[str, Field(pattern=r"^C-\d{4}$", description="The customer's ID, such as C-0042")]
Sku = Annotated[str, Field(pattern=r"^KG-\d{4}$", description="A product's SKU, such as KG-1031")]
Status = Literal["placed", "shipped", "delivered", "cancelled", "returned"]

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

DESCRIPTIONS = {               # what the model reads to choose a tool: when to use it, its inputs, what comes back
    "find_orders": "Search one customer's orders, newest first, when the ticket gives no order ID or asks about "
                   "several orders. Filter by status or by the date the order was placed. Returns each order's ID, "
                   "date, status, total and SKUs. To look up one order whose ID you know, use get_order_status "
                   "instead.",
    "get_order_status": "Look up where one order is: its status, dates, lines and total. Customers often write the "
                        "number alone (1873, #1873, o1873); pass it as O-1873. For a refund, or a question about how "
                        "much a refund would be, use quote_refund instead: it checks the order itself. If the ticket "
                        "gives no order ID, use find_orders.",
    "quote_refund": "Work out a refund without making it. Call this first for any refund request and for any question "
                    "about how much a refund would be; it checks the order itself, so you don't need "
                    "get_order_status first. For a delivered or returned order, it returns the amount, whether it is "
                    "within the refund policy's limit, and a quote_id that is valid for 15 minutes. Pass the quote_id "
                    "to issue_refund to make the refund.",
    "issue_refund": "Refund an order, using a quote from quote_refund. Pass the quote_id, not an amount; if you don't "
                    "have a quote_id, call quote_refund first. Calling again with the same quote_id returns the same "
                    "refund and never refunds twice. Refunds above the policy limit are held until a person confirms "
                    "them.",
    "check_stock": "How many of one product the shop has on hand in each warehouse, and when each was last counted. "
                   "Takes the product's SKU, such as KG-1031. A negative count means the product sold before a "
                   "recount caught a miscount; count it as none available.",
}


class Line(BaseModel):
    sku: str
    quantity: int
    unit_price: str = Field(description="Decimal string, such as 24.99")


class OrderDetail(BaseModel):
    order_id: str
    status: Status
    placed_on: date
    shipped_on: date | None
    delivered_on: date | None
    shipping_method: str
    lines: list[Line]
    total: str


class OrderSummary(BaseModel):
    order_id: str
    placed_on: date
    status: Status
    total: str
    skus: list[str]


class OrderList(BaseModel):
    customer_id: str
    orders: list[OrderSummary] = Field(description="Newest first")
    more: bool = Field(description="True if more orders matched than `limit` allowed")


class RefundQuote(BaseModel):
    quote_id: str = Field(description="Pass to issue_refund to refund this amount")
    order_id: str
    sku: str | None = Field(description="The product refunded, or null for the whole order")
    amount: str
    policy_limit: str
    within_limit: bool = Field(description="False means a person must confirm the refund")
    expires_in_seconds: int


class Refund(BaseModel):
    refund_id: str
    quote_id: str
    order_id: str
    amount: str
    status: Literal["requested", "needs_confirmation"]


class WarehouseStock(BaseModel):
    warehouse: str
    on_hand: int = Field(description="Negative if sold before a recount caught a miscount")
    last_counted: date


class StockReport(BaseModel):
    sku: str
    available: int = Field(description="Sum of the warehouses' positive counts")
    warehouses: list[WarehouseStock]


def _api(method: str, path: str, **kwargs) -> httpx2.Response | None:
    """Call the shop's API with the server's key. None for a 404; MCPError if the API rejects the key."""
    response = httpx2.request(method, f"{os.environ['SHOP_API_URL']}{path}",
                              headers={"X-API-Key": os.environ["SHOP_API_KEY"]}, timeout=5.0, **kwargs)
    if response.status_code == 401:
        raise MCPError(INTERNAL_ERROR, "The shop's API rejected this server's key. The server needs reconfiguring.")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response


def _cents(amount: str) -> int:
    whole, _, frac = amount.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def create_server(name: str = "shop-support", version: str = "0.3.0", *,
                  quotes: MutableMapping[str, dict] | None = None, auth: AuthSettings | None = None,
                  token_verifier: TokenVerifier | None = None) -> MCPServer:
    """The shop's server with its five tools. Each call makes a new server with an empty quote store, unless `quotes`
    gives it a store to share (chapter 6). `auth` and `token_verifier` go to `MCPServer` unchanged, to protect the
    server with OAuth over HTTP (chapter 8)."""
    server = MCPServer(name, version=version, auth=auth, token_verifier=token_verifier)
    quotes = {} if quotes is None else quotes
    lock = getattr(quotes, "lock", None) or threading.Lock()   # guards the once-only check

    def order_or_error(order_id: str) -> dict:
        response = _api("GET", f"/orders/{order_id}")
        if response is None:
            raise ToolError(f"The shop has no order {order_id}. Check the number with the customer, "
                            "or use find_orders to list their orders.")
        return response.json()

    @server.tool(title="Find a customer's orders", description=DESCRIPTIONS["find_orders"], annotations=READ_ONLY)
    def find_orders(customer_id: CustomerId, status: Status | None = None,
                    placed_since: Annotated[date | None, Field(description="Only orders placed on or after this "
                                                                           "date, YYYY-MM-DD")] = None,
                    limit: Annotated[int, Field(ge=1, le=50)] = 10) -> OrderList:
        params = {"customer_id": customer_id, "limit": 100, **({"status": status} if status else {})}
        found = [o for o in _api("GET", "/orders", params=params).json()["orders"]
                 if placed_since is None or date.fromisoformat(o["placed_on"]) >= placed_since]
        return OrderList(customer_id=customer_id, more=len(found) > limit, orders=[
            OrderSummary(order_id=o["order_id"], placed_on=o["placed_on"], status=o["status"], total=o["total"],
                         skus=[line["sku"] for line in o["lines"]]) for o in found[:limit]])

    @server.tool(title="Look up an order", description=DESCRIPTIONS["get_order_status"], annotations=READ_ONLY)
    def get_order_status(order_id: OrderId) -> OrderDetail:
        return OrderDetail.model_validate(order_or_error(order_id))

    @server.tool(title="Quote a refund", description=DESCRIPTIONS["quote_refund"], annotations=READ_ONLY)
    def quote_refund(order_id: OrderId,
                     sku: Annotated[Sku | None, Field(description="Refund only this product's line; leave out to "
                                                                  "refund the whole order")] = None,
                     reason: Annotated[str, Field(min_length=3, max_length=200)] = "customer request") -> RefundQuote:
        order = order_or_error(order_id)
        if order["status"] not in REFUNDABLE:
            raise ToolError(f"Order {order_id} is {order['status']}: the shop refunds only delivered or returned "
                            "orders. Use get_order_status to tell the customer where it is.")
        lines = [line for line in order["lines"] if sku is None or line["sku"] == sku]
        if not lines:
            raise ToolError(f"Order {order_id} has no line for {sku}. Its SKUs are "
                            f"{', '.join(line['sku'] for line in order['lines'])}.")
        cents = (_cents(order["total"]) if sku is None
                 else sum(line["quantity"] * _cents(line["unit_price"]) for line in lines))
        with lock:
            quote_id = "Q-" + secrets.token_hex(5)     # random, so it can't be worked out from the order
            while quote_id in quotes:
                quote_id = "Q-" + secrets.token_hex(5)
            quotes[quote_id] = {"order_id": order_id, "sku": sku, "cents": cents, "reason": reason,
                                "expires": time.monotonic() + QUOTE_TTL_SECONDS, "refund": None}
        return RefundQuote(quote_id=quote_id, order_id=order_id, sku=sku, amount=_money(cents),
                           policy_limit=_money(REFUND_LIMIT_CENTS), within_limit=cents <= REFUND_LIMIT_CENTS,
                           expires_in_seconds=QUOTE_TTL_SECONDS)

    @server.tool(title="Issue a refund", description=DESCRIPTIONS["issue_refund"], annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    def issue_refund(quote_id: Annotated[str, Field(pattern=r"^Q-[0-9a-f]{10}$",
                                                    description="From quote_refund, such as Q-3f9a0c21be")]) -> Refund:
        with lock:
            quote = quotes.get(quote_id)
            if quote is None:
                raise ToolError(f"There is no quote {quote_id}. Call quote_refund for the order to get a quote_id.")
            if quote["refund"] is not None:
                return quote["refund"]
            if time.monotonic() > quote["expires"]:
                raise ToolError(f"Quote {quote_id} has expired. Call quote_refund again for a new quote_id.")
            made = _api("POST", "/refunds", json={"order_id": quote["order_id"], "amount": _money(quote["cents"]),
                                                  "reason": quote["reason"]}).json()
            quote["refund"] = Refund(refund_id=made["refund_id"], quote_id=quote_id, order_id=made["order_id"],
                                     amount=made["amount"], status=made["status"])
            quotes[quote_id] = quote       # write back, for a store that keeps copies
            return quote["refund"]

    @server.tool(title="Check stock", description=DESCRIPTIONS["check_stock"], annotations=READ_ONLY)
    def check_stock(sku: Sku) -> StockReport:
        response = _api("GET", f"/stock/{sku}")
        if response is None:
            raise ToolError(f"The shop has no product {sku}. SKUs look like KG-1031.")
        levels = [WarehouseStock.model_validate(w) for w in response.json()["warehouses"]]
        return StockReport(sku=sku, available=sum(max(w.on_hand, 0) for w in levels), warehouses=levels)

    return server


def server_params(base_url: str, api_key: str | None = None) -> StdioServerParameters:
    """How a client launches this server over stdio, with the shop's API address and key in its environment."""
    from lib import shop_api
    env = shop_api.server_env(base_url, api_key or shop_api.DEMO_API_KEY)
    return StdioServerParameters(command=sys.executable, args=["-m", "lib.shop_tools", "--serve"], env=env,
                                 cwd=EXAMPLES)


# The first draft of DESCRIPTIONS, written as docstrings: the SDK passes a docstring through as written, so each
# line break and its indentation reached the model. `description-choices` recorded the model's choices with it.
DRAFT_DESCRIPTIONS = {
    'find_orders': "Search one customer's orders, newest first, when the ticket gives no order ID or asks about several\n        orders. Filter by status or by the date the order was placed. Returns each order's ID, date, status, total\n        and SKUs. To look up one order whose ID you know, use get_order_status instead.",
    'get_order_status': 'Look up one order by its ID: its status, dates, lines and total. Customers often write the number alone\n        (1873, #1873, o1873); pass it as O-1873. If the ticket gives no order ID, use find_orders instead.',
    'quote_refund': 'Work out what the shop would refund on a delivered or returned order, without refunding anything:\n        the amount, whether it is within the refund policy\'s limit, and a quote_id. Use it to answer "how much would\n        I get back" and as the first step of any refund. The quote_id is valid for 15 minutes; pass it to\n        issue_refund to make the refund.',
    'issue_refund': "Refund an order, using a quote from quote_refund. Pass the quote_id, not an amount; if you don't have a\n        quote_id, call quote_refund first. Calling again with the same quote_id returns the same refund and never\n        refunds twice. Refunds above the policy limit are held until a person confirms them.",
    'check_stock': "How many of one product the shop has on hand in each warehouse, and when each was last counted. Takes the\n        product's SKU, such as KG-1031. A negative count means the product sold before a recount caught a miscount;\n        count it as none available.",
}

# One-line descriptions of the kind an endpoint-to-tool generator writes.
VAGUE_DESCRIPTIONS = {
    "find_orders": "Get orders.",
    "get_order_status": "Get an order.",
    "quote_refund": "Refund quote.",
    "issue_refund": "Refund an order.",
    "check_stock": "Get stock.",
}


def with_descriptions(tools: list[Tool], descriptions: dict[str, str]) -> list[Tool]:
    """The same tools, in the same order, with only each tool's `description` replaced."""
    return [tool.model_copy(update={"description": descriptions[tool.name]}) for tool in tools]


def _endpoint_tool(name: str, description: str, properties: dict, required: list[str]) -> Tool:
    return Tool(name=name, description=description,
                input_schema={"type": "object", "properties": properties, "required": required})


def endpoint_tools() -> list[Tool]:
    """One tool per endpoint of the shop's API, as an endpoint-to-tool generator writes them: named after the method
    and path, described by the endpoint's one-line summary, with the endpoint's parameters as plain types."""
    text, integer, number = {"type": "string"}, {"type": "integer"}, {"type": "number"}
    return [
        _endpoint_tool("get_orders", "List orders, newest first.",
                       {"customer_id": text, "status": text, "limit": integer}, []),
        _endpoint_tool("get_orders_by_order_id", "Get one order.", {"order_id": text}, ["order_id"]),
        _endpoint_tool("get_stock_by_sku", "Get stock for a SKU.", {"sku": text}, ["sku"]),
        _endpoint_tool("post_refunds", "Create a refund.",
                       {"order_id": text, "amount": number, "reason": text}, ["order_id", "amount"]),
        _endpoint_tool("post_stock_by_sku_recount", "Recount stock for a SKU.",
                       {"sku": text, "seconds": number}, ["sku"]),
    ]


if __name__ == "__main__":
    if "--serve" in sys.argv:
        create_server().run()
