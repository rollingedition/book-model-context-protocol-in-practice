"""Five failures and the path each takes: three tool execution errors the model reads (isError results), a crash the
model sees only as a generic message, and a protocol error (a JSON-RPC error) that only the host sees."""
import asyncio

from mcp import Client, MCPError

from lib import loopback, shop_api, shop_tools
from lib.host import ReplayModel, choose_tool
from lib.shop_data import load_shop


async def attempt(params, name: str, arguments: dict, label: str) -> None:
    async with Client(params) as client:
        try:
            result = await client.call_tool(name, arguments)
            print(f"{label} is error:", result.is_error)
            print(f"{label} says:", result.content[0].text)
        except MCPError as error:
            print(f"{label} JSON-RPC error code:", error.code)
            print(f"{label} JSON-RPC error message:", error.message)


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        params = shop_tools.server_params(base_url)
        async with Client(params) as client:          # T-0006's recorded choice, with the SKU the model made up
            tools = (await client.list_tools()).tools
        choice = choose_tool(ReplayModel("description-choices"), load_shop().ticket("T-0006"), tools)
        await attempt(params, choice.tool, choice.arguments, "wrong SKU")
        await attempt(params, "issue_refund", {"quote_id": "Q-0000000000"}, "unknown quote")
        await attempt(params, "refund_order", {"order_id": "O-2289"}, "unknown tool")
        await attempt(shop_tools.server_params(base_url, api_key="wrong-key"), "get_order_status",
                      {"order_id": "O-2289"}, "rejected key")
    await attempt(params, "get_order_status", {"order_id": "O-2289"}, "API down")    # the API has stopped


asyncio.run(main())
