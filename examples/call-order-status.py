"""Launch the shop's server over stdio and call get_order_status for a real order and a wrong one, then for a server
 started without the shop's variables. The asserts pin the error flags the prose states: a real order is not an error, and a wrong ID is."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters
from mcp.types import Implementation

from lib import loopback, shop_api

SHOP_HOST = Implementation(name="shop-host", version="0.1.0")  # the name the server's logs and the wire show


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        env = {"SHOP_API_URL": base_url, "SHOP_API_KEY": shop_api.DEMO_API_KEY}  # the only two variables the server reads
        # relative to the examples folder, where examples run, so the server file is found
        params = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"], env=env)
        async with Client(params, client_info=SHOP_HOST) as client:
            print("protocol revision:", client.protocol_version)
            print("server:", client.server_info.name, client.server_info.version)
            result = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            assert result.is_error is False        # a real order comes back as a result, not an error
            # the tool returns the order as JSON text in its first content block
            print("order status:", json.loads(result.content[0].text)["status"])
            wrong = await client.call_tool("get_order_status", {"order_id": "O-7144"})
            assert wrong.is_error is True          # an unknown order is a failed tool result, not an exception
            print("wrong ID says:", wrong.content[0].text)

        # no env=, so the server starts without the shop's variables and its tool fails at the first call
        no_env = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"])
        async with Client(no_env, client_info=SHOP_HOST) as client:
            broken = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            print("without env says:", broken.content[0].text)


asyncio.run(main())
