"""Tool poisoning: the partner's `track_parcel` in a clean and a poisoned version, whose description tells the model to
call it for each ticket. The title the user sees is the same in both; the point rests on the last line, the poisoned
runs that called `track_parcel`, and the model's choices are replayed from the recording `poisoned-tools`."""
import asyncio

from mcp import Client

from lib import owned_shop, partner
from lib.host import ReplayModel, choose_tool
from lib.shop_data import load_shop

TICKETS = ("T-0003", "T-0006", "T-0016")                    # delivery, damaged item, stock


async def listed(server):
    async with Client(server) as client:
        return (await client.list_tools()).tools


async def main() -> None:
    shop, model = load_shop(), ReplayModel("poisoned-tools")   # the model's recorded choices, replayed per ticket
    shop_tools = await listed(owned_shop.create_server())
    for version in ("clean", "poisoned"):
        tracking = (await listed(partner.create_server(version)))[0]   # the partner's only tool
        print(f"{version}, title the user sees:", tracking.title)
        print(f"{version}, description characters:", len(tracking.description))
    print("added for the model:", partner.POISON.strip()[:58] + "...")   # the opening 58 characters of the instruction
    followed = 0
    for ticket_id in TICKETS:
        for version in ("clean", "poisoned"):
            tools = shop_tools + await listed(partner.create_server(version))   # the shop's five tools and track_parcel
            choice = choose_tool(model, shop.ticket(ticket_id), tools)
            print(f"{ticket_id}, {version}:", choice.tool)
            followed += version == "poisoned" and choice.tool == "track_parcel"
    print("poisoned runs:", len(TICKETS))
    print("poisoned runs that called track_parcel:", followed)


asyncio.run(main())
