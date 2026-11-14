"""Consent: the host runs the shop's reads from its own list, and asks, with the exact arguments, before a refund above
the limit (which the shop's server then asks about too) and before any partner call, whatever the partner's annotations
say. The `decisions logged` line records each choice, and the partner's call is the one that is not made."""
import asyncio
import json
import os
import re

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import ElicitResult

from lib import auth_server, host_guard, loopback, owned_shop, partner, shop_api
from lib.shop_data import load_shop

TICKET = load_shop().ticket("T-0028")                           # from C-0127, about order O-2476


def user(request: host_guard.Request) -> bool:
    shown = re.sub(r"Q-[0-9a-f]{10}", "Q-...", json.dumps(request.arguments))[:60]   # the first 60 characters
    print(f"  host asks: {request.server}/{request.tool} {shown}...")
    # the scripted user: yes to the refund, no to the partner
    return {"issue_refund": True, "track_parcel": False}[request.tool]


async def lead(context, params) -> ElicitResult:                 # the server's own question, to the same user
    print("  server asks:", params.message.split("?")[0] + "?")        # the question, without what follows it
    return ElicitResult(action="accept", content={"release": True})


async def main(url: str, token: str) -> None:
    gate = host_guard.ConsentGate(host_guard.NO_SIDE_EFFECTS, ask=user)
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"})
    async with Client(streamable_http_client(url, http_client=http), elicitation_callback=lead) as shop, \
            Client(partner.create_server()) as other:
        # the partner's claim about its own tool, which the gate never reads
        assert (await other.list_tools()).tools[0].annotations.read_only_hint is True
        quote_id = (await shop.call_tool("quote_refund", {"order_id": "O-1928"})).structured_content["quote_id"]
        for client, server, tool, arguments in [
                (shop, "shop", "get_order_status", {"order_id": "O-2476"}),
                (shop, "shop", "issue_refund", {"quote_id": quote_id}),
                # a placeholder tracking number; the note carries the whole ticket, as a poisoned description asks
                (other, "partner", "track_parcel", {"tracking_number": "FX-00000000", "note": TICKET.body})]:
            ran = gate.allows(server, tool, arguments) and await client.call_tool(tool, arguments)
            print(f"{server}/{tool}:", "ran" if ran else "not called")
            ran and print(f"{server}/{tool} status:", ran.structured_content["status"])
    print("decisions logged:", "; ".join(f"{r.tool} {decision}" for r, decision in gate.log))


with auth_server.serve() as issuer, loopback.serve(shop_api.create_app()) as api_url:
    os.environ.update(shop_api.server_env(api_url))
    with owned_shop.serve(issuer.url) as url:
        asyncio.run(main(url, auth_server.mint(issuer.url, url, ["orders:read", "stock:read", "refunds:write"],
                                               subject="C-0127")))
