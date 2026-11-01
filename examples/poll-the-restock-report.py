"""Call restock_report through a client that polls the task, and get the report as an ordinary tool result."""
import asyncio
import os

from mcp import Client

from lib import http_mcp, loopback, shop_api, tasks

server = http_mcp.load_server("declare-the-tasks-extension.py")     # the shop's server with the Tasks extension


async def main() -> None:
    polls = []
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(server.streamable_http_app()) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        async with Client(base_url + "/mcp", extensions=[tasks.TasksClient(on_poll=polls.append)]) as client:
            result = await client.call_tool("restock_report", {"below": 30})
    statuses = [p["status"] for p in polls]
    print("statuses:", " then ".join(dict.fromkeys(statuses)))
    print("more than one working poll:", statuses.count("working") > 1)
    counted = [int(p["statusMessage"].split()[1]) for p in polls if "statusMessage" in p]
    print("messages count up:", counted == sorted(counted))
    print("last message:", polls[-1]["statusMessage"])
    print("result type:", type(result).__name__)
    report = result.structured_content
    print("skus recounted:", report["skus"])
    print("to reorder:", len(report["reorder"]))
    print("first to reorder:", "{sku}, {units} units".format(**report["reorder"][0]))


asyncio.run(main())
