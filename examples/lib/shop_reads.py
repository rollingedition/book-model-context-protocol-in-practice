"""Async reads from the shop's API, for MCP servers whose resources and prompts wrap it (chapter 4).

A server launched over stdio finds the API in its environment, as `lib.shop_api.server_env()` sets it: `SHOP_API_URL`
and `SHOP_API_KEY`. `get_json()` makes one GET with the key and returns the JSON body, or None when the API answers
404, so the caller decides what a miss means for its own primitive (a `ResourceNotFoundError` for a resource, an
invalid-params error for a prompt). Any other error status raises `httpx2.HTTPStatusError`.

    from lib.shop_reads import get_json
    order = await get_json("/orders/O-2476")                         # dict, or None if there is no such order
    mine = await get_json("/orders", customer_id="C-0127", limit=100)

It also holds the setup chapter 4's examples share, so each example shows only what its section teaches:
`get_order()` checks an order ID's format (`O-` and four digits) before the API sees it, `server_params()` launches an
example's own file as a stdio server for the API, `stock_summary()` reads a `shop://stock/{sku}` resource as one line,
and `orders_starting()` and `most_orders_per_customer()` count over the shop's data.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

import httpx2
from mcp import Client, StdioServerParameters

from lib.shop_api import server_env
from lib.shop_data import load_shop


async def get_json(path: str, **query) -> dict | None:
    """GET `path` on the shop's API with the key from the environment: the JSON body, or None on 404."""
    async with httpx2.AsyncClient(base_url=os.environ["SHOP_API_URL"], timeout=5.0) as http:
        response = await http.get(path, params=query, headers={"X-API-Key": os.environ["SHOP_API_KEY"]})
    if response.status_code == 404:
        return None
    return response.raise_for_status().json()


async def get_order(order_id: str) -> dict | None:
    """One order by its ID, or None if the ID isn't in the shop's format or the API has no such order."""
    return await get_json(f"/orders/{order_id}") if re.fullmatch(r"O-\d{4}", order_id) else None


def server_params(script: str, base_url: str, **env: str) -> StdioServerParameters:
    """Launch `script --serve` over stdio, with the shop's API in its environment and any extra variables."""
    return StdioServerParameters(command=sys.executable, args=[script, "--serve"], env={**server_env(base_url), **env})


async def stock_summary(client: Client, uri: str) -> str:
    """Read a `shop://stock/{sku}` resource and return its counts as one line, such as "north 2, south -6"."""
    by_warehouse = json.loads((await client.read_resource(uri)).contents[0].text)
    return ", ".join(f"{warehouse} {count}" for warehouse, count in by_warehouse.items())


def orders_starting(prefix: str) -> int:
    """How many of the shop's orders have IDs that start with `prefix`, across every customer."""
    return sum(o.order_id.startswith(prefix) for o in load_shop().orders)


def most_orders_per_customer() -> int:
    """The largest number of orders any one customer has in the shop's data."""
    return max(Counter(o.customer_id for o in load_shop().orders).values())
