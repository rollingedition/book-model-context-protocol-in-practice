"""shop-support, the chapter 2 server, offers one tool, one resource and one prompt. Run bare, the file starts it as a
client, which prints what it discovers: the tools, resources and prompts lines are the ones the prose reads."""
import asyncio
import os
import sys

import httpx2
from mcp import Client, StdioServerParameters
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lib.policies import policy

# ttl_ms is in milliseconds, so 300_000 is five minutes; "public" lets a shared cache reuse the tool list.
server = MCPServer("shop-support", version="0.2.0",
                   cache_hints={"tools/list": CacheHint(ttl_ms=300_000, scope="public")})


@server.tool()
def get_order_status(order_id: str) -> dict:
    """Look up one of the shop's orders by its ID, such as O-1873: its status, dates, lines and total."""
    response = httpx2.get(f"{os.environ['SHOP_API_URL']}/orders/{order_id}",
                          headers={"X-API-Key": os.environ["SHOP_API_KEY"]}, timeout=5.0)   # timeout in seconds
    if response.status_code == 404:
        raise ToolError(f"The shop has no order {order_id}. Order IDs look like O-1873.")
    response.raise_for_status()
    return response.json()


@server.resource("shop://policies/refund", name="refund-policy", mime_type="text/markdown")
def refund_policy() -> str:
    return policy("refund").path.read_text(encoding="utf-8")       # examples/data/shop/policies/refund.md


@server.prompt()
def review_refund(order_id: str) -> str:
    """Review a customer's refund request for one order against the shop's refund policy."""
    return (f"Review the refund request for order {order_id}. Look up the order with get_order_status, read the "
            "refund policy at shop://policies/refund, and say whether the refund needs a person to confirm it.")


async def main() -> None:
    # No variables are passed: listing never calls the tool, so the server needs none of the shop's API settings.
    async with Client(StdioServerParameters(command=sys.executable, args=[__file__, "--serve"], env={})) as client:
        print("server:", client.server_info.name, client.server_info.version)
        print("protocol revision:", client.protocol_version)
        # auto mode keeps the server/discover answer on the session, so the versions come from there
        print("supported versions:", ", ".join(client.session.discover_result.supported_versions))
        # exclude_none drops the capabilities the server didn't declare, leaving only the ones it offers
        print("capabilities:", ", ".join(sorted(client.server_capabilities.model_dump(exclude_none=True))))
        print("tools:", ", ".join(t.name for t in (await client.list_tools()).tools))
        print("resources:", ", ".join(str(r.uri) for r in (await client.list_resources()).resources))
        print("prompts:", ", ".join(p.name for p in (await client.list_prompts()).prompts))


if __name__ == "__main__":
    # With --serve this file is the server the client launches; run bare, it is the client.
    server.run() if "--serve" in sys.argv else asyncio.run(main())
