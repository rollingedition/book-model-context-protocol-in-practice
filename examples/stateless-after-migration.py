"""Ports the 2025 server's per-connection quote to SDK 2.x unchanged, then with the handle the pinned revision asks for.
The prose's point rests on the session-keyed failure, the count of session objects, and the handle's refund line."""
import asyncio
import os

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lib import confirmations, loopback, shop_api, shop_tools

chapter3 = confirmations.chapter3_tools()          # quote_refund and issue_refund from lib.shop_tools
server = MCPServer("shop-support", version="0.12.0")
quotes = {}                                        # the 2025 code: each connection's open quote, by its session
sessions_seen = set()


@server.tool(description="Quote a refund for a whole order, for issue_refund to refund.")
def quote_refund(order_id: str, ctx: Context) -> str:
    sessions_seen.add(id(ctx.session))       # each request gets its own session object at the pinned revision
    quotes[ctx.session] = chapter3["quote_refund"].fn(order_id, sku="KG-1050")   # chapter 3's quote needs a SKU; the port pins one
    return f"Quoted {quotes[ctx.session].amount}."


@server.tool(description="Refund the quote this connection made last.")
def issue_refund(ctx: Context) -> shop_tools.Refund:
    sessions_seen.add(id(ctx.session))
    if ctx.session not in quotes:
        raise ToolError("There is no open quote in this session. Call quote_refund first.")
    return chapter3["issue_refund"].fn(quotes.pop(ctx.session).quote_id)   # pop: a quote is used once


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))      # both servers run in this process
        with loopback.serve(server.streamable_http_app()) as old, \
             loopback.serve(shop_tools.create_server().streamable_http_app()) as new:
            async with Client(old + "/mcp") as client:
                await client.call_tool("quote_refund", {"order_id": "O-2415"})
                print("session-keyed issue_refund:", (await client.call_tool("issue_refund", {})).content[0].text)
                print("session objects in two calls:", len(sessions_seen))
            async with Client(new + "/mcp") as client:
                quote = await client.call_tool("quote_refund", {"order_id": "O-2415", "sku": "KG-1050"})
                refund = await client.call_tool("issue_refund", {"quote_id": quote.structured_content["quote_id"]})
                print("handle issue_refund:", refund.structured_content["status"], refund.structured_content["amount"])


asyncio.run(main())
