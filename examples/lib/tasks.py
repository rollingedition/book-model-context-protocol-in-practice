"""The book's own small Tasks extension (chapter 7), built on the Python SDK's extension framework.

`mcp` at the pinned release ships the framework (`mcp.server.extension.Extension`, `mcp.client.extension.ClientExtension`)
but no Tasks extension. This module implements the part of the Tasks extension's specification (SEP-2663, schema
snapshot 2026-07-28) that chapter 7 teaches, and no more: `tools/call` answered with a task handle, `tasks/get`
and `tasks/cancel`. It has no `tasks/update`, so a task here never asks for input, and no `notifications/tasks`
push. It keeps tasks in memory, in one process: a production server needs storage every replica shares.

Server side:

    clock = tasks.Clock()                                    # fake time: starts at 2026-06-30T09:00:00Z, moves on advance()
    server = MCPServer("shop-support", extensions=[tasks.Tasks({"restock_report"}, clock=clock)])
    tasks.report("recounted 12 of 64 SKUs")                  # inside a tool running as a task: its statusMessage
    tasks.cancel_requested()                                 # inside a tool: has the client sent tasks/cancel?

`Tasks(tool_names)` answers every call to those tools with a task, but only when that request's `_meta` declares the
extension; otherwise it raises -32021 (Missing Required Client Capability) through the SDK's
`require_client_extension`. `tasks/get` and `tasks/cancel` make the same check, and are served only at protocol
revision 2026-07-28, the first the extension applies to. It stores the task before it returns the handle, then runs the tool's ordinary handler
in the background, so the task's `result` is exactly what a plain call would have returned. Task IDs come from
`secrets.token_urlsafe`. `tasks/get` on a task whose `ttlMs` has passed on the clock purges it and answers -32602.
`tasks/cancel` acknowledges with an empty result and only sets a flag: the tool stops when it checks
`cancel_requested()`, and the task becomes `cancelled` then.

Client side:

    async with Client(url, extensions=[tasks.TasksClient(on_poll=print)]) as client:
        result = await client.call_tool("restock_report")    # polls tasks/get, returns the final CallToolResult
    await tasks.get(client.session, task_id)                  # one tasks/get, as a dict; Mcp-Name carries the ID
    await tasks.cancel(client.session, task_id)               # one tasks/cancel, as a dict
    await tasks.poll_until(client.session, task_id, done)     # tasks/get until done(task) holds; returns that task

`TasksClient` declares the extension on every request and claims `resultType: "task"`: it polls at the server's
`pollIntervalMs` until the task is terminal, calls `on_poll(task)` with each `tasks/get` reply, and returns the
`CallToolResult` from a completed task. A failed task raises `MCPError` with the task's error; a cancelled one
raises `TaskCancelled`.
"""
from __future__ import annotations

import asyncio
import contextvars
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from mcp.client.extension import ClaimContext, ClientExtension, ResultClaim
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver.server import require_client_extension
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, Request, RequestParams, Result
from mcp_types.jsonrpc import INVALID_PARAMS

EXTENSION_ID = "io.modelcontextprotocol/tasks"
TERMINAL = frozenset({"completed", "failed", "cancelled"})
START = datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc)      # the shop's reference date, never "today"


class Clock:
    """Fake time for task timestamps and TTLs: it moves only when `advance` is called, so outputs never vary."""

    def __init__(self, start: datetime = START) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _Task:
    task_id: str
    created_at: datetime
    ttl_ms: int | None
    poll_interval_ms: int
    status: str = "working"
    status_message: str | None = None
    last_updated_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False
    runner: asyncio.Task | None = field(default=None, repr=False)

    def wire(self, *, detailed: bool) -> dict[str, Any]:
        task = {"taskId": self.task_id, "status": self.status, "createdAt": _iso(self.created_at),
                "lastUpdatedAt": _iso(self.last_updated_at or self.created_at), "ttlMs": self.ttl_ms,
                "pollIntervalMs": self.poll_interval_ms}
        if self.status_message is not None:
            task["statusMessage"] = self.status_message
        if detailed and self.result is not None:
            task["result"] = self.result
        if detailed and self.error is not None:
            task["error"] = self.error
        return task


