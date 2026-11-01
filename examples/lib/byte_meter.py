"""Count what one exchange costs on the wire: bytes each way through a TCP relay, and HTTP requests at the server.

    from lib import byte_meter, loopback
    app, requests = byte_meter.count_requests(app)
    with loopback.serve(app) as base_url, byte_meter.relay(base_url) as (url, traffic):
        ...                                   # send everything to `url`
    print(traffic.sent, traffic.received, requests.count)

`relay` listens on 127.0.0.1 on a free port and copies every connection to `base_url` unchanged, counting the bytes
the client sends (request lines, headers and bodies) and the bytes it receives. `count_requests` wraps an ASGI app and
counts the HTTP requests it handles, each one a round trip, keeping each request's `Mcp-Method` header. Both see
only loopback traffic, so the counts are the same on every machine for the same requests; times are not, so this
module measures none.

`meta_bytes(lines, meta)` measures, on lines logged as sent, the bytes that `"_meta": {...}` takes in the line that
carries `meta` (chapter 2's `request-meta-on-the-wire`).
"""
from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

HOST = "127.0.0.1"


@dataclass
class Traffic:
    sent: int = 0          # client to server
    received: int = 0      # server to client
    connections: int = 0

    def reset(self) -> None:
        self.sent = self.received = self.connections = 0


@dataclass
class RequestCount:
    count: int = 0
    names: list[str] = field(default_factory=list)   # each request's Mcp-Method header, else "GET /path"

    def reset(self) -> None:
        self.count = 0
        self.names.clear()


def count_requests(app):
    """`app` wrapped so that every HTTP request it handles adds one to the returned counter."""
    counter = RequestCount()

    async def counted(scope, receive, send):
        if scope["type"] == "http":
            counter.count += 1
            headers = dict(scope["headers"])
            counter.names.append(headers.get(b"mcp-method", f"{scope['method']} {scope['path']}".encode()).decode())
        await app(scope, receive, send)

    return counted, counter


def _pump(source: socket.socket, sink: socket.socket, traffic: Traffic, field: str, lock: threading.Lock) -> None:
    try:
        while chunk := source.recv(65536):
            with lock:
                setattr(traffic, field, getattr(traffic, field) + len(chunk))
            sink.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (sink, source):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


@contextmanager
def relay(base_url: str) -> Iterator[tuple[str, Traffic]]:
    """A counting TCP relay in front of `base_url`; yields the relay's base URL and its running byte counts."""
    upstream = urlsplit(base_url)
    listener = socket.create_server((HOST, 0))
    traffic, lock, threads, sockets = Traffic(), threading.Lock(), [], []

    def accept() -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            server = socket.create_connection((upstream.hostname, upstream.port))
            sockets.extend((client, server))
            with lock:
                traffic.connections += 1
            for args in ((client, server, traffic, "sent", lock), (server, client, traffic, "received", lock)):
                thread = threading.Thread(target=_pump, args=args, daemon=True)
                thread.start()
                threads.append(thread)

    acceptor = threading.Thread(target=accept, daemon=True)
    acceptor.start()
    try:
        yield f"http://{HOST}:{listener.getsockname()[1]}", traffic
    finally:
        listener.close()
        for thread in threads:
            thread.join(timeout=2)
        for sock in sockets:
            sock.close()


def meta_bytes(lines: list[str], meta: dict) -> int:
    """The bytes that `"_meta": {...}` takes in the logged line that carries `meta`, measured on the line as sent."""
    for line in lines:
        start = line.find('"_meta":')
        while start != -1:
            value_at = start + len('"_meta":')
            value_at += len(line[value_at:]) - len(line[value_at:].lstrip())
            value, end = json.JSONDecoder().raw_decode(line, value_at)
            if value == meta:
                return len(line[start:end].encode("utf-8"))
            start = line.find('"_meta":', start + 1)
    raise LookupError("no logged line carries that _meta")
