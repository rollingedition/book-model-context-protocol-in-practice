"""Launch the shop's server over stdio, call get_order_status twice, and show what a missing environment does."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters
from mcp.types import Implementation

from lib import loopback, shop_api

SHOP_HOST = Implementation(name="shop-host", version="0.1.0")


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        env = {"SHOP_API_URL": base_url, "SHOP_API_KEY": shop_api.DEMO_API_KEY}
        params = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"], env=env)
        async with Client(params, client_info=SHOP_HOST) as client:
            print("protocol revision:", client.protocol_version)
            print("server:", client.server_info.name, client.server_info.version)
            result = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            print("is error:", result.is_error)
            print("order status:", json.loads(result.content[0].text)["status"])
            wrong = await client.call_tool("get_order_status", {"order_id": "O-7144"})
            print("wrong ID is error:", wrong.is_error)
            print("wrong ID says:", wrong.content[0].text)

        no_env = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"])
        async with Client(no_env, client_info=SHOP_HOST) as client:
            broken = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            print("without env says:", broken.content[0].text)


asyncio.run(main())