_current: contextvars.ContextVar[tuple[_Task, Clock] | None] = contextvars.ContextVar("current_task", default=None)


def report(message: str) -> None:
    """Set the running task's `statusMessage`. Outside a task (a plain call) it does nothing."""
    if (current := _current.get()) is not None:
        task, clock = current
        task.status_message, task.last_updated_at = message, clock.now()


def cancel_requested() -> bool:
    """Whether the client has sent `tasks/cancel` for the running task. Always False in a plain call."""
    current = _current.get()
    return current is not None and current[0].cancel_requested


class TaskCancelledError(MCPError):
    """Raised by a tool that saw `cancel_requested()`, so that its task ends `cancelled`.

    It subclasses `MCPError` only because the SDK passes `MCPError` through a tool unwrapped (anything else becomes
    an `isError` result); it never reaches the wire.
    """

    def __init__(self, message: str) -> None:
        super().__init__(code=-32603, message=message)


class TaskIdParams(RequestParams):
    task_id: str


class Tasks(Extension):
    """Answer calls to `tool_names` with a task; serve `tasks/get` and `tasks/cancel`."""

    identifier = EXTENSION_ID

    def __init__(self, tool_names: set[str], *, ttl_ms: int | None = 3_600_000, poll_interval_ms: int = 100,
                 clock: Clock | None = None) -> None:
        self.tool_names, self.ttl_ms, self.poll_interval_ms = set(tool_names), ttl_ms, poll_interval_ms
        self.clock = clock or Clock()
        self._tasks: dict[str, _Task] = {}

    def methods(self):
        revisions = frozenset({"2026-07-28"})                     # the extension doesn't apply to 2025-11-25
        return (MethodBinding("tasks/get", TaskIdParams, self._get, protocol_versions=revisions),
                MethodBinding("tasks/cancel", TaskIdParams, self._cancel, protocol_versions=revisions))

    async def intercept_tool_call(self, params, ctx, call_next):
        if params.name not in self.tool_names:
            return await call_next(ctx)
        require_client_extension(ctx, EXTENSION_ID)              # -32021 unless this request declared the extension
        task = _Task(secrets.token_urlsafe(24), self.clock.now(), self.ttl_ms, self.poll_interval_ms)
        self._tasks[task.task_id] = task                         # stored before the handle goes out
        token = _current.set((task, self.clock))
        try:
            task.runner = asyncio.create_task(self._run(task, call_next, ctx))
        finally:
            _current.reset(token)
        return {"resultType": "task", **task.wire(detailed=False)}

    async def _run(self, task: _Task, call_next, ctx) -> None:
        try:
            result = await call_next(ctx)
            task.result = result.model_dump(by_alias=True, mode="json", exclude_none=True)
            task.status = "completed"                            # an isError result completes too
        except TaskCancelledError as stopped:
            task.status, task.status_message = "cancelled", stopped.error.message
        except asyncio.CancelledError:
            task.status = "cancelled"
        except MCPError as error:
            task.error, task.status = {"code": error.error.code, "message": error.error.message}, "failed"
        except Exception as error:                               # noqa: BLE001 - any other failure is a JSON-RPC error
            task.error, task.status = {"code": -32603, "message": str(error)}, "failed"
        task.last_updated_at = self.clock.now()

    def _find(self, task_id: str) -> _Task:
        task = self._tasks.get(task_id)
        if task is not None and task.ttl_ms is not None:
            if self.clock.now() >= task.created_at + timedelta(milliseconds=task.ttl_ms):
                del self._tasks[task_id]                         # purged: its result is gone with it
                if task.runner is not None and not task.runner.done():
                    task.runner.cancel()
                raise MCPError(code=INVALID_PARAMS, message="Failed to retrieve task: Task has expired")
        if task is None:
            raise MCPError(code=INVALID_PARAMS, message="Failed to retrieve task: Task not found")
        return task

    async def _get(self, ctx, params: TaskIdParams) -> dict[str, Any]:
        require_client_extension(ctx, EXTENSION_ID)              # SEP-2663: -32021 for a client that didn't declare
        return {"resultType": "complete", **self._find(params.task_id).wire(detailed=True)}

    async def _cancel(self, ctx, params: TaskIdParams) -> dict[str, Any]:
        require_client_extension(ctx, EXTENSION_ID)
        task = self._find(params.task_id)
        if task.status not in TERMINAL:
            task.cancel_requested = True                         # cooperative: the tool decides when to stop
        return {}


