"""Call restock_report through a client whose extension polls the task until it ends, and get the report back as an ordinary tool result. The asserts check that the report was still working on more than one poll and that its messages only counted up, which the prose relies on."""
import asyncio
import os

from mcp import Client

from lib import http_mcp, loopback, shop_api, tasks

server = http_mcp.load_server("declare-the-tasks-extension.py")     # the shop's server with the Tasks extension


async def main() -> None:
    polls = []
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(server.streamable_http_app()) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        # on_poll keeps every tasks/get reply, in the order the client received them
        async with Client(base_url + "/mcp", extensions=[tasks.TasksClient(on_poll=polls.append)]) as client:
            result = await client.call_tool("restock_report", {"below": 30})
    statuses = [p["status"] for p in polls]
    # dict.fromkeys drops repeated statuses but keeps their order, so each status is listed once
    print("statuses:", " then ".join(dict.fromkeys(statuses)))
    assert statuses.count("working") > 1, statuses
    # the second word of "recounted N of 64 SKUs" is N
    counted = [int(p["statusMessage"].split()[1]) for p in polls if "statusMessage" in p]
    assert counted == sorted(counted), counted
    print("last message:", polls[-1]["statusMessage"])
    print("result type:", type(result).__name__)
    report = result.structured_content
    print("skus recounted:", report["skus"])
    print("to reorder:", len(report["reorder"]))
    # the first of the products the report lists for reordering
    print("first to reorder:", "{sku}, {units} units".format(**report["reorder"][0]))


asyncio.run(main())
