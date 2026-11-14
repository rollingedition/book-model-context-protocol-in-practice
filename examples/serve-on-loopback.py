"""Serves chapter 3's five tools over Streamable HTTP in a process of its own, then calls one from a client that has only
the endpoint's URL. The point rests on the protocol revision and O-1873 status lines: the client settles on the pinned
revision and gets the order's status back."""
import asyncio
import sys
from urllib.parse import urlsplit

from mcp import Client

from lib import http_mcp, loopback, shop_api, shop_tools

server = shop_tools.create_server(version="0.6.0")      # chapter 3's tools, unchanged


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        with http_mcp.launch(__file__, env=shop_api.server_env(api_url)) as url:   # runs this file again with --serve, as its own process
            async with Client(url) as client:                                # no handshake: the client needs only the URL
                print("endpoint host:", urlsplit(url).hostname)
                print("endpoint path:", urlsplit(url).path)
                print("protocol revision:", client.protocol_version)
                print("server:", client.server_info.name, client.server_info.version)
                print("tools:", len((await client.list_tools()).tools))
                result = await client.call_tool("get_order_status", {"order_id": "O-1873"})
                print("O-1873 status:", result.structured_content["status"])


if "--serve" in sys.argv:
    server.run(transport="streamable-http", port=http_mcp.port())   # 127.0.0.1, path /mcp
else:
    asyncio.run(main())
