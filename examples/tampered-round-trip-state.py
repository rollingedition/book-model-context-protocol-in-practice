"""Send issue_refund's retry wrongly, then rightly, then again: a changed requestState, an answer with no state, and a
state with other arguments; then an honest retry, and its replay. The seal refuses the changed and the mismatched state,
the tool asks again for the answer with no state, and its own once-only record refuses the replay."""
import asyncio

from mcp import Client, MCPError
from mcp.types import ElicitResult

from lib import confirmations, loopback, shop_api

YES = ElicitResult(action="accept", content={"release": True})     # the scripted user's answer


async def retry(client: Client, label: str, quote_id: str, state: str | None) -> None:
    try:
        result = await client.session.call_tool("issue_refund", {"quote_id": quote_id}, input_responses={"confirm": YES},
                                                request_state=state, allow_input_required=True)
    except MCPError as error:
        print(f"{label}:", error.error.code, error.error.message)
        return
    if result.result_type == "input_required":
        print(f"{label}: input_required, the server asks again")
    elif result.is_error:
        print(f"{label}: tool error,", result.content[0].text)
    else:
        print(f"{label}: refund", result.structured_content["refund_id"], result.structured_content["status"])

async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(confirmations.launch("refund-asks-to-confirm.py", base_url),
                          elicitation_callback=confirmations.say_yes) as client:
            quotes = [(await client.call_tool("quote_refund", {"order_id": order})).structured_content["quote_id"]
                      for order in ("O-2289", "O-1145")]
            first = await client.session.call_tool("issue_refund", {"quote_id": quotes[0]}, allow_input_required=True)
            state = first.request_state
            # swaps the character at index 20 for another, so the seal no longer matches the token
            changed = state[:20] + ("A" if state[20] != "A" else "B") + state[21:]
            await retry(client, "one character changed", quotes[0], changed)
            await retry(client, "answer without state", quotes[0], None)
            await retry(client, "state with other arguments", quotes[1], state)
            await retry(client, "honest retry", quotes[0], state)
            await retry(client, "same retry again", quotes[0], state)


asyncio.run(main())
