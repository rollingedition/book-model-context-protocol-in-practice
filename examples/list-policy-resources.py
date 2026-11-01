"""Serve the shop's six policies as static resources, then list them and read the refund policy from a client."""
import asyncio
import sys

from mcp import Client, StdioServerParameters
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FileResource
from mcp.types import Annotations

from lib.policies import load_policies

HOUR_MS = 3_600_000
server = MCPServer("shop-support", version="0.4.0", cache_hints={   # policies are the same for every caller
    "resources/list": CacheHint(ttl_ms=HOUR_MS, scope="public"),
    "resources/read": CacheHint(ttl_ms=HOUR_MS, scope="public")})

for policy in load_policies():
    server.add_resource(FileResource(
        uri=f"shop://policies/{policy.slug}", name=f"{policy.slug}-policy", title=policy.title,
        description=policy.summary, mime_type="text/markdown", path=policy.path,
        annotations=Annotations(audience=["assistant"], priority=1.0 if policy.slug == "refund" else 0.5,
                                last_modified=f"{policy.updated}T00:00:00Z")))


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[__file__, "--serve"], env={})
    async with Client(params) as client:
        print("protocol revision:", client.protocol_version)
        listed = await client.list_resources()
        print("resources:", len(listed.resources))
        for resource in listed.resources:
            print(f"  {resource.uri}  {resource.title!r}  priority {resource.annotations.priority}")
        print("list cache scope:", listed.cache_scope)
        print("list ttl ms:", listed.ttl_ms)
        read = await client.read_resource("shop://policies/refund")
        contents = read.contents[0]
        print("mime type:", contents.mime_type)
        print("first line:", contents.text.splitlines()[0])
        print("read cache scope:", read.cache_scope)
        print("read ttl ms:", read.ttl_ms)


if __name__ == "__main__":
    server.run() if "--serve" in sys.argv else asyncio.run(main())
