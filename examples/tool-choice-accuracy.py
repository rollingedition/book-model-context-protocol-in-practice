"""Score the first tool call of every ticket in chapter 10's queue run against the tool each ticket is tagged with,
overall, per tag and by confusion, and check the order IDs of the right calls. The prose's point rests on the
accuracy lines, the per-tag line for refunds, and the two order-ID lines, which differ."""
import asyncio
from collections import Counter

from lib import queue_replay, ticket_host
from lib.shop_data import load_shop


async def main() -> None:
    tickets = load_shop().tickets
    runs = await queue_replay.replay_queue()
    scored = []                                            # (ticket, expected tool, first tool called)
    for ticket in tickets:
        calls = runs[ticket.ticket_id].calls
        # the first call, or None when the host made none; a refund ticket expects quote_refund first
        scored.append((ticket, ticket_host.expected_first_tool(ticket), calls[0] if calls else None))
    right = [(t, call) for t, expected, call in scored if call and call.tool == expected]
    print("first tool right:", f"{len(right)} of {len(scored)}")
    print("top-1 accuracy:", f"{len(right) / len(scored):.2f}")
    for expected, count in sorted(Counter(expected for _, expected, _ in scored).items()):
        hits = sum(1 for t, e, call in scored if e == expected and call and call.tool == expected)
        print(f"expected {expected}:", f"{hits} of {count}")
    confusions = Counter((expected, call.tool if call else "no tool") for _, expected, call in scored
                         if not call or call.tool != expected)
    for (expected, chosen), count in confusions.most_common():
        print(f"expected {expected}, called {chosen}:", count)
    with_order = [(t, call) for t, call in right if t.order_id and "order_id" in call.arguments]  # right calls naming an order
    as_written = sum(call.arguments["order_id"] == t.cited_order_id for t, call in with_order)   # the ID the ticket gave
    meant = sum(call.arguments["order_id"] == t.order_id for t, call in with_order)              # the customer's order
    print("right tool, order ID as the ticket wrote it:", f"{as_written} of {len(with_order)}")
    print("right tool, order the customer meant:", f"{meant} of {len(with_order)}")
    # tickets whose cited ID isn't the order the customer meant
    typos = [(t, e, call) for t, e, call in scored if t.cited_order_id and t.cited_order_id != t.order_id]
    print("tickets with a mistyped order ID:", len(typos))
    print("of which the right tool was called:", sum(1 for _, e, call in typos if call and call.tool == e))
    for t, _, call in [(t, e, call) for t, e, call in typos if not call or call.tool != e]:
        print(f"mistyped {t.ticket_id}, first tool:", call.tool if call else "no tool")
    print("smallest expected-tool group, tickets:", min(Counter(e for _, e, _ in scored).values()))
    manifest = queue_replay.manifest()
    print("recorded model:", manifest["model"].split("/")[-1])   # the model's name, without its publisher's path
    print("recorded quantization:", manifest["quantization"])


asyncio.run(main())
