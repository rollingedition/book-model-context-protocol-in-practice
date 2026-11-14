"""Call restock_report and keep the handle the server answers with at once, instead of waiting for the report. The tasks/get sent straight after is the line the prose rests on: it finds the task, so the server stored it before the handle left."""
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
            # allow_claimed hands back the handle itself, not the result the client would otherwise wait for
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
    get = next(e for e in exchanges if e["request"]["method"] == "tasks/get")   # the tasks/get the client sent above
    # the trace stores header names in lowercase, so the lookup uses mcp-name
    assert get["request_headers"].get("mcp-name") == handle.task_id


asyncio.run(main())
