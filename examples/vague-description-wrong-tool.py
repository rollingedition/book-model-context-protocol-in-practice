"""Predict, then run: eight of the shop's tickets and the same five tools, shown to the model with three sets of
descriptions: one-line ones, the shop's first draft, and its revision. Only the descriptions differ. The model's
replies are a recording (examples/data/recorded/description-choices/), made with recordings/description_choices.py."""
import asyncio
import json

from mcp import Client

from lib import shop_tools
from lib.host import ReplayModel, choose_tool
from lib.shop_data import load_shop

TICKETS = ("T-0002", "T-0013", "T-0004", "T-0022", "T-0006", "T-0029", "T-0024", "T-0016")
SETS = {"vague": shop_tools.VAGUE_DESCRIPTIONS, "draft": shop_tools.DRAFT_DESCRIPTIONS,
        "revised": shop_tools.DESCRIPTIONS}
model = ReplayModel("description-choices")


def right_tool(ticket) -> str:
    """The tool a correct host calls first. issue_refund takes a quote_id, so a refund starts with quote_refund."""
    return "quote_refund" if ticket.expected_tool == "issue_refund" else ticket.expected_tool


async def main() -> None:
    shop = load_shop()
    async with Client(shop_tools.create_server()) as client:     # in-process: listing tools calls no API
        listed = (await client.list_tools()).tools
    right = dict.fromkeys(SETS, 0)
    for ticket_id in TICKETS:
        ticket = shop.ticket(ticket_id)
        choices = {label: choose_tool(model, ticket, shop_tools.with_descriptions(listed, descriptions))
                   for label, descriptions in SETS.items()}
        for label, choice in choices.items():
            right[label] += choice.tool == right_tool(ticket)
        if all(choice.tool == right_tool(ticket) for choice in choices.values()):
            print(f"{ticket_id} all three:", right_tool(ticket))
            continue
        print(f"{ticket_id} needs:", right_tool(ticket))
        for label, choice in choices.items():
            print(f"{ticket_id} {label}:", choice.tool or "none")
        if choices["revised"].tool == "quote_refund":
            print(f"{ticket_id} revised sku:", choices["revised"].arguments.get("sku"))
            print(f"{ticket_id} order's skus:", ", ".join(line.sku for line in shop.order(ticket.order_id).lines))
    print("sampling temperature:", json.loads((model.folder / "manifest.json").read_text())["sampling"]["temperature"])
    for label, count in right.items():
        print(f"{label} right:", f"{count} of {len(TICKETS)}")


asyncio.run(main())
