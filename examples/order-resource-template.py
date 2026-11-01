"""Address any order as shop://orders/{order_id}: a resource template over the shop's API, and what a miss returns."""
import asyncio
import json
import re
import sys

from mcp import Client, MCPError, StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

from lib import loopback, shop_api, shop_reads

server = MCPServer("shop-support", version="0.4.0")   # default cache hint: ttl 0, scope private


@server.resource("shop://orders/{order_id}", title="One of the shop's orders", mime_type="application/json")
async def order(order_id: str) -> dict:
    """One order: its status, dates, lines and total, as the shop's API returns it."""
    if not re.fullmatch(r"O-\d{4}", order_id):                      # check the format before the API sees it
        raise ResourceNotFoundError(f"Order IDs look like O-1873, not {order_id!r}.")
    if (found := await shop_reads.get_json(f"/orders/{order_id}")) is None:    # the API answered 404
        raise ResourceNotFoundError(f"The shop has no order {order_id}.")
    return found


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        params = StdioServerParameters(command=sys.executable, args=[__file__, "--serve"],
                                       env=shop_api.server_env(base_url))
        async with Client(params) as client:
            template = (await client.list_resource_templates()).resource_templates[0]
            print("template:", template.uri_template)
            read = await client.read_resource("shop://orders/O-2476")
            print("O-2476 status:", json.loads(read.contents[0].text)["status"])
            print("read cache scope:", read.cache_scope)
            for case, uri in (("unknown order", "shop://orders/O-7144"),
                              ("malformed", "shop://orders/2476"),
                              ("traversal", "shop://orders/..%2F..%2Frefunds")):
                try:
                    await client.read_resource(uri)
                except MCPError as err:
                    print(f"{case} code:", err.error.code)
                    print(f"{case} says:", err.error.message)
                    print(f"{case} data uri:", err.error.data["uri"])


if __name__ == "__main__":
    server.run() if "--serve" in sys.argv else asyncio.run(main())
