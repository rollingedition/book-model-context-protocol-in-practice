"""Serve chapter 3's five tools over Streamable HTTP on loopback, and call one from a client that has only a URL."""
import asyncio
import sys
from urllib.parse import urlsplit

from mcp import Client

from lib import http_mcp, loopback, shop_api, shop_tools

server = shop_tools.create_server(version="0.6.0")      # chapter 3's tools, unchanged


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        with http_mcp.launch(__file__, env=shop_api.server_env(api_url)) as url:
            async with Client(url) as client:
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