# ---- client side -----------------------------------------------------------------------------------------------

class GetTaskRequest(Request[TaskIdParams, Literal["tasks/get"]]):
    name_param = "taskId"                                        # Streamable HTTP: Mcp-Name carries the task ID


class CancelTaskRequest(Request[TaskIdParams, Literal["tasks/cancel"]]):
    name_param = "taskId"


class TaskResult(Result):
    """A `tasks/get` reply, or a `tasks/cancel` acknowledgement, kept as the server sent it."""

    model_config = {"extra": "allow"}


async def get(session, task_id: str) -> dict[str, Any]:
    """Send one `tasks/get` and return the reply as a dict, as it came off the wire."""
    reply = await session.send_request(GetTaskRequest(method="tasks/get", params=TaskIdParams(task_id=task_id)),
                                       TaskResult)
    return reply.model_dump(by_alias=True, mode="json", exclude_none=True)


async def cancel(session, task_id: str) -> dict[str, Any]:
    """Send one `tasks/cancel` and return the acknowledgement as a dict."""
    reply = await session.send_request(CancelTaskRequest(method="tasks/cancel",
                                                         params=TaskIdParams(task_id=task_id)), TaskResult)
    return reply.model_dump(by_alias=True, mode="json", exclude_none=True)


async def poll_until(session, task_id: str, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """Send `tasks/get` until `done(task)` holds, and return that reply. It waits for a state, never for a time."""
    while not done(task := await get(session, task_id)):
        await asyncio.sleep(0.05)
    return task


class CreateTaskResult(Result):
    """The task handle a `tools/call` returns instead of a `CallToolResult`."""

    model_config = {"extra": "allow"}
    result_type: Literal["task"]
    task_id: str
    status: str
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None
    poll_interval_ms: int | None = None


class TaskCancelled(RuntimeError):
    """The task a call started ended `cancelled`, so there is no result."""


class TasksClient(ClientExtension):
    """Declare the Tasks extension and finish a task handle by polling `tasks/get`."""

    identifier = EXTENSION_ID

    def __init__(self, on_poll: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
                 on_handle: Callable[[CreateTaskResult], Awaitable[None] | None] | None = None) -> None:
        self.on_poll, self.on_handle = on_poll, on_handle

    def claims(self):
        return (ResultClaim(result_type="task", model=CreateTaskResult, resolve=self._resolve),)

    async def _resolve(self, handle: CreateTaskResult, ctx: ClaimContext) -> CallToolResult:
        await _maybe_await(self.on_handle, handle)
        interval = handle.poll_interval_ms or 1000
        while True:
            await asyncio.sleep(interval / 1000)
            task = await get(ctx.session, handle.task_id)
            await _maybe_await(self.on_poll, task)
            interval = task.get("pollIntervalMs") or interval     # the server may change it between polls
            if task["status"] == "completed":
                return CallToolResult.model_validate(task["result"])
            if task["status"] == "failed":
                raise MCPError(code=task["error"]["code"], message=task["error"]["message"])
            if task["status"] == "cancelled":
                raise TaskCancelled(f"task for {ctx.tool_name} was cancelled")


async def _maybe_await(callback, value) -> None:
    if callback is not None and (pending := callback(value)) is not None:
        await pending
