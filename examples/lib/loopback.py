"""Start and stop servers on 127.0.0.1, on a free port. Nothing more.

    from lib import loopback
    with loopback.serve(app) as base_url:      # "http://127.0.0.1:PORT"
        ...

`serve` runs any ASGI app (the shop's API, or an MCP server's Streamable HTTP app) under uvicorn in a background
thread, waits until it accepts connections, and shuts it down when the block ends. The port changes from run to run,
so examples never print `base_url`. The examples harness brings loopback up inside its network namespace; nothing
beyond the machine is reachable.
"""
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn

HOST = "127.0.0.1"


@contextmanager
def serve(app, *, startup_timeout: float = 10.0) -> Iterator[str]:
    """Serve `app` on 127.0.0.1 and yield its base URL, such as "http://127.0.0.1:50123"."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="auto"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + startup_timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"server on {HOST}:{port} did not start")
        time.sleep(0.01)
    try:
        yield f"http://{HOST}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
