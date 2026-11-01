"""find_orders' typed inputs: the JSON Schema the SDK builds from them, three arguments it rejects in one result the
model can read, a string it quietly converts, and a date it can't know is wrong."""
import asyncio
import json

from mcp import Client

from lib import loopback, shop_api, shop_tools


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(shop_tools.server_params(base_url)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name, prop in tools["find_orders"].input_schema["properties"].items():
                rules = {k: v for k, v in prop.items() if k in ("pattern", "minimum", "maximum", "default")}
                kinds = [p.get("enum") or p.get("format") or p["type"] for p in prop.get("anyOf", [prop])]
                print(f"{name}:", json.dumps(kinds), json.dumps(rules))

            bad = await client.call_tool("find_orders", {"customer_id": "42", "status": "lost", "limit": 500})
            print("bad arguments is error:", bad.is_error)
            print(bad.content[0].text)

            loose = await client.call_tool("find_orders", {"customer_id": "C-0085", "limit": "5"})
            print("string limit is error:", loose.is_error)
            print("string limit orders:", len(loose.structured_content["orders"]))

            # T-0013 asks for orders "since 12 Jun"; the recorded model sent 2023-06-12, a valid date
            wrong_year = await client.call_tool("find_orders", {"customer_id": "C-0085", "placed_since": "2023-06-12"})
            right_year = await client.call_tool("find_orders", {"customer_id": "C-0085", "placed_since": "2026-06-12"})
            print("since 2023-06-12 orders:", len(wrong_year.structured_content["orders"]))
            print("since 2026-06-12 orders:", len(right_year.structured_content["orders"]))


asyncio.run(main())
