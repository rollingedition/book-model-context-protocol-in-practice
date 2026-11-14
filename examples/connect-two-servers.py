"""Two clients under their own prefixes each settle their own revision, and the SDK's ClientSessionGroup settles the
shop's server on an older one. A reconnect that reuses the cached era sends no server/discover probe, which the
example asserts before it prints the first request."""
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
        # mode is the revision the first connection settled on, prior_discover its cached era: no probe is sent
        async with Client(params, mode=revision, prior_discover=era) as again:
            await again.list_tools()
            print("reconnect protocol revision:", again.protocol_version)
    # "out" marks the messages the client sent, as the relay logged them
    methods = [message.get("method") for direction, message in wire.read_trace(str(LOG)) if direction == "out"]
    assert "server/discover" not in methods      # the reconnect never probed, because the era was cached
    print("reconnect first request:", methods[0])        # index 0: the first message the reconnect sent
    LOG.unlink()

asyncio.run(main())
