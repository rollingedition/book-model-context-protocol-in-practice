"""A rug pull: the partner's server changes `track_parcel`'s description in its next release. The host pinned each
definition it approved, so it notices the change and keeps the tool from the model until the user approves again. The
title and read-only hint are unchanged, and the last line shows which tools the model is left with."""
import asyncio

from mcp import Client

from lib import host_guard, owned_shop, partner


async def listed(server):
    async with Client(server) as client:
        return client.protocol_version, client.server_info.version, (await client.list_tools()).tools


async def main() -> None:
    pins = host_guard.ToolPins()
    revision, _, shop_tools = await listed(owned_shop.create_server())
    _, version, partner_tools = await listed(partner.create_server("clean"))
    print("protocol revision:", revision)
    pins.approve("shop", shop_tools)
    pins.approve("partner", partner_tools)              # the user read and approved these definitions
    print(f"approved: partner {version},", ", ".join(tool.name for tool in partner_tools))
    print("approved sha256:", host_guard.definition_sha256(partner_tools[0])[:16])   # 16 hex digits of the hash

    _, version, partner_tools = await listed(partner.create_server("updated"))   # the partner's next release
    status = pins.check("partner", partner_tools)
    print(f"partner {version}, track_parcel:", status["track_parcel"])
    print("released sha256:", host_guard.definition_sha256(partner_tools[0])[:16])   # the first 16 hex digits, as above
    print("fields changed:", ", ".join(pins.changes("partner", partner_tools[0])))
    print("title the user sees:", partner_tools[0].title)
    assert partner_tools[0].annotations.read_only_hint is True   # the hint is still set after the change
    print("shop's tools:", ", ".join(sorted(set(pins.check("shop", shop_tools).values()))))
    shown = pins.usable("shop", shop_tools) + pins.usable("partner", partner_tools)
    print("tools the model sees:", ", ".join(tool.name for tool in shown))


asyncio.run(main())
