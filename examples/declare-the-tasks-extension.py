"""Declare the Tasks extension on the shop's server, then show what a client gets with it and without it: both declarations, and the
Missing Required Client Capability error a client without it gets from the call and from the task method. The prose's point rests on those two errors."""
import asyncio
import json
import os

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

from lib import loopback, restock, shop_api, tasks, wire

# only restock_report answers with a task; the server's other tools answer as usual
server = MCPServer("shop-support", version="0.7.0", extensions=[tasks.Tasks({"restock_report"})])


@server.tool(title="Restock report")
async def restock_report(below: int = 30) -> restock.RestockReport:
    """Recount every product's stock and list those with fewer than `below` units. Slow: runs as a task."""
    return await restock.run(below)


async def main() -> None:
    app = wire.record_http(server.streamable_http_app(), log="declare.jsonl")
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(app) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        async with Client(base_url + "/mcp", extensions=[tasks.TasksClient()]) as client:
            print("protocol revision:", client.protocol_version)
            print("server declares:", json.dumps(client.server_capabilities.extensions))
            await client.list_tools()
        async with Client(base_url + "/mcp") as plain:
            try:
                await plain.call_tool("restock_report")
            except MCPError as error:
                print("client without it:", error.error.code, error.error.message)
                # the specification's field, which lists the extensions the client lacked
                print("required:", json.dumps(error.error.data["requiredCapabilities"]))
            try:
                await tasks.get(plain.session, "any-task-id")       # the task methods check the declaration too
            except MCPError as error:
                print("tasks/get without it:", error.error.code)
    # the first tools/list the client sent, as the wire trace recorded it
    sent = next(e["request"] for e in wire.read_http_trace("declare.jsonl") if e["request"]["method"] == "tools/list")
    # at this revision a client declares its capabilities in the _meta of each request it sends
    print("client declares:", json.dumps(sent["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]))


asyncio.run(main())
