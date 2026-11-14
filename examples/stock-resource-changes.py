"""Watches two products with subscriptions/listen, records recounts while a stream is open and while it is closed, and re-reads after each.
The point rests on the first event, which arrives, and on the re-listening line, which shows that nothing is replayed."""
import asyncio
import sys

import anyio
from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from lib.shop_data import WAREHOUSES, load_shop
from lib.shop_reads import stock_summary

server = MCPServer("shop-support", version="0.4.0")
counts = {(s.sku, s.warehouse): s.on_hand for s in load_shop().stock}   # stands in for the shop's stock system


@server.resource("shop://stock/{sku}", title="On-hand stock for one product", mime_type="application/json")
def stock(sku: str) -> dict:
    if (sku, WAREHOUSES[0]) not in counts:              # a product exists if the first warehouse has a count for it
        raise ResourceNotFoundError(f"The shop sells no product {sku}.")
    return {warehouse: counts[sku, warehouse] for warehouse in WAREHOUSES}


@server.tool()
async def set_on_hand(sku: str, warehouse: str, counted: int, ctx: Context) -> str:
    """Record a warehouse's recount of one product, replacing its on-hand count."""
    counts[sku, warehouse] = counted
    await ctx.notify_resource_updated(f"shop://stock/{sku}")  # the exact URI clients watch; another spelling never matches
    return f"{sku} in {warehouse}: {counted}"


async def main() -> None:
    watched = ["shop://stock/KG-1018", "shop://stock/KG-9999"]           # KG-9999 doesn't exist
    async with Client(StdioServerParameters(command=sys.executable, args=[__file__, "--serve"], env={})) as client:
        async with client.listen(resource_subscriptions=watched) as changes:
            print("honoured:", " and ".join(changes.honored.resource_subscriptions))
            print("before:", await stock_summary(client, watched[0]))  # watched[0] is KG-1018
            # KG-1026 isn't watched, so this recount sends nothing on the stream
            await client.call_tool("set_on_hand", {"sku": "KG-1026", "warehouse": "north", "counted": 0})
            # KG-1018 is watched, so its update reaches the open stream
            await client.call_tool("set_on_hand", {"sku": "KG-1018", "warehouse": "south", "counted": 4})
            print("first event:", (await anext(changes)).uri)
            print("after:", await stock_summary(client, watched[0]))  # watched[0] is KG-1018
        # recorded while no stream is open, so no stream can hear it
        await client.call_tool("set_on_hand", {"sku": "KG-1018", "warehouse": "south", "counted": 3})
        async with client.listen(resource_subscriptions=watched) as changes:
            with anyio.move_on_after(1.0) as waited:                      # wait a second for anything replayed
                await anext(changes)
            print("events after re-listening:", 0 if waited.cancelled_caught else "at least 1")
            print("re-read:", await stock_summary(client, watched[0]))  # watched[0] is KG-1018


if __name__ == "__main__":
    server.run() if "--serve" in sys.argv else asyncio.run(main())
