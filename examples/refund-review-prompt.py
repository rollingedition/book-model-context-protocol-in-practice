"""Packages a refund review as a prompt, with the refund policy embedded, the order quoted and the arguments checked first.
The point rests on the two messages, and on the three failures: a bad path gets Invalid Params, while a missing amount and a misspelled name both get an internal error."""
import asyncio
import json
import re
import sys

from mcp import Client, MCPError, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import INVALID_PARAMS, EmbeddedResource, TextResourceContents

from lib import loopback, shop_api, shop_reads
from lib.policies import policy

server = MCPServer("shop-support", version="0.4.0")


@server.prompt(title="Review a refund request")
async def review_refund(order_id: str, amount: str) -> list[EmbeddedResource | str]:
    """Check a customer's refund request against the refund policy before a person issues it."""
    # up to five whole digits and exactly two decimals, so 24.99 and 343.49 pass
    if not re.fullmatch(r"\d{1,5}\.\d{2}", amount):
        raise MCPError(INVALID_PARAMS, f"Amounts look like 24.99, not {amount!r}.")
    # the API is asked only for an ID in the right format, and None from it means no such order
    if not re.fullmatch(r"O-\d{4}", order_id) or (order := await shop_reads.get_json(f"/orders/{order_id}")) is None:
        raise MCPError(INVALID_PARAMS, f"No order {order_id!r}. Order IDs look like O-1873.")
    return [EmbeddedResource(type="resource", resource=TextResourceContents(       # each item: one user message
                uri="shop://policies/refund", mime_type="text/markdown", text=policy("refund").text)),
            (f"Order {order_id}: {json.dumps(order)}\n\nThe customer asks for a refund of {amount}. "
             "From the policy and the order only: does it qualify, how much may the shop refund, "
             "and must a support lead confirm it?")]


async def main() -> None:
    good = {"order_id": "O-1145", "amount": "343.49"}  # the order, and the amount its customer asks for
    tries = {"path as order_id": ("review_refund", {**good, "order_id": "../refunds"}),  # a path where an ID belongs
             "missing amount": ("review_refund", {"order_id": "O-1145"}),
             "unknown prompt": ("refund_review", good)}  # misspelled: the prompt is review_refund
    with loopback.serve(shop_api.create_app()) as base_url:
        env = shop_api.server_env(base_url)
        async with Client(StdioServerParameters(command=sys.executable, args=[__file__, "--serve"], env=env)) as client:
            for n, message in enumerate((await client.get_prompt("review_refund", good)).messages, 1):
                print(f"message {n}:", message.role, message.content.type)
            for case, (name, arguments) in tries.items():
                try:
                    await client.get_prompt(name, arguments)
                except MCPError as err:
                    print(f"{case}:", err.error.code, err.error.message)


if __name__ == "__main__":
    server.run() if "--serve" in sys.argv else asyncio.run(main())
