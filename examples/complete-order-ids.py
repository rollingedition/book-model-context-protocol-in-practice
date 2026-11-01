"""Complete order IDs for shop://orders/{order_id}, offering only the orders of the customer the server acts for."""
import asyncio
import os
import sys

from mcp import Client, MCPError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.types import Completion, ResourceTemplateReference

from lib import loopback, shop_api, shop_reads
server = MCPServer("shop-support", version="0.4.0")


@server.resource("shop://orders/{order_id}", title="One of your orders", mime_type="application/json")
async def order(order_id: str) -> dict:
    found = await shop_reads.get_order(order_id)                     # checks the ID's format before the API sees it
    if found is None or found["customer_id"] != os.environ["SHOP_CUSTOMER_ID"]:
        raise ResourceNotFoundError(f"You have no order {order_id}.")   # the same answer either way
    return found


@server.completion()
async def complete(ref, argument, context) -> Completion | None:
    if not isinstance(ref, ResourceTemplateReference) or argument.name != "order_id":
        return None
    page = await shop_reads.get_json("/orders", customer_id=os.environ["SHOP_CUSTOMER_ID"], limit=100)  # newest first
    matches = [o["order_id"] for o in page["orders"] if o["order_id"].startswith(argument.value.upper())]
    cut_short = page["total"] > len(page["orders"])          # older orders the API didn't return may match too
    return Completion(values=matches, total=None if cut_short else len(matches), has_more=cut_short)


async def main() -> None:
    print("shop orders starting O-2:", shop_reads.orders_starting("O-2"))
    print("most orders for one customer:", shop_reads.most_orders_per_customer())
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(shop_reads.server_params(__file__, base_url, SHOP_CUSTOMER_ID="C-0127")) as client:
            for typed in ("O-2", "o-24"):
                ref = ResourceTemplateReference(uri="shop://orders/{order_id}")
                result = (await client.complete(ref, {"name": "order_id", "value": typed})).completion
                print(f"{typed} offers:", ", ".join(result.values), f"({result.total} in all)")
            for order_id in ("O-1767", "O-7144"):                 # another customer's order, and nobody's
                try:
                    await client.read_resource(f"shop://orders/{order_id}")
                except MCPError as err:
                    print(f"{order_id} answer:", err.error.code, err.error.message)


if __name__ == "__main__":
    server.run() if "--serve" in sys.argv else asyncio.run(main())
