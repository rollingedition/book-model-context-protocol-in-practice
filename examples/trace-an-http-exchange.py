"""Records the HTTP exchanges behind one tool call, then sends two requests the SDK's client never would. The point rests
on the request headers and response status lines of the tool call, and on the mismatched and GET lines, which show what
the server refuses."""
import asyncio
import os

import httpx2
from mcp import Client

from lib import http_mcp, loopback, shop_api, wire

SHOWN = ("content-type", "accept", "mcp-protocol-version", "mcp-method", "mcp-name")


async def main() -> None:
    server = http_mcp.load_server("serve-on-loopback.py")        # chapter 3's five tools
    app = wire.record_http(server.streamable_http_app(), log="http.jsonl")   # logs each exchange as the app saw it
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(app) as base_url:
        os.environ.update(shop_api.server_env(api_url))           # the server runs in this process, so it reads the API address here
        async with Client(base_url + "/mcp") as client:
            await client.call_tool("get_order_status", {"order_id": "O-1873"})
        exchanges = wire.read_http_trace("http.jsonl")
        # the recorder keeps header names in lower case
        print("POSTs:", ", ".join(e["request_headers"]["mcp-method"] for e in exchanges))
        call = next(e for e in exchanges if e["request_headers"]["mcp-method"] == "tools/call")
        for name in SHOWN:
            print(f"request {name}:", call["request_headers"][name])
        print("request _meta keys:", ", ".join(call["request"]["params"]["_meta"]))
        print("response status:", call["status"])
        print("response content-type:", call["response_headers"]["content-type"])
        print("response mcp-session-id:", call["response_headers"].get("mcp-session-id", "none"))

        # the body names get_order_status, so this Mcp-Name header disagrees with it
        wrong = http_mcp.post(base_url + "/mcp", "tools/call", {"name": "get_order_status",
                              "arguments": {"order_id": "O-1873"}}, headers={"Mcp-Name": "check_stock"})
        print("mismatched Mcp-Name status:", wrong.status_code)
        print("mismatched Mcp-Name error:", wrong.json()["error"]["code"], wrong.json()["error"]["message"])
        # a GET marked with the pinned revision, which the app refuses rather than serving its 2025 stream
        stream = httpx2.get(base_url + "/mcp", headers={"MCP-Protocol-Version": http_mcp.VERSION})
        print("GET status:", stream.status_code)
        print("GET allow:", stream.headers["allow"])


asyncio.run(main())
