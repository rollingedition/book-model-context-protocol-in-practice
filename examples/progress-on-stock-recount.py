"""recount_stock reports progress as it walks the shop's products, and a JSON-only server drops every report."""
import asyncio
import os

from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from lib import loopback, recount, shop_api, wire

server = MCPServer("shop-support", version="0.6.0")


@server.tool(title="Recount stock", annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
async def recount_stock(ctx: Context) -> recount.Recount:
    """Recount every product's stock in both warehouses. Slow: reports progress per product."""
    units = 0
    async with recount.api() as api:
        for n, sku in enumerate(recount.SKUS, 1):
            units += await recount.one(api, sku)
            await ctx.report_progress(n, total=len(recount.SKUS), message=f"recounted {sku}")
    return recount.Recount(skus=len(recount.SKUS), units=units)


async def run(mode: str, json_response: bool) -> None:
    app = wire.record_http(server.streamable_http_app(json_response=json_response), log=f"{mode}.jsonl")
    reports = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        reports.append((progress, total, message))

    with loopback.serve(app) as base_url:
        async with Client(base_url + "/mcp") as client:
            result = await client.call_tool("recount_stock", progress_callback=on_progress)
    call = next(e for e in wire.read_http_trace(f"{mode}.jsonl") if e["request"]["method"] == "tools/call")
    print(f"{mode} content-type:", call["response_headers"]["content-type"].split(";")[0])
    print(f"{mode} progress reports:", len(reports))
    print(f"{mode} last report:", "{:g} of {:g}, {}".format(*reports[-1]) if reports else "none")
    print(f"{mode} units counted:", result.structured_content["units"])


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))          # the servers run in this process
        await run("sse", json_response=False)
        await run("json", json_response=True)


asyncio.run(main())
