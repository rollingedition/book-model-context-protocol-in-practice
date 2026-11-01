"""What each tool's annotations tell a host, with the specification's defaults filled in where a hint is missing, and
whether the server keeps issue_refund's idempotent promise when the same call arrives twice."""
import asyncio

import httpx2
from mcp import Client

from lib import loopback, shop_api, shop_tools

DEFAULTS = {"read_only_hint": False, "destructive_hint": True, "idempotent_hint": False, "open_world_hint": True}


def assumed(annotations) -> dict:
    """The hints a host should assume: each one the tool sets, and the specification's default for the rest."""
    given = annotations.model_dump(exclude_none=True) if annotations else {}
    hints = {hint: given.get(hint, default) for hint, default in DEFAULTS.items()}
    if hints["read_only_hint"]:          # destructive and idempotent apply only to a tool that changes something
        del hints["destructive_hint"], hints["idempotent_hint"]
    return hints


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        async with Client(shop_tools.server_params(base_url)) as client:
            tools = (await client.list_tools()).tools + shop_tools.endpoint_tools()[3:4]    # + post_refunds
            for tool in tools:
                hints = assumed(tool.annotations)
                shown = ", ".join(h.removesuffix("_hint") for h, on in hints.items() if on) or "nothing"
                print(f"{tool.name} assumes:", shown)
                print(f"{tool.name} asks consent:", not hints["read_only_hint"])

            quote = (await client.call_tool("quote_refund", {"order_id": "O-2415", "sku": "KG-1050"})).structured_content
            first = await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
            again = await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
            print("issue_refund first refund:", first.structured_content["refund_id"])
            print("issue_refund second refund:", again.structured_content["refund_id"])

        twice = [httpx2.post(f"{base_url}/refunds", headers={"X-API-Key": shop_api.DEMO_API_KEY},
                             json={"order_id": "O-2415", "amount": "23.98"}).json()["refund_id"] for _ in range(2)]
        print("post_refunds first refund:", twice[0])
        print("post_refunds second refund:", twice[1])


asyncio.run(main())
