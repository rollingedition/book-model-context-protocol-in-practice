"""Record every message the client and the shop's server exchange for one tool call, and print them in order. The point
 rests on the methods line: the exchange has no initialize."""
import asyncio
import pathlib
import sys

from mcp import Client, StdioServerParameters
from mcp.types import Implementation

from lib import loopback, shop_api, wire


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as base_url:
        server = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"],
                                       env=shop_api.server_env(base_url))
        pathlib.Path("wire.jsonl").unlink(missing_ok=True)   # the relay appends, so start each run empty
        # the relay starts the server and copies every line both ways, appending each one to the log
        params = wire.relay(server, log="wire.jsonl")
        async with Client(params, client_info=Implementation(name="shop-host", version="0.1.0")) as client:
            await client.list_tools()
            await client.call_tool("get_order_status", {"order_id": "O-2476"})
    # messages 1, 5 and 6 print in full; the rest on one line, with strings cut at 48 characters
    messages = wire.print_trace("wire.jsonl", full=(1, 5, 6), depth=4, max_string=48)
    print("messages:", len(messages))
    print("methods:", ", ".join(m["method"] for m in messages if "method" in m))  # results carry no method


asyncio.run(main())
