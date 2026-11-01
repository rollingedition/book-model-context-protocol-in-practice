"""Port the 2025 server's setup lines to SDK 2.x: two breaks that fail loudly, one that fails silently, and the fix."""
import asyncio

from mcp import Client
from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = "Answers the support team's questions about orders, refunds and stock."

try:
    from mcp.server.fastmcp import FastMCP          # the 2025 server's first import
except ModuleNotFoundError as error:
    print("import FastMCP:", str(error).split(". ", 1)[1].split("; see")[0])
try:
    from mcp.shared.exceptions import McpError      # what 1.x tools raised for protocol errors
except ImportError as error:
    print("import McpError:", str(error).split(" (")[0])
try:
    MCPServer("shop-support", instructions=INSTRUCTIONS, port=8000, stateless_http=False)
except TypeError as error:
    print("port on the constructor:", error)

as_written = MCPServer("shop-support", INSTRUCTIONS)                     # 1.x's second argument was instructions
ported = MCPServer("shop-support", instructions=INSTRUCTIONS, version="0.12.0")


async def main() -> None:
    for label, server in (("as written", as_written), ("ported", ported)):
        async with Client(server) as client:
            print(f"{label} title:", client.server_info.title)
            print(f"{label} instructions:", client.instructions)


asyncio.run(main())
