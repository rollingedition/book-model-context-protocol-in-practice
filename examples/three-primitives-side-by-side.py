"""Use each of shop-support's three primitives once, as a host would: the tool for the model, the resource for the
host's code, the prompt for the person at the desk. The prose quotes the order's status, the policy's first line and
the prompt's one required argument."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

from lib import loopback, shop_api


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        # the server from list-what-the-server-offers, run as its own process with --serve; its env points at the shop's API
        params = StdioServerParameters(command=sys.executable, args=["list-what-the-server-offers.py", "--serve"],
                                       env=shop_api.server_env(base_url))
        async with Client(params) as client:
            # A tool: the host lists it for the model, and calls it when the model asks.
            result = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            assert result.is_error is False      # the lookup must succeed for the prose's claim
            # a tool's result is a list of content blocks; the order arrives as JSON text in the first one
            print("tool says order status:", json.loads(result.content[0].text)["status"])

            # A resource: the host reads it when its own code decides the model needs it.
            policy = (await client.read_resource("shop://policies/refund")).contents[0]   # this server returns one item
            print("resource type:", policy.mime_type)
            print("resource first line:", policy.text.splitlines()[0])

            # A prompt: the host shows it to the user, who picks it and fills in its arguments.
            listed = (await client.list_prompts()).prompts[0]     # the first prompt, the only one shop-support offers
            print("prompt arguments:", "; ".join(f"{a.name}, {'required' if a.required else 'optional'}"
                                                 for a in listed.arguments))
            prompt = await client.get_prompt("review_refund", {"order_id": "O-2476"})
            print("prompt messages:", len(prompt.messages))
            print("prompt role:", prompt.messages[0].role)
            print("prompt starts:", prompt.messages[0].content.text[:44] + "…")   # 44 characters: enough to name the order


asyncio.run(main())
