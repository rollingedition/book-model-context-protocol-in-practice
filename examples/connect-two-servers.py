"""The host opens one Client per server, under its own prefixes, and each connection settles its own revision. The
SDK's ClientSessionGroup, given the same shop server, settles on a 2025 revision. A reconnect reuses the cached era."""
import asyncio
import pathlib

from mcp import Client
from mcp.client.session_group import ClientSessionGroup

from lib import loopback, shop_api, support_shop, ticket_host, wire

LOG = pathlib.Path("connect-two-servers.jsonl")


async def main() -> None:
    LOG.unlink(missing_ok=True)
    with loopback.serve(shop_api.create_app()) as base_url:
        async with ticket_host.queue_host(base_url) as host:
            for prefix, client in host.clients.items():
                print(f"{prefix} server:", client.server_info.name)
                print(f"{prefix} protocol revision:", client.protocol_version)
            era = host.clients["shop"].session.discover_result         # what the probe learned, kept per server
            revision = host.clients["shop"].protocol_version
        async with ClientSessionGroup() as group:
            session = await group.connect_to_server(support_shop.server_params(base_url))
            print("ClientSessionGroup protocol revision:", session.protocol_version)
        params = wire.relay(support_shop.server_params(base_url), log=str(LOG))
        async with Client(params, mode=revision, prior_discover=era) as again:
            await again.list_tools()
            print("reconnect protocol revision:", again.protocol_version)
    methods = [message.get("method") for direction, message in wire.read_trace(str(LOG)) if direction == "out"]
    print("reconnect sent server/discover:", "server/discover" in methods)
    print("reconnect first request:", methods[0])
    LOG.unlink()

asyncio.run(main())
