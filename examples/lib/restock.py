"""The work behind chapter 7's `restock_report` tool: recount every product, then list the ones to reorder.

    from lib import restock
    report = await restock.run(below=30)                     # a restock.RestockReport
    steps = restock.Steps(); await restock.run(30, steps=steps)  # each SKU waits for steps.allow(), from any thread

`run` walks `lib.recount.SKUS` in catalogue order and asks the shop's API to recount each one, through chapter 6's
`lib.recount`, waiting `seconds` per SKU. After each SKU it sets the task's status message ("recounted 12 of 64
SKUs") with `lib.tasks.report`, and checks `lib.tasks.cancel_requested()`: if the client has cancelled the task, it
stops there and raises `lib.tasks.TaskCancelledError`. In a plain call, both do nothing. The report lists, in catalogue
order, each SKU whose recounted units across both warehouses are below `below`. The API's address and key come from
the environment, as `lib.shop_api.server_env()` sets them.

`Steps` lets an example decide when the work moves on, so its output never depends on the machine's speed: with
`steps=`, `run` waits before each SKU until `steps.allow()` has been called once more. An example calls `allow()`
from its own thread; the server's event loop runs in another, which is why `Steps` hands the wake-up across with
`call_soon_threadsafe`.
"""
from __future__ import annotations

import asyncio
import threading

from pydantic import BaseModel

from lib import recount, tasks


class Reorder(BaseModel):
    sku: str
    units: int                   # units on hand across both warehouses, as recounted


class RestockReport(BaseModel):
    skus: int                    # products recounted
    below: int                   # the threshold the report used
    reorder: list[Reorder]       # products under the threshold, in catalogue order


class Steps:
    """Permission to start SKUs: `allow(k)` lets `k` more begin. Safe to call from any thread."""

    def __init__(self) -> None:
        self._lock, self._allowed = threading.Lock(), 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._moved = asyncio.Event()

    def allow(self, k: int = 1) -> None:
        with self._lock:
            self._allowed += k
            loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._moved.set)

    async def wait(self, n: int) -> None:
        """Return once SKU `n` (counting from 1) is allowed to start."""
        while True:
            with self._lock:
                self._loop = asyncio.get_running_loop()
                if self._allowed >= n:
                    return
                self._moved.clear()
            await self._moved.wait()


async def run(below: int, seconds: float = recount.SECONDS_PER_SKU, steps: Steps | None = None) -> RestockReport:
    """Recount every SKU, `seconds` each, and report those with fewer than `below` units."""
    reorder = []
    async with recount.api() as api:
        for n, sku in enumerate(recount.SKUS, 1):
            if steps is not None:
                await steps.wait(n)
            units = await recount.one(api, sku, seconds=seconds)
            if units < below:
                reorder.append(Reorder(sku=sku, units=units))
            tasks.report(f"recounted {n} of {len(recount.SKUS)} SKUs")
            if tasks.cancel_requested():
                raise tasks.TaskCancelledError(f"stopped after {n} of {len(recount.SKUS)} SKUs")
    return RestockReport(skus=len(recount.SKUS), below=below, reorder=reorder)
