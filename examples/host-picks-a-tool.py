"""The book's host loop shows three tickets and the server's tools to a model, then calls the tool the model chooses, from recorded replies in examples/data/recorded/. The point rests on the three `tool` lines."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters
from mcp.types import Implementation

from lib import loopback, shop_api
from lib.host import ReplayModel, choose_tool
from lib.shop_data import load_shop

model = ReplayModel("pick-a-tool")  # answers only with the replies recorded for these exact messages


async def main() -> None:
    shop = load_shop()
    with loopback.serve(shop_api.create_app()) as base_url:
        params = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"],
                                       env=shop_api.server_env(base_url))
        async with Client(params, client_info=Implementation(name="shop-host", version="0.1.0")) as client:
            tools = (await client.list_tools()).tools
            for ticket_id in ("T-0003", "T-0010", "T-0015"):
                ticket = shop.ticket(ticket_id)
                # the longest paragraph of the ticket, which holds the customer's question
                print(f"{ticket_id} asks:", max(ticket.body.split("\n\n"), key=len))
                choice = choose_tool(model, ticket, tools)
                print(f"{ticket_id} tool:", choice.tool or "none")
                if choice.tool is None:  # the model answered in words, so there is no call to make
                    print(f"{ticket_id} reply:", choice.reply[:72] + "…")  # a reply can run long, so the output shows only its opening
                    continue
                print(f"{ticket_id} order id:", choice.arguments.get("order_id"))
                result = await client.call_tool(choice.tool, choice.arguments)
                print(f"{ticket_id} order status:", json.loads(result.content[0].text)["status"])


asyncio.run(main())
