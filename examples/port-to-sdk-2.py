"""Tries the 2025 server's setup lines on SDK 2.x: two breaks fail with an error, and one fails silently. The prose's point,
that the second positional argument now sets the title, rests on the two title and instructions lines a client sees."""
import asyncio

from mcp import Client
from mcp.server.mcpserver import MCPServer

INSTRUCTIONS = "Answers the support team's questions about orders, refunds and stock."

try:
    from mcp.server.fastmcp import FastMCP          # the 2025 server's first import
except ModuleNotFoundError as error:
    print("import FastMCP:", str(error).split(". ", 1)[1].split("; see")[0])   # the message after its first sentence
try:
    from mcp.shared.exceptions import McpError      # what 1.x tools raised for protocol errors
except ImportError as error:
    print("import McpError:", str(error).split(" (")[0])   # drops the parenthetical
try:
    MCPServer("shop-support", instructions=INSTRUCTIONS, port=8000, stateless_http=False)   # port and stateless_http moved to run() and streamable_http_app() in 2.x
except TypeError as error:
    print("port on the constructor:", error)

as_written = MCPServer("shop-support", INSTRUCTIONS)                     # 1.x's second argument was instructions
ported = MCPServer("shop-support", instructions=INSTRUCTIONS, version="0.12.0")   # a keyword, so the string can't become the title


async def main() -> None:
    for label, server in (("as written", as_written), ("ported", ported)):
        async with Client(server) as client:
            print(f"{label} title:", client.server_info.title)
            print(f"{label} instructions:", client.instructions)


asyncio.run(main())
