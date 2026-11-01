"""Cancel recount_stock after five progress reports by closing its response stream, and see the server stop."""
import os

import anyio
from mcp import Client
from mcp.server.mcpserver import Context, MCPServer

from lib import loopback, recount, shop_api, wire

server = MCPServer("shop-support", version="0.6.0")
runs: list = []                           # how a recount ended, and how many recounts it asked the API for


@server.tool(title="Recount stock")
async def recount_stock(ctx: Context) -> recount.Recount:
    """Recount every product's stock in both warehouses. Slow: reports progress per product."""
    done = units = 0
    async with recount.api() as api:
        try:
            for asked, sku in enumerate(recount.SKUS, 1):      # counted before each request to the API
                units += await recount.one(api, sku, seconds=0.1)
                done += 1
                await ctx.report_progress(done, total=len(recount.SKUS), message=f"recounted {sku}")
        except anyio.get_cancelled_exc_class():
            runs.extend([f"cancelled with {done} of {len(recount.SKUS)} recounted", asked])
            raise                         # always re-raise; cleanup that awaits goes under a shielded scope
    return recount.Recount(skus=done, units=units)


async def main() -> None:
    app = wire.record_http(server.streamable_http_app(), log="cancel.jsonl")
    with loopback.serve(shop_api.create_app()) as api_url, loopback.serve(app) as base_url:
        os.environ.update(shop_api.server_env(api_url))
        async with Client(base_url + "/mcp") as client:
            with anyio.CancelScope() as scope:
                async def on_progress(progress, total, message):
                    if progress >= 5:
                        scope.cancel()    # the host no longer needs the answer
                await client.call_tool("recount_stock", progress_callback=on_progress)
            await anyio.sleep(0.5)        # give the server time to see the closed stream
        print(f"server saw: {runs[0]}\nrecounts asked of the API: {runs[1]}")
    exchanges = wire.read_http_trace("cancel.jsonl")
    print("POSTs:", ", ".join(e["request"]["method"] for e in exchanges))
    kinds = [m.get("method", "result") for m in exchanges[-1]["messages"]]
    print("tools/call stream:", "finished" if exchanges[-1]["complete"] else "closed by the client")
    print("tools/call messages:", kinds.count("notifications/progress"), "progress,", kinds.count("result"), "result")


anyio.run(main)
