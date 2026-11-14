"""Two tool lists for the same API, one tool per endpoint as a generator writes them and the shop's five task tools, then
ticket T-0024's refund both ways. The point rests on two printed lines: the endpoint tool records the amount the model
sent, and quote_refund's amount is the server's own figure, which the code asserts is within the limit."""
import asyncio

import httpx2
from mcp import Client

from lib import loopback, shop_api, shop_tools


async def main() -> None:
    for tool in shop_tools.endpoint_tools():
        print("endpoint tool:", tool.name, tool.input_schema["required"])
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(shop_tools.server_params(base_url)) as client:
            print("protocol revision:", client.protocol_version)
            for tool in (await client.list_tools()).tools:
                print("task tool:", tool.name, tool.input_schema.get("required", []))  # .get: no "required" key if none

            # T-0024: "please refund the aluminium muffin tray on o2415". The endpoint tool post_refunds forwards
            # its arguments to POST /refunds, so the amount is whatever the model sends, such as the order's total.
            order = httpx2.get(f"{base_url}/orders/O-2415", headers={"X-API-Key": shop_api.DEMO_API_KEY}).json()
            refund = httpx2.post(f"{base_url}/refunds", headers={"X-API-Key": shop_api.DEMO_API_KEY},
                                 json={"order_id": "O-2415", "amount": order["total"], "reason": "damaged"})
            print("post_refunds status:", refund.status_code)
            print("post_refunds amount:", refund.json()["amount"])

            quote = await client.call_tool("quote_refund", {"order_id": "O-2415", "sku": "KG-1050",
                                                            "reason": "arrived damaged"})
            print("quote_refund amount:", quote.structured_content["amount"])
            print("quote_refund within limit:", quote.structured_content["within_limit"])
            assert quote.structured_content["within_limit"]  # the muffin tray's line is under the refund policy's limit


asyncio.run(main())
