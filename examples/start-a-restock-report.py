"""Call restock_report and get a task handle back at once; the task is already stored and working."""
import asyncio
import os

from mcp import Client

from lib import http_mcp, loopback, shop_api, tasks, wire

server = http_mcp.load_server("declare-the-tasks-extension.py")     # the shop's server with the Tasks extension


async def main() -> None:
    app = wire.record_http(server.streamable_http_app(), log="start.jsonl")
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(app) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        async with Client(base_url + "/mcp", extensions=[tasks.TasksClient()]) as client:
            handle = await client.session.call_tool("restock_report", {"below": 30}, allow_claimed=True)
            task = await tasks.get(client.session, handle.task_id)
    print("result type:", handle.result_type)
    print("handle fields:", ", ".join(sorted(handle.model_dump(by_alias=True, exclude_none=True))))
    print("status:", handle.status)
    print("created at:", handle.created_at)
    print("ttl ms:", handle.ttl_ms)
    print("poll interval ms:", handle.poll_interval_ms)
    print("task id length:", len(handle.task_id))
    print("tasks/get straight after:", task["status"])
    exchanges = wire.read_http_trace("start.jsonl")
    get = next(e for e in exchanges if e["request"]["method"] == "tasks/get")
    print("Mcp-Name is the task id:", get["request_headers"].get("mcp-name") == handle.task_id)


asyncio.run(main())
