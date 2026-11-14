"""quote_refund returns a pydantic model, so the SDK publishes its output schema and returns structuredContent; a tool
that returns a bare string gets a {"result": ...} wrapper instead. The point rests on the bare structured content line,
and the quote's within-limit flag and text block, which the code asserts."""
import asyncio
import json

from mcp import Client
from mcp.server.mcpserver import MCPServer

from lib import loopback, shop_api, shop_tools
from lib.shop_data import load_shop, money

bare = MCPServer("bare-return")


@bare.tool()
def refund_amount(order_id: str) -> str:
    """The refund for a whole order, as a decimal string."""
    return money(load_shop().order(order_id).total_cents)


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(shop_tools.server_params(base_url)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            print("output schema requires:", ", ".join(tools["quote_refund"].output_schema["required"]))
            quote = await client.call_tool("quote_refund", {"order_id": "O-2289", "reason": "arrived cracked"})
            shown = {**quote.structured_content, "quote_id": "(random)"}      # quote IDs differ on every run
            print("structured content:", json.dumps(shown))
            print("amount:", quote.structured_content["amount"])
            print("within limit:", quote.structured_content["within_limit"])
            assert quote.structured_content["within_limit"] is False
            # the lifetime is in seconds; the prose gives it in minutes
            print("quote lifetime minutes:", quote.structured_content["expires_in_seconds"] // 60)
            # the text block a client that reads only text gets, parsed back to JSON
            same_json = json.loads(quote.content[0].text) == quote.structured_content
            print("text block is the same JSON:", same_json)
            assert same_json

    async with Client(bare) as client:                  # in-process: no wire needed to read a schema
        tool = (await client.list_tools()).tools[0]
        print("bare output schema:", json.dumps(tool.output_schema))
        result = await client.call_tool("refund_amount", {"order_id": "O-2289"})
        print("bare structured content:", json.dumps(result.structured_content))


asyncio.run(main())
