"""Use each of shop-support's three primitives once: call the tool, read the resource, get the prompt."""
import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

from lib import loopback, shop_api


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        params = StdioServerParameters(command=sys.executable, args=["list-what-the-server-offers.py", "--serve"],
                                       env=shop_api.server_env(base_url))
        async with Client(params) as client:
            # A tool: the host lists it for the model, and calls it when the model asks.
            result = await client.call_tool("get_order_status", {"order_id": "O-2476"})
            print("tool call is error:", result.is_error)
            print("tool says order status:", json.loads(result.content[0].text)["status"])

            # A resource: the host reads it when its own code decides the model needs it.
            policy = (await client.read_resource("shop://policies/refund")).contents[0]
            print("resource type:", policy.mime_type)
            print("resource first line:", policy.text.splitlines()[0])

            # A prompt: the host shows it to the user, who picks it and fills in its arguments.
            listed = (await client.list_prompts()).prompts[0]
            print("prompt arguments:", "; ".join(f"{a.name}, {'required' if a.required else 'optional'}"
                                                 for a in listed.arguments))
            prompt = await client.get_prompt("review_refund", {"order_id": "O-2476"})
            print("prompt messages:", len(prompt.messages))
            print("prompt role:", prompt.messages[0].role)
            print("prompt starts:", prompt.messages[0].content.text[:44] + "…")


asyncio.run(main())
