"""The 2025 server asked the client for its roots to find a folder; the ported tool takes the folder as a parameter
and checks it against the folders the server's configuration allows."""
import asyncio
import os
from pathlib import Path

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lib import loopback, restock, shop_api

server = MCPServer("shop-support", version="0.12.0")
EXPORT_DIRS = [Path(d).resolve() for d in os.environ.get("SHOP_EXPORT_DIRS", "exports").split(",")]


@server.tool(description="Recount stock and save the restock report as CSV in export_dir, a folder the server allows.")
async def save_restock_report(export_dir: str) -> str:
    folder = Path(export_dir).resolve()                  # "exports/../private" resolves outside exports
    if folder not in EXPORT_DIRS:
        raise ToolError(f"{export_dir} isn't an export folder. Use one of: {', '.join(d.name for d in EXPORT_DIRS)}.")
    report = await restock.run(below=30, seconds=0)
    folder.mkdir(exist_ok=True)
    (folder / "restock.csv").write_text("sku,units\n" + "".join(f"{r.sku},{r.units}\n" for r in report.reorder))
    return f"Saved {len(report.reorder)} products to reorder in {export_dir}/restock.csv."


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))      # the server runs in this process
        async with Client(server) as client:
            for folder in ("exports", "exports/../private"):
                saved = await client.call_tool("save_restock_report", {"export_dir": folder})
                print(f"export to {folder}:", saved.content[0].text)


asyncio.run(main())
