"""The 2025 way to confirm a refund, which fails at revision 2026-07-28: issue_refund calls ctx.elicit() and waits,
but the protocol gives the server no channel back to the client. The printed error code and the count of questions
the user saw show the failure, before anyone is asked."""
import asyncio
import sys

from mcp import Client, MCPError
from mcp.server.mcpserver import Context
from mcp.types import ElicitResult
from pydantic import BaseModel

from lib import confirmations, loopback, shop_api, shop_tools

server, held = confirmations.shop_server()     # chapter 3's other tools; held is chapter 3's issue_refund
asked = []                                     # every question that reached the user


class Release(BaseModel):
    release: bool


@server.tool(title="Issue a refund", description=shop_tools.DESCRIPTIONS["issue_refund"], annotations=held.annotations)
async def issue_refund(quote_id: confirmations.QuoteId, ctx: Context) -> shop_tools.Refund:
    refund = held.fn(quote_id)
    if refund.status == "needs_confirmation":   # ask, and hold the call open until the answer comes back
        answer = await ctx.elicit(f"Refund {refund.amount} on order {refund.order_id}?", Release)
        if answer.action == "accept" and answer.data.release:
            return confirmations.release(refund)
    return refund


async def say_yes(context, params) -> ElicitResult:   # a scripted user, who would release the refund
    asked.append(params.message)
    return ElicitResult(action="accept", content={"release": True})


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(confirmations.launch(__file__, base_url), elicitation_callback=say_yes) as client:   # starts this file with --serve
            print("protocol revision:", client.protocol_version)
            quote = (await client.call_tool("quote_refund", {"order_id": "O-2289"})).structured_content
            try:
                await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
            except MCPError as error:
                print("error code:", error.error.code)
                print("error message:", error.error.message)
            print("questions the user saw:", len(asked))


server.run() if "--serve" in sys.argv else asyncio.run(main())   # the client runs this file with --serve; run directly, it starts the client
