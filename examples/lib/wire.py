"""The wire trace: record every JSON-RPC message a stdio client and server exchange, and print them compactly.

The SDK's in-process client sends no JSON-RPC at all, so a faithful trace needs a real stdio subprocess. `relay()`
puts a small relay between the client and the server: the client launches the relay, the relay launches the real
server, copies every line in both directions unchanged, and appends each line to a log file. The trace is the exact
bytes on the wire.

    from lib import wire
    params = wire.relay(StdioServerParameters(command=sys.executable, args=["server.py", "--serve"], env=env),
                        log="wire.jsonl")
    async with Client(params) as client: ...
    wire.print_trace("wire.jsonl")

`print_trace` prints each message with its number, direction (`->` client to server, `<-` server to client), kind
and method: in full for the numbers you pass as `full`, otherwise on one line. Request IDs are replaced by 1, 2, 3 in
order of appearance, so the output is stable; values under keys that look like secrets (`token`, `key`,
`authorization`, `password`, `secret`, `cookie`) print as "[redacted]"; objects nested too deep print as "{…}". Run as
a script, this file is the relay itself.

Chapter 6 adds HTTP exchanges. `record_http(app, log)` wraps an ASGI app, such as an MCP server's Streamable HTTP
app, starts `log` empty, and appends one JSON line to it per HTTP exchange, as the app saw it: method, path, request headers and body,
response status and headers, the JSON-RPC messages in the response (one JSON body, or each `data:` event of an SSE
stream), the number of SSE comment lines such as `: ping`, and whether the response finished or the client went
away first. Header names are lowercase, as ASGI gives them, and values under secret-looking names print as
"[redacted]". `read_http_trace(log)` returns the exchanges in order, as dicts.

    app = wire.record_http(server.streamable_http_app(), log="http.jsonl")
    with loopback.serve(app) as base_url: ...
    for exchange in wire.read_http_trace("http.jsonl"): print(exchange["status"], exchange["request_headers"])
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

SECRET_WORDS = ("token", "key", "authorization", "password", "secret", "cookie")


def relay(server, log: str):
    """StdioServerParameters that launch `server` behind the recording relay, logging to `log`."""
    from mcp import StdioServerParameters
    return StdioServerParameters(
        command=sys.executable, args=[os.path.abspath(__file__), os.path.abspath(log), "--", server.command,
                                      *server.args], env=server.env, cwd=server.cwd)


def read_trace(log: str) -> list[tuple[str, dict]]:
    """The logged messages, in order, as (direction, message) pairs."""
    with open(log, encoding="utf-8") as f:
        return [(entry["dir"], json.loads(entry["line"])) for entry in map(json.loads, f)]


def kind(message: dict) -> str:
    if "method" in message:
        return "request" if "id" in message else "notification"
    return "error" if "error" in message else "result"


def compact(value, depth: int, max_string: int = 0, *, _level: int = 0):
    """`value` with secrets redacted, anything nested deeper than `depth` elided, and strings longer than
    `max_string` (when it is above 0) cut with "…"."""
    if isinstance(value, str) and max_string and len(value) > max_string:
        return value[:max_string - 1] + "…"
    if isinstance(value, dict):
        if _level >= depth:
            return "{…}"
        return {k: "[redacted]" if any(w in k.lower() for w in SECRET_WORDS) and not isinstance(v, dict | list)
                else compact(v, depth, max_string, _level=_level + 1) for k, v in value.items()}
    if isinstance(value, list):
        if _level >= depth:
            return "[…]"
        return [compact(v, depth, max_string, _level=_level + 1) for v in value]
    return value


def print_trace(log: str, full: tuple[int, ...] = (), depth: int = 3, max_string: int = 0) -> list[dict]:
    """Print the logged messages in order and return them.

    Each message gets a header line: its number, its direction, its kind, its method (for requests and
    notifications) and its request ID. Messages whose numbers are in `full` print in full as indented JSON, cut at
    `depth`, with strings cut at `max_string`; every other message prints its `params`, `result` or `error` on the
    same line, one level deep."""
    ids: dict = {}
    messages = []
    for n, (direction, message) in enumerate(read_trace(log), 1):
        if "id" in message:
            message["id"] = ids.setdefault(json.dumps(message["id"]), len(ids) + 1)
        messages.append(message)
        arrow = "->" if direction == "out" else "<-"
        header = " ".join(str(part) for part in (f"{n}.", arrow, kind(message), message.get("method"),
                                                  f"(id {message['id']})" if "id" in message else None) if part)
        if n in full:
            print(header)
            print(json.dumps(compact(message, depth, max_string), indent=2, ensure_ascii=False))
        else:
            key = next((k for k in ("params", "result", "error") if k in message), None)
            body = json.dumps(compact(message[key], 1), ensure_ascii=False) if key else ""
            print(header, f"{key}: {body}" if key else "")
    return messages


def _headers(raw) -> dict[str, str]:
    """ASGI header pairs as a dict of lowercase names, with secret-looking values redacted."""
    out: dict[str, str] = {}
    for name, value in raw:
        key = name.decode("latin-1").lower()
        out[key] = "[redacted]" if any(w in key for w in SECRET_WORDS) else value.decode("latin-1")
    return out


def _messages(content_type: str, body: bytes) -> tuple[list[dict], int]:
    """The JSON-RPC messages in a response body, and the number of SSE comment lines."""
    text = body.decode("utf-8", "replace")
    if content_type.startswith("text/event-stream"):
        messages, comments = [], 0
        for line in text.splitlines():
            if line.startswith("data:"):
                messages.append(json.loads(line[5:].strip()))
            elif line.startswith(":"):
                comments += 1
        return messages, comments
    try:
        return ([json.loads(text)] if text.strip() else []), 0
    except ValueError:
        return [], 0                     # a plain-text body, such as the SDK's "Invalid Origin header"


def record_http(app, log: str):
    """Wrap the ASGI `app` so that each HTTP exchange it serves is appended to `log`, emptied here, as one JSON line."""
    open(log, "w", encoding="utf-8").close()
    lock = threading.Lock()

    async def recorded(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        entry = {"method": scope["method"], "path": scope["path"], "request_headers": _headers(scope["headers"]),
                 "status": None, "response_headers": {}, "complete": False}
        request_body, response_body = bytearray(), bytearray()

        async def receive_logged():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
            return message

        async def send_logged(message):
            if message["type"] == "http.response.start":
                entry["status"] = message["status"]
                entry["response_headers"] = _headers(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                entry["complete"] = not message.get("more_body", False)
            await send(message)

        try:
            await app(scope, receive_logged, send_logged)
        finally:
            try:
                entry["request"] = json.loads(request_body) if request_body else None
            except ValueError:
                entry["request"] = None
            content_type = entry["response_headers"].get("content-type", "")
            entry["messages"], entry["comments"] = _messages(content_type, bytes(response_body))
            entry["body_text"] = bytes(response_body).decode("utf-8", "replace") if not entry["messages"] else None
            with lock, open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    return recorded


def read_http_trace(log: str) -> list[dict]:
    """The HTTP exchanges `record_http` logged, in the order they finished."""
    with open(log, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _pump(source, sink, direction: str, log, lock: threading.Lock) -> None:
    for line in iter(source.readline, b""):
        with lock:
            log.write(json.dumps({"dir": direction, "line": line.decode("utf-8").rstrip("\n")}) + "\n")
            log.flush()
        sink.write(line)
        sink.flush()
    sink.close()


def _main(argv: list[str]) -> int:
    log_path, command = argv[0], argv[argv.index("--") + 1:]
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    lock = threading.Lock()
    with open(log_path, "a", encoding="utf-8") as log:
        inbound = threading.Thread(target=_pump, args=(sys.stdin.buffer, child.stdin, "out", log, lock), daemon=True)
        outbound = threading.Thread(target=_pump, args=(child.stdout, sys.stdout.buffer, "in", log, lock))
        inbound.start()
        outbound.start()
        outbound.join()                  # the server closed its stdout: it has exited or is exiting
    return child.wait()


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
