"""The shop's existing HTTP API: the "before" that the book's MCP servers wrap.

A small Starlette app over `lib.shop_data`. Every request needs the API key in the `X-API-Key` header; without it the
API answers 401. Money is a decimal string ("24.99"), dates are ISO 8601.

    GET  /orders/{order_id}            one order: status, dates, lines, total            (404 if unknown)
    GET  /orders?customer_id=C-0042    a customer's orders, newest first (also: status=, limit=, default 20)
    GET  /stock/{sku}                  on-hand count per warehouse and the last recount date (404 if unknown)
    POST /refunds                      {"order_id", "amount", "reason"}: records a refund request. Above the policy
                                       limit it is held with status "needs_confirmation" (422 if the amount is more
                                       than the order's total)
    POST /refunds/{refund_id}/confirm  releases a held refund: its status becomes "requested" (404 if unknown, 409 if
                                       it isn't held); added for chapter 5
    POST /refunds/{refund_id}/cancel   cancels a held refund: its status becomes "cancelled" (404, 409 as above)
    POST /stock/{sku}/recount         a slow recount: waits `seconds` (default 3, at most 30), then returns the count

Use it with `lib.loopback.serve`:

    from lib import loopback, shop_api
    with loopback.serve(shop_api.create_app()) as base_url:
        httpx2.get(f"{base_url}/orders/O-1873", headers={"X-API-Key": shop_api.DEMO_API_KEY})

The app keeps refunds it records in memory, per app: each `create_app()` starts from the generated data.
"""
from __future__ import annotations

import asyncio
import secrets

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lib.shop_data import REFUND_LIMIT_CENTS, Order, Shop, load_shop, money

API_KEY_HEADER = "X-API-Key"
DEMO_API_KEY = "demo-shop-key-not-a-secret"   # a fixed key for the examples; a real deployment reads its own


def server_env(base_url: str, api_key: str = DEMO_API_KEY) -> dict[str, str]:
    """The environment an MCP server launched over stdio needs to reach the shop's API: SHOP_API_URL and
    SHOP_API_KEY. The stdio client passes only a short allowlist of the parent's variables, so pass these as `env=`."""
    return {"SHOP_API_URL": base_url, "SHOP_API_KEY": api_key}


def order_json(order: Order) -> dict:
    """An order as the API returns it."""
    return {
        "order_id": order.order_id, "customer_id": order.customer_id, "status": order.status,
        "placed_on": order.placed_on.isoformat(),
        "shipped_on": order.shipped_on.isoformat() if order.shipped_on else None,
        "delivered_on": order.delivered_on.isoformat() if order.delivered_on else None,
        "shipping_method": order.shipping_method,
        "lines": [{"sku": line.sku, "quantity": line.quantity, "unit_price": money(line.unit_price_cents)}
                  for line in order.lines],
        "total": money(order.total_cents), "payment": order.payment,
    }


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def _cents(value) -> int | None:
    try:
        whole, _, frac = str(value).partition(".")
        return int(whole) * 100 + int((frac + "00")[:2]) if len(frac) <= 2 else None
    except ValueError:
        return None


def create_app(shop: Shop | None = None, api_key: str = DEMO_API_KEY) -> Starlette:
    """The shop's API over `shop` (default: `load_shop()`), accepting only `api_key`."""
    shop = shop or load_shop()
    refunds: list[dict] = []

    def authorized(request: Request) -> bool:
        return secrets.compare_digest(request.headers.get(API_KEY_HEADER, ""), api_key)

    def guarded(handler):
        async def endpoint(request: Request):
            if not authorized(request):
                return _error(401, "unauthorized", f"missing or wrong {API_KEY_HEADER} header")
            return await handler(request)
        return endpoint

    async def get_order(request: Request):
        order = shop.order(request.path_params["order_id"])
        if order is None:
            return _error(404, "order_not_found", f"no order {request.path_params['order_id']}")
        return JSONResponse(order_json(order))

    async def list_orders(request: Request):
        q = request.query_params
        found = [o for o in reversed(shop.orders)
                 if (not q.get("customer_id") or o.customer_id == q["customer_id"])
                 and (not q.get("status") or o.status == q["status"])]
        limit = min(int(q.get("limit", 20)), 100)
        return JSONResponse({"orders": [order_json(o) for o in found[:limit]], "total": len(found)})

    async def get_stock(request: Request):
        sku = request.path_params["sku"]
        levels = shop.stock_for(sku)
        if not levels:
            return _error(404, "sku_not_found", f"no product {sku}")
        return JSONResponse({"sku": sku, "warehouses": [
            {"warehouse": s.warehouse, "on_hand": s.on_hand, "last_counted": s.last_counted.isoformat()}
            for s in levels]})

    async def create_refund(request: Request):
        body = await request.json()
        order = shop.order(str(body.get("order_id", "")))
        if order is None:
            return _error(404, "order_not_found", f"no order {body.get('order_id')}")
        cents = _cents(body.get("amount"))
        if cents is None or cents <= 0 or cents > order.total_cents:
            return _error(422, "invalid_amount", f"amount must be between 0.01 and {money(order.total_cents)}")
        status = "needs_confirmation" if cents > REFUND_LIMIT_CENTS else "requested"
        refund = {"refund_id": f"R-{len(shop.refunds) + len(refunds) + 1:04d}", "order_id": order.order_id,
                  "amount": money(cents), "reason": str(body.get("reason", "")), "status": status,
                  "policy_limit": money(REFUND_LIMIT_CENTS)}
        refunds.append(refund)
        return JSONResponse(refund, status_code=201)

    def decide_held_refund(status: str):
        """An endpoint that moves a held refund to `status`, once: a refund that isn't held answers 409."""
        async def endpoint(request: Request):
            refund_id = request.path_params["refund_id"]
            refund = next((r for r in refunds if r["refund_id"] == refund_id), None)
            if refund is None:
                return _error(404, "refund_not_found", f"no refund {refund_id}")
            if refund["status"] != "needs_confirmation":
                return _error(409, "refund_not_held", f"refund {refund_id} is {refund['status']}, not held")
            refund["status"] = status
            return JSONResponse(refund)
        return endpoint

    async def recount(request: Request):
        sku = request.path_params["sku"]
        levels = shop.stock_for(sku)
        if not levels:
            return _error(404, "sku_not_found", f"no product {sku}")
        await asyncio.sleep(min(float(request.query_params.get("seconds", 3)), 30))
        return JSONResponse({"sku": sku, "counted": sum(max(s.on_hand, 0) for s in levels)})

    return Starlette(routes=[
        Route("/orders", guarded(list_orders)),
        Route("/orders/{order_id}", guarded(get_order)),
        Route("/stock/{sku}", guarded(get_stock)),
        Route("/stock/{sku}/recount", guarded(recount), methods=["POST"]),
        Route("/refunds", guarded(create_refund), methods=["POST"]),
        Route("/refunds/{refund_id}/confirm", guarded(decide_held_refund("requested")), methods=["POST"]),
        Route("/refunds/{refund_id}/cancel", guarded(decide_held_refund("cancelled")), methods=["POST"]),
    ])
