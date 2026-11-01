"""Call list_tools() twice on two servers, one with the SDK's default cache hint and one with a 5-minute public hint,
and count the tools/list requests that reach each server."""
import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from lib import wire


async def list_twice(script: str, second_call: str = "use") -> tuple[str, str, int]:
    log = Path(script).with_suffix(".jsonl")
    log.unlink(missing_ok=True)                          # the relay appends to its log
    server = StdioServerParameters(command=sys.executable, args=[script, "--serve"], env={})
    async with Client(wire.relay(server, log=str(log))) as client:
        first = await client.list_tools()                # cache_mode="use" is the default
        await client.list_tools(cache_mode=second_call)
        name = client.server_info.name
    sent = sum(1 for _, message in wire.read_trace(str(log)) if message.get("method") == "tools/list")
    return name, f"ttlMs {first.ttl_ms}, cacheScope {first.cache_scope}", sent


async def main() -> None:
    name, hint, sent = await list_twice("order-status-server.py")         # chapter 1's server sets no hint
    print(f"{name} hint:", hint)
    print(f"{name} tools/list sent for two calls:", sent)
    name, hint, sent = await list_twice("list-what-the-server-offers.py")
    print(f"{name} hint:", hint)
    print(f"{name} tools/list sent for two calls:", sent)
    name, hint, sent = await list_twice("list-what-the-server-offers.py", second_call="bypass")
    print(f"{name} tools/list sent when the second call bypasses:", sent)


asyncio.run(main())
