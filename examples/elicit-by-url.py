"""pay_refund sends the support lead to the payment provider's page to connect their account. URL mode keeps the
sign-in out of the client, and accept means only that the user agreed to open the page."""
import asyncio
import secrets

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ElicitRequest, ElicitRequestURLParams, ElicitResult, InputRequiredResult

from lib import confirmations

server = MCPServer("shop-payments", version="0.5.0")
finished: set[str] = set()     # flows the payment provider reports finished; it would tell the server, not the client


@server.tool(description="Pay out a released refund through the shop's payment provider, by its refund_id.")
def pay_refund(refund_id: str, ctx: Context) -> str | InputRequiredResult:
    flow = ctx.request_state or secrets.token_urlsafe(16)    # the server's own ID for this flow, carried in requestState
    if flow in finished:
        return f"Paid {refund_id} through the payment provider"
    answer = (ctx.input_responses or {}).get("connect")
    if answer is not None and answer.action != "accept":
        return f"Not paid: the user didn't connect a payment account. {refund_id} stays released, unpaid."
    confirmations.require_elicitation(ctx, "url")
    ask = ElicitRequestURLParams(url=f"https://pay.fernhill.example/connect/{flow}",
                                 message="To pay refunds, connect your payment provider account on its own page.")
    return InputRequiredResult(input_requests={"connect": ElicitRequest(params=ask)}, request_state=flow)


async def main() -> None:
    async with Client(server, elicitation_callback=confirmations.say_yes) as client:   # declares form and url
        def call(state=None, answers=None):
            return client.session.call_tool("pay_refund", {"refund_id": "R-0111"}, input_responses=answers,
                                            request_state=state, allow_input_required=True)
        first = await call()
        request = first.input_requests["connect"].params
        print("first call:", first.result_type, request.mode)
        print("url:", request.url.rsplit("/", 1)[0] + "/…")
        accepted = {"connect": ElicitResult(action="accept")}     # the scripted user agrees to open the page
        second = await call(first.request_state, accepted)
        print("after accept:", second.result_type, second.input_requests["connect"].params.mode)
        finished.add(request.url.rsplit("/", 1)[1])               # the lead signs in on the provider's page
        third = await call(second.request_state, accepted)
        print("after sign-in:", third.result_type, third.content[0].text)

asyncio.run(main())
