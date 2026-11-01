"""The stock recount behind chapter 6's `recount_stock` tool: one slow call to the shop's API per product.

    from lib import recount
    async with recount.api() as api:                   # the shop's API, with the server's key
        for n, sku in enumerate(recount.SKUS, 1):
            units = await recount.one(api, sku)        # POST /stock/{sku}/recount; both warehouses' count

`SKUS` is every product in the shop's data, in catalogue order: the shop's API has no endpoint that lists products.
`one` asks the API to recount one SKU, waiting `SECONDS_PER_SKU` unless told otherwise (the API's own `seconds` parameter), and returns
the units it counted. `Recount` is the tool's result. The API's address and key come from the environment, as
`lib.shop_api.server_env()` sets them.
"""
from __future__ import annotations

import os

import httpx2
from pydantic import BaseModel

from lib.shop_data import load_shop

SKUS = tuple(product.sku for product in load_shop().products)
SECONDS_PER_SKU = 0.02           # the shop's real recount takes seconds per product; the examples keep it short


class Recount(BaseModel):
    skus: int                    # products recounted
    units: int                   # units on hand across both warehouses


def api() -> httpx2.AsyncClient:
    """An async client for the shop's API, with the server's key."""
    return httpx2.AsyncClient(base_url=os.environ["SHOP_API_URL"], timeout=10.0,
                              headers={"X-API-Key": os.environ["SHOP_API_KEY"]})


async def one(client: httpx2.AsyncClient, sku: str, seconds: float = SECONDS_PER_SKU) -> int:
    """Recount one SKU in both warehouses, the API taking `seconds`, and return the units counted."""
    response = await client.post(f"/stock/{sku}/recount", params={"seconds": seconds})
    response.raise_for_status()
    return response.json()["counted"]
