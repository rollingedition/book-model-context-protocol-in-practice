"""The 2025 server's pushed confirmation becomes a resolver's question, and its log line goes to stderr."""
import asyncio
import logging
import os
from typing import Annotated

from mcp import Client
from mcp.server.mcpserver import Elicit, Resolve
from pydantic import BaseModel

from lib import confirmations, loopback, shop_api, shop_tools

server, held = confirmations.shop_server(version="0.12.0")   # chapter 3's other tools; held is its issue_refund
log = logging.getLogger("shop-support")                       # to stderr, not to the client


class Release(BaseModel):
    release: bool


def confirm(quote_id: confirmations.QuoteId) -> Elicit[Release] | Release:
    refund = held.fn(quote_id)                                # the same quote always gives the same refund
    if refund.status != "needs_confirmation":
        return Release(release=False)                         # nothing held, so nothing to ask
    return Elicit(f"Refund {refund.amount} on order {refund.order_id}? It is above the policy limit.", Release)


@server.tool(description=shop_tools.DESCRIPTIONS["issue_refund"], annotations=held.annotations)
def issue_refund(quote_id: confirmations.QuoteId, answer: Annotated[Release, Resolve(confirm)]) -> shop_tools.Refund:
    refund = held.fn(quote_id)
    if refund.status == "needs_confirmation" and answer.release:
        refund = confirmations.release(refund)
    log.info("refund %s is %s", refund.refund_id, refund.status)
    return refund


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))      # the server runs in this process
        with loopback.serve(server.streamable_http_app()) as url:
            async with Client(url + "/mcp", elicitation_callback=confirmations.say_yes) as client:
                quote = (await client.call_tool("quote_refund", {"order_id": "O-2289"})).structured_content
                first = await client.session.call_tool("issue_refund", {"quote_id": quote["quote_id"]},
                                                        allow_input_required=True)
                print("first round:", first.result_type)
                print("first round asks:", ", ".join(r.method for r in first.input_requests.values()))
                refund = await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
                print("refund after the lead's yes:", refund.structured_content["status"])


asyncio.run(main())
