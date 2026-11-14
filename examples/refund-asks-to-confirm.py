"""issue_refund answers a held refund with an input request instead of a result, which asks a person to confirm it.
The prose's points rest on the result type line, the one input request under confirm with its message, and the
assert, which fails the run if the SDK doesn't seal the request state."""
import asyncio
import sys

from mcp import Client
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from lib import confirmations, loopback, shop_api, shop_tools

server, held = confirmations.shop_server()     # chapter 3's other tools; held is chapter 3's issue_refund
answered = confirmations.OnceOnly()            # the round-trip states already answered, so a replayed answer fails


@server.tool(title="Issue a refund", description=shop_tools.DESCRIPTIONS["issue_refund"], annotations=held.annotations)
def issue_refund(quote_id: confirmations.QuoteId, ctx: Context) -> shop_tools.Refund | InputRequiredResult:
    refund = held.fn(quote_id)                 # the same quote_id always gives the same refund
    if refund.status != "needs_confirmation":
        return refund
    answer = (ctx.input_responses or {}).get("confirm")   # the answer comes back under the key the tool asked with
    if answer is None or ctx.request_state != refund.refund_id:   # first round, or a question never asked
        confirmations.require_elicitation(ctx, "form")     # ask only what the client declared it can show
        ask = ElicitRequestFormParams(requested_schema=confirmations.RELEASE_FORM, message=f"Refund {refund.amount} on "
                                      f"order {refund.order_id}? It is above the policy limit, so a lead must confirm it.")
        return InputRequiredResult(input_requests={"confirm": ElicitRequest(params=ask)},
                                   request_state=refund.refund_id)   # the refund's ID rides in the state the SDK seals
    if answer.action != "accept" or not (answer.content or {}).get("release"):
        raise ToolError(f"Nobody confirmed refund {refund.refund_id}, so the shop's API still holds it.")
    if not answered.claim(ctx.request_state):              # sealing can't stop a replay; this record does
        raise ToolError(f"Refund {refund.refund_id} was already confirmed. Don't send the same answer again.")
    return confirmations.release(refund)


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(confirmations.launch(__file__, base_url),   # starts this file with --serve over stdio
                          elicitation_callback=confirmations.say_yes) as client:      # declares elicitation
            quote = (await client.call_tool("quote_refund", {"order_id": "O-2289"})).structured_content
            result = await client.session.call_tool("issue_refund", {"quote_id": quote["quote_id"]},
                                                     allow_input_required=True)   # return the input request, not an answer to it
            print("result type:", result.result_type)
            for key, request in result.input_requests.items():
                print(f"input request {key}:", request.method, request.params.mode)
                print("message:", request.params.message)
            # the SDK's sealed-token prefix: a request state that starts with it was sealed on its way out
            assert result.request_state.startswith("v1.")


server.run() if "--serve" in sys.argv else asyncio.run(main())   # the client runs this file with --serve; run directly, it starts the client
