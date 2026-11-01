"""Finish the refund from refund-asks-to-confirm: retry the same call with the answer and the echoed requestState,
first by hand, so both requests show on the wire, then with Client.call_tool, which runs the loop itself."""
import asyncio
import pathlib

from mcp import Client
from mcp.types import ElicitResult

from lib import confirmations, loopback, shop_api, wire

LOG = pathlib.Path("refund-confirmed-round-trip.jsonl")             # every line the relay copies
YES = ElicitResult(action="accept", content={"release": True})    # the scripted user's answer


async def say_yes(context, params) -> ElicitResult:
    print("user was asked:", params.message)
    return YES


async def main() -> None:
    LOG.unlink(missing_ok=True)
    with loopback.serve(shop_api.create_app()) as base_url:
        server = wire.relay(confirmations.launch("refund-asks-to-confirm.py", base_url), log=str(LOG))
        async with Client(server, elicitation_callback=say_yes) as client:
            quote = (await client.call_tool("quote_refund", {"order_id": "O-2289"})).structured_content
            arguments = {"quote_id": quote["quote_id"]}
            first = await client.session.call_tool("issue_refund", arguments, allow_input_required=True)
            done = await client.session.call_tool("issue_refund", arguments, input_responses={"confirm": YES},
                                                  request_state=first.request_state, allow_input_required=True)
            print("by hand:", done.structured_content["refund_id"], done.structured_content["status"])
            quote = (await client.call_tool("quote_refund", {"order_id": "O-1145"})).structured_content
            done = await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
            print("by Client.call_tool:", done.structured_content["refund_id"], done.structured_content["status"])
    calls, results = [], {}                     # the issue_refund requests, in order, and each one's resultType
    for direction, message in wire.read_trace(str(LOG)):
        if message.get("method") == "tools/call" and message["params"]["name"] == "issue_refund":
            calls.append(message)
        elif direction == "in" and "result" in message:
            results[message["id"]] = message["result"]["resultType"]
    for label, message in zip(["by hand, call", "by hand, retry", "Client.call_tool, call", "Client.call_tool, retry"],
                              calls):
        sent = " and ".join(key for key in ("inputResponses", "requestState") if key in message["params"])
        print(f"{label}: id {message['id']}, sends {sent or 'arguments only'}, gets {results[message['id']]}")
    LOG.unlink()

asyncio.run(main())
