"""The partner's next release adds its own get_order_status. ClientSessionGroup refuses the second server; the host's
prefixes keep both tools, and route each name the model sees back to its server and its name on the wire."""
import asyncio
import sys

from mcp import MCPError, StdioServerParameters
from mcp.client.session_group import ClientSessionGroup
from mcp.types import ToolAnnotations

from lib import host_guard, loopback, partner, shop_api, support_shop, ticket_host

server = partner.create_server("clean")


@server.tool(title="Look up a delivery order", annotations=ToolAnnotations(read_only_hint=True))
def get_order_status(delivery_id: str) -> str:
    """Where one of the partner's delivery orders is, by its delivery ID, such as D-58120."""
    return f"{delivery_id}: out for delivery"


async def main() -> None:
    mine = StdioServerParameters(command=sys.executable, args=[__file__, "--serve"], env={})
    with loopback.serve(shop_api.create_app()) as base_url:
        servers = {"shop": support_shop.server_params(base_url), "partner": mine}
        async with ClientSessionGroup() as group:
            for params in servers.values():
                try:
                    await group.connect_to_server(params)
                except MCPError as error:
                    print("ClientSessionGroup:", error)
        gate = host_guard.ConsentGate(host_guard.NO_SIDE_EFFECTS, ask=ticket_host.approve_every_call)
        async with ticket_host.TicketHost(servers, gate=gate, lead=ticket_host.decline_every_request) as host:
            names = [tool.name for tool in host.tools()]
            print("tools the model sees:", len(names))
            for name in names:
                if name.endswith("get_order_status"):
                    print(f"{name} routes to:", host.route(name))
            print("get_order_status routes to:", host.route("get_order_status"))


server.run() if "--serve" in sys.argv else asyncio.run(main())
