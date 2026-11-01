"""Serve the shop's MCP servers over Streamable HTTP on loopback, and talk to them without the SDK's client (chapter 6).

    from lib import http_mcp
    with http_mcp.launch("serve-on-loopback.py", env=env) as url:      # "http://127.0.0.1:PORT/mcp"
        async with Client(url) as client: ...
    server.run(transport="streamable-http", port=http_mcp.port())       # in the launched file, under --serve

- `launch(example, env=...)` runs a server example as its own process, `python {example} --serve --port PORT`, on a
  free loopback port, waits until the port accepts connections, yields the MCP endpoint's URL, and stops the process
  when the block ends. Each process is one replica: it shares nothing with another but what you pass in `env`.
- `port()` is the port a launched file was given (`--port`), for `MCPServer.run(transport="streamable-http", ...)`.
- `post(url, method, params, ...)` sends one JSON-RPC request as a client at the pinned revision would: a POST with
  `Content-Type`, `Accept`, `MCP-Protocol-Version`, `Mcp-Method` and, for a named target, `Mcp-Name`, and the
  per-request `_meta` from `lib.raw_stdio.envelope`. `headers=` adds or overrides headers, so an example can send a
  request the SDK's client never would, such as one whose `Mcp-Name` disagrees with its body. It returns the
  `httpx2.Response`, read in full.
- `load_server(example)` returns the `server` that a server example defines, without running the example: it runs
  the file's statements except the last, which in this book's server examples is the line that serves or runs the
  client. A later chapter can then serve an earlier chapter's server over another transport.

The port changes from run to run, so examples never print a URL. Everything binds to 127.0.0.1.
"""
from __future__ import annotations

import ast
import itertools
import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2

from lib import raw_stdio

HOST = "127.0.0.1"
PATH = "/mcp"                                   # the SDK's default endpoint path
VERSION = "2026-07-28"
NAMED = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}   # methods that carry Mcp-Name
_ids = itertools.count(1)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def port(default: int = 8000) -> int:
    """The port after `--port` in this process's arguments, else `default` (the SDK's own default)."""
    return int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else default


@contextmanager
def launch(example: str, *, env: dict[str, str], startup_timeout: float = 15.0) -> Iterator[str]:
    """Run `example` with `--serve --port PORT` in its own process and yield its endpoint URL."""
    chosen = free_port()
    examples = Path(__file__).resolve().parent.parent
    process = subprocess.Popen([sys.executable, str(examples / example), "--serve", "--port", str(chosen)],
                               cwd=examples, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + startup_timeout
        while True:
            try:
                socket.create_connection((HOST, chosen), timeout=0.2).close()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"{example} did not start on {HOST}:{chosen}") from None
                time.sleep(0.05)
        yield f"http://{HOST}:{chosen}{PATH}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def post(url: str, method: str, params: dict | None = None, *, headers: dict[str, str] | None = None,
         version: str = VERSION) -> httpx2.Response:
    """POST one JSON-RPC request with the headers and `_meta` the pinned revision asks for; `headers` override."""
    body_params = {**(params or {}), "_meta": raw_stdio.envelope(version, capabilities={})}
    sent = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": version, "Mcp-Method": method}
    if method in NAMED:
        sent["Mcp-Name"] = str(body_params[NAMED[method]])
    sent.update(headers or {})
    body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": body_params}
    return httpx2.post(url, content=json.dumps(body), headers=sent, timeout=10.0)


def load_server(example: str):
    """The `server` object a server example defines, from running every statement of the file but its last."""
    path = Path(__file__).resolve().parent.parent / example
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tree.body = tree.body[:-1]
    namespace = {"__name__": path.stem.replace("-", "_"), "__file__": str(path)}
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace["server"]
