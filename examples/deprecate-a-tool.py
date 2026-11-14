"""Retire find_orders in favour of find_orders_v2 over three releases, watched by a listening client and a caching
client. The prose's point rests on the caching client's list and on the last line, the error the old name returns
after the window."""
import asyncio

from mcp import Client
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

from lib import confirmations, loopback, shop_tools
from lib.testing import shop_api_here

bus, tools = InMemorySubscriptionBus(), confirmations.chapter3_tools()
server = MCPServer("shop-support", version="0.11.0", tools=list(tools.values()), subscriptions=bus,
                   cache_hints={"tools/list": CacheHint(ttl_ms=60_000, scope="public")})   # a minute: short while a change is under way
old = tools["find_orders"]


def find_orders_v2(customer_id: shop_tools.CustomerId, sku: shop_tools.Sku | None = None) -> shop_tools.OrderList:
    """Search one customer's orders, newest first, optionally only those with one product's SKU."""
    found = old.fn(customer_id, limit=50)
    return found.model_copy(update={"orders": [o for o in found.orders if sku is None or sku in o.skus]})


def retired(customer_id: shop_tools.CustomerId) -> shop_tools.OrderList:
    raise ToolError("find_orders was retired. Call find_orders_v2 with the same customer_id.")


async def replace_find_orders(fn, description: str) -> None:
    server.remove_tool("find_orders")
    server.add_tool(fn, name="find_orders", title=old.title, description=description, annotations=old.annotations)
    await bus.publish(ToolsListChanged())                     # to every client listening for list changes


async def main() -> None:
    with shop_api_here(), loopback.serve(server.streamable_http_app()) as base_url:
        async with Client(base_url + "/mcp") as listening, Client(base_url + "/mcp") as cached:
            listing, _ = await cached.list_tools(), await listening.list_tools()     # both cache release 1's list
            print("release 1:", f"{len(listing.tools)} tools, ttlMs {listing.ttl_ms}")
            async with listening.listen(tools_list_changed=True) as changes:   # a stream that carries list-change events
                server.add_tool(find_orders_v2)                                       # release 2: the replacement first
                await replace_find_orders(old.fn, "Deprecated: use find_orders_v2. " + old.description)
                print("event:", type(await anext(changes)).__name__)
            print("listening client sees:", ", ".join(t.name for t in (await listening.list_tools()).tools))
            print("cached client sees:", ", ".join(t.name for t in (await cached.list_tools()).tools))
            during = await cached.call_tool("find_orders", {"customer_id": "C-0127"})
            print("find_orders during the window:", "tool error" if during.is_error else "result")
            await replace_find_orders(retired, "Retired: use find_orders_v2.")         # release 3: the old name now errors
            after = await cached.call_tool("find_orders", {"customer_id": "C-0127"})
            print("find_orders after the window:", after.content[0].text)


asyncio.run(main())
