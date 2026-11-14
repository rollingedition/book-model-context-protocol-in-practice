"""The shop's first MCP server: one tool, get_order_status, that wraps GET /orders/{order_id} on the shop's API. The
 point rests on the description and schema lines, the only parts of the tool a model reads."""
import asyncio
import json
import os
import sys

import httpx2
from mcp import Client, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

server = MCPServer("shop-orders", version="0.1.0")


@server.tool()
def get_order_status(order_id: str) -> dict:
    """Look up one of the shop's orders by its ID, such as O-1873: its status, dates, lines and total."""
    # read on each call: a missing variable raises KeyError here, and the SDK reports only a generic error
    response = httpx2.get(f"{os.environ['SHOP_API_URL']}/orders/{order_id}",
                          headers={"X-API-Key": os.environ["SHOP_API_KEY"]},
                          timeout=5.0)  # seconds; a slow shop API fails this call instead of holding the worker
    # the shop answers 404 for an order it doesn't have, so the model gets a message it can act on
    if response.status_code == 404:
        raise ToolError(f"The shop has no order {order_id}. Order IDs look like O-1873.")
    response.raise_for_status()  # any other failure, such as a wrong key, stays on the server as an HTTPError
    return response.json()


async def show_tools() -> None:
    from lib import loopback, shop_api
    with loopback.serve(shop_api.create_app()) as base_url:
        # the API's address and key are the only variables the server gets
        params = StdioServerParameters(command=sys.executable, args=[__file__, "--serve"],
                                       env=shop_api.server_env(base_url))
        async with Client(params) as client:
            for tool in (await client.list_tools()).tools:
                print("tool:", tool.name)
                print("description:", tool.description)
                print("input schema:", json.dumps(tool.input_schema))


if __name__ == "__main__":
    if "--serve" in sys.argv:
        server.run()                  # stdio is the default transport
    else:
        asyncio.run(show_tools())
