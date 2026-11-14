"""Fetch order O-2476 from the shop's API, then through shop-support's tool over Streamable HTTP, and count the cost.
The prose's comparison comes from the byte totals and the request counts the script prints."""
import asyncio
import os
import runpy

import httpx2
from mcp import Client

from lib import byte_meter, loopback, shop_api


async def session(url, traffic, requests, mode: str, calls: int) -> tuple[list[str], int]:
    """Open a client, list the tools as a host does, make `calls` tool calls, close it: the requests and bytes."""
    traffic.reset()
    requests.reset()
    # auto mode first sends server/discover to probe the server; a pinned revision skips that probe
    async with Client(f"{url}/mcp", mode=mode) as client:
        await client.list_tools()
        for _ in range(calls):
            await client.call_tool("get_order_status", {"order_id": "O-2476"})
    return list(requests.names), traffic.sent + traffic.received     # bytes both ways, from the relay


async def main() -> None:
    print("setup: one process, 127.0.0.1, HTTP/1.1, no TLS, bytes counted at a TCP relay, headers included")
    api_app, api_requests = byte_meter.count_requests(shop_api.create_app())
    with loopback.serve(api_app) as api_url, byte_meter.relay(api_url) as (url, traffic):
        # the one API call, sent through the relay so that its bytes are counted the way the tool's are
        httpx2.get(f"{url}/orders/O-2476", headers={"X-API-Key": shop_api.DEMO_API_KEY}).raise_for_status()
        api_bytes = traffic.sent + traffic.received
        print("api call round trips:", api_requests.count)
        print("api call bytes:", api_bytes)

        os.environ.update(shop_api.server_env(api_url))      # the tool calls the API directly, not through a relay
        shop_support = runpy.run_path("list-what-the-server-offers.py")["server"]    # defined there, not run
        mcp_app, mcp_requests = byte_meter.count_requests(shop_support.streamable_http_app())
        with loopback.serve(mcp_app) as mcp_url, byte_meter.relay(mcp_url) as (url, traffic):
            for mode, label in (("auto", "auto"), ("2026-07-28", "pinned")):
                names, setup_bytes = await session(url, traffic, mcp_requests, mode, calls=0)   # setup only, no tool call
                print(f"mcp {label} setup request count:", len(names))
                print(f"mcp {label} setup requests:", ", ".join(names))
                print(f"mcp {label} setup bytes:", setup_bytes)
            names, with_call = await session(url, traffic, mcp_requests, "2026-07-28", calls=1)
            call_bytes = with_call - setup_bytes          # a pinned session with one call, less the pinned setup
            print("mcp tool call round trips:", names.count("tools/call"))
            print("mcp tool call bytes:", call_bytes)
            print("tool call bytes per api call byte:", round(call_bytes / api_bytes, 1))  # one decimal place, as the prose quotes


asyncio.run(main())
