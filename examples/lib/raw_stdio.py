"""Talk to a stdio MCP server one hand-written JSON-RPC line at a time, with no SDK client in between.

`mcp.Client` always sends a well-formed request, and refuses to send a protocol version it doesn't know. To show
what a server does with a request the SDK would never send, such as one with an unknown version or a missing
`_meta` key, write the line yourself:

    from lib import raw_stdio
    with raw_stdio.launch([sys.executable, "server.py", "--serve"], env=env) as server:
        reply = server.request("tools/list", meta=raw_stdio.envelope("2026-07-28"))

`request` writes one request, waits for the reply with the same ID, and returns it as a dict. Notifications and
other lines the server sends in between are skipped. The server's standard error is discarded.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

PREFIX = "io.modelcontextprotocol/"


def envelope(version: str, capabilities: dict | None = None, client_name: str | None = "shop-host") -> dict:
    """The per-request `_meta` keys a client sends: the protocol version, its capabilities (left out when
    `capabilities` is None) and, unless `client_name` is None, its name."""
    meta: dict = {PREFIX + "protocolVersion": version}
    if client_name is not None:
        meta[PREFIX + "clientInfo"] = {"name": client_name, "version": "0.1.0"}
    if capabilities is not None:
        meta[PREFIX + "clientCapabilities"] = capabilities
    return meta


class RawServer:
    def __init__(self, process: subprocess.Popen):
        self.process = process
        self.next_id = 1

    def request(self, method: str, params: dict | None = None, *, meta: dict) -> dict:
        """Send one request with `meta` as its `_meta`, and return the server's reply to it."""
        message_id, self.next_id = self.next_id, self.next_id + 1
        line = {"jsonrpc": "2.0", "id": message_id, "method": method, "params": {**(params or {}), "_meta": meta}}
        self.process.stdin.write((json.dumps(line) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        for raw in iter(self.process.stdout.readline, b""):
            reply = json.loads(raw)
            if reply.get("id") == message_id:
                return reply
        raise EOFError(f"the server exited before it answered {method}")


@contextmanager
def launch(command: list[str], env: dict[str, str] | None = None) -> Iterator[RawServer]:
    """Start `command` as a stdio server and close its standard input when the block ends."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env)
    try:
        yield RawServer(process)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()
