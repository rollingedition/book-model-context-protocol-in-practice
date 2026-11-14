"""Two refunds above the policy limit, each held by an input request from the shop's server. The host shows the lead
which server asks and what, and Client.call_tool retries with the answer; the lead accepts the first and declines the second."""
import asyncio
import json

from mcp.types import ElicitResult

from lib import loopback, shop_api, ticket_host
from lib.shop_data import REFUND_LIMIT_CENTS, money

answers = [ElicitResult(action="accept", content={"release": True}), ElicitResult(action="decline")]   # the scripted lead's answers, in order
fields: list[str] = []                      # the form fields the lead was shown


def lead(server: str, params) -> ElicitResult:
    fields.extend(params.requested_schema["properties"])      # the field names, from the request's schema
    return answers.pop(0)                   # index 0: the next unused answer, so each request gets one answer in turn


async def main() -> None:
    print("refund policy limit:", money(REFUND_LIMIT_CENTS))
    with loopback.serve(shop_api.create_app()) as base_url:
        async with ticket_host.queue_host(base_url, lead=lead) as host:
            for order_id in ("O-1145", "O-2289"):
                outcome, quote = await host.call("shop.quote_refund", {"order_id": order_id})
                quote_id = json.loads(quote)["quote_id"]
                print(f"{order_id} quote id:", quote_id)
                outcome, text = await host.call("shop.issue_refund", {"quote_id": quote_id})
                server, message, action = host.asked[-1]          # index -1: the request this call just answered
                print(f"{order_id} asked by:", server)
                print(f"{order_id} message:", message)
                print(f"{order_id} lead's answer:", action)
                print(f"{order_id} outcome:", outcome)
                print(f"{order_id} back to the model:", text)
            print("form fields:", ", ".join(sorted(set(fields))))
            print("input requests answered:", len(host.asked))
            # the rounds one call may take before the client raises, which is the client's default here
            print("retry rounds allowed per call:", host.clients["shop"].input_required_max_rounds)
            # only the calls the gate asked the user about, not those its list let through without asking
            print("consent asked for:", [request.tool for request, decision in host.gate.log
                                         if decision != "allowed by the host's list"])


asyncio.run(main())
