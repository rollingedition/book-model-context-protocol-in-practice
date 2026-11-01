"""Replay chapter 10's queue run, and check what the replies claim against what the host's call log shows (chapter 11).

    from lib import queue_replay
    runs = await queue_replay.replay_queue()            # {"T-0001": Run, ...}, every ticket in the shop's queue
    queue_replay.unbacked_refund(runs["T-0048"])        # True: the reply promises a refund no call made

`replay_queue()` runs the support host exactly as chapter 10's `work-the-ticket-queue` does: the shop's API on
loopback, `ticket_host.queue_host` with the shop's server over stdio and the partner's in-process, the refund policy
attached, and the model's replies from the recording `ticket-runs`. Nothing calls a model. A replay holds only for
the exact messages the recording saw, so it raises `lib.host.RecordingMismatch` as soon as a prompt differs: a
changed tool description, tool result or prompt; `replay_queue` raises it unwrapped from the clients' exception
groups. `change(host)`, if given, runs after the host connects and before
the first ticket, so a test can change what the host shows the model and see the replay stop.

The promise check is chapter 10's, `ticket_host.promises_refund`, with its phrase list `REFUND_PROMISE` ("will be
processed", "we'll refund" and similar), so the two chapters count the same replies. It is a rule of thumb written
against this recording's replies, not a classifier: it misses promises worded otherwise, such as "your refund has
been issued", and it would flag "your refund will be processed once a lead confirms it", which is true when the
refund is held.
`unbacked_refund(run)` is True when the run's last reply promises a refund and no `issue_refund` call in the run
returned a result. A host would send such a ticket to a person before the reply reaches the customer.
`manifest()` is the recording's manifest: the model, its quantization, the sampling settings and the batches.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from lib import loopback, shop_api, ticket_host
from lib.host import RecordingMismatch, ReplayModel
from lib.shop_data import load_shop

RECORDING = "ticket-runs"


async def replay_queue(change: Callable[[ticket_host.TicketHost], Awaitable[None] | None] | None = None,
                       tickets=None) -> dict[str, ticket_host.Run]:
    """Work every ticket (or `tickets`) through the support host, replaying chapter 10's recording."""
    model = ReplayModel(RECORDING)
    tickets = load_shop().tickets if tickets is None else tickets
    try:
        with loopback.serve(shop_api.create_app()) as base_url:
            async with ticket_host.queue_host(base_url) as host:
                await host.attach("shop")
                if change is not None and (pending := change(host)) is not None:
                    await pending
                return {ticket.ticket_id: await host.work(model, ticket) for ticket in tickets}
    except BaseExceptionGroup as group:              # the clients' task groups wrap what the loop raised
        mismatch = group.subgroup(RecordingMismatch)
        while isinstance(mismatch, BaseExceptionGroup):
            mismatch = mismatch.exceptions[0]
        raise (mismatch or group) from None


def refunded(run: ticket_host.Run) -> bool:
    """Whether any `issue_refund` call in the run came back as a result."""
    return any(turn.tool == "shop.issue_refund" and turn.outcome == "result" for turn in run.calls)


def unbacked_refund(run: ticket_host.Run) -> bool:
    """The reply promises a refund that the host's call log doesn't show."""
    return ticket_host.promises_refund(run.answer) and not refunded(run)


def manifest() -> dict:
    """The manifest of the recording `ticket-runs`: model, quantization, sampling and batches."""
    return json.loads((ReplayModel(RECORDING).folder / "manifest.json").read_text())
