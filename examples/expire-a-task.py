"""Show the two ways a task ends early: its time to live runs out and the server purges it, or the client cancels it and the report stops at its next check. The -32602 from the purged task and the final status of the cancelled report are the lines the prose rests on."""
import asyncio
import os

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

from lib import loopback, restock, shop_api, tasks

clock = tasks.Clock()                                     # fake time: moves only when the example says so
first_steps, second_steps = restock.Steps(), restock.Steps()   # a report starts a product only when allowed
pending = [first_steps, second_steps]                     # one per call, in call order
# a task expires one minute after it was created, counted on the fake clock
server = MCPServer("shop-support", version="0.7.0",
                   extensions=[tasks.Tasks({"restock_report"}, ttl_ms=60_000, clock=clock)])


@server.tool(title="Restock report")
async def restock_report(below: int = 30) -> restock.RestockReport:
    """Recount every product's stock and list those with fewer than `below` units. Slow: runs as a task."""
    # calls arrive in order, so each report takes the next gate
    return await restock.run(below, steps=pending.pop(0))


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(server.streamable_http_app()) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        async with Client(base_url + "/mcp", extensions=[tasks.TasksClient()]) as client:
            first = await client.session.call_tool("restock_report", allow_claimed=True)
            print("first, ttl ms:", first.ttl_ms)         # first_steps allows no product, so it stays working
            print("first, first poll:", (await tasks.get(client.session, first.task_id))["status"])
            clock.advance(61)                             # 61 seconds: past the one-minute time to live
            try:
                await tasks.get(client.session, first.task_id)
            except MCPError as error:
                print("first, 61 s later:", error.error.code, error.error.message)
            second = await client.session.call_tool("restock_report", allow_claimed=True)
            second_steps.allow()                          # product 1 only: the report then waits before product 2
            task = await tasks.poll_until(client.session, second.task_id, lambda t: "statusMessage" in t)
            print("second, before cancel:", task["status"] + ",", task["statusMessage"])
            ack = await tasks.cancel(client.session, second.task_id)
            print("cancel acknowledged, besides _meta:", ", ".join(f"{k} {v}" for k, v in ack.items() if k != "_meta"))
            print("second, right after:", (await tasks.get(client.session, second.task_id))["status"])
            second_steps.allow()                          # product 2 starts; the check after it sees the cancel
            task = await tasks.poll_until(client.session, second.task_id, lambda t: t["status"] in tasks.TERMINAL)
            print("second, finally:", task["status"] + ",", task["statusMessage"])


asyncio.run(main())
