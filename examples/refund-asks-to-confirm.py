"""issue_refund asks a person to confirm a refund the shop's API holds, by returning an input request, not a result."""
import asyncio
import sys

from mcp import Client
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from lib import confirmations, loopback, shop_api, shop_tools

server, held = confirmations.shop_server()     # chapter 3's other tools; held is chapter 3's issue_refund
answered = confirmations.OnceOnly()            # the round-trip states already answered


@server.tool(title="Issue a refund", description=shop_tools.DESCRIPTIONS["issue_refund"], annotations=held.annotations)
def issue_refund(quote_id: confirmations.QuoteId, ctx: Context) -> shop_tools.Refund | InputRequiredResult:
    refund = held.fn(quote_id)                 # the same quote_id always gives the same refund
    if refund.status != "needs_confirmation":
        return refund
    answer = (ctx.input_responses or {}).get("confirm")
    if answer is None or ctx.request_state != refund.refund_id:   # first round, or a question never asked
        confirmations.require_elicitation(ctx, "form")     # ask only what the client declared it can show
        ask = ElicitRequestFormParams(requested_schema=confirmations.RELEASE_FORM, message=f"Refund {refund.amount} on "
                                      f"order {refund.order_id}? It is above the policy limit, so a lead must confirm it.")
        return InputRequiredResult(input_requests={"confirm": ElicitRequest(params=ask)},
                                   request_state=refund.refund_id)
    if answer.action != "accept" or not (answer.content or {}).get("release"):
        raise ToolError(f"Nobody confirmed refund {refund.refund_id}, so the shop's API still holds it.")
    if not answered.claim(ctx.request_state):              # sealing can't stop a replay; this record does
        raise ToolError(f"Refund {refund.refund_id} was already confirmed. Don't send the same answer again.")
    return confirmations.release(refund)


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(confirmations.launch(__file__, base_url),
                          elicitation_callback=confirmations.say_yes) as client:      # declares elicitation
            quote = (await client.call_tool("quote_refund", {"order_id": "O-2289"})).structured_content
            result = await client.session.call_tool("issue_refund", {"quote_id": quote["quote_id"]},
                                                     allow_input_required=True)
            print("result type:", result.result_type)
            for key, request in result.input_requests.items():
                print(f"input request {key}:", request.method, request.params.mode)
                print("message:", request.params.message)
            print("request state sealed:", result.request_state.startswith("v1."))


server.run() if "--serve" in sys.argv else asyncio.run(main())
