"""Ask shop-support for a protocol revision it doesn't support, read the error, and retry with one it does."""
import sys

from mcp import Client, StdioServerParameters
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from lib import raw_stdio

COMMAND = [sys.executable, "list-what-the-server-offers.py", "--serve"]
UNKNOWN = "2099-01-01"                       # stands for any revision this server doesn't implement

try:                                         # the SDK's client won't even send a version it doesn't know
    Client(StdioServerParameters(command=COMMAND[0], args=COMMAND[1:]), mode=UNKNOWN)
except ValueError as refused:
    print("client refuses:", type(refused).__name__)

with raw_stdio.launch(COMMAND, env={}) as server:
    error = server.request("tools/list", meta=raw_stdio.envelope(UNKNOWN, capabilities={}))["error"]
    print("error code:", error["code"])
    print("error message:", error["message"])
    print("server supports:", ", ".join(error["data"]["supported"]))
    print("client asked for:", error["data"]["requested"])

    mutual = [version for version in MODERN_PROTOCOL_VERSIONS if version in error["data"]["supported"]]
    if not mutual:
        sys.exit("no version in common: show the user an error instead of retrying")
    print("retry with:", mutual[-1])
    retry = server.request("tools/list", meta=raw_stdio.envelope(mutual[-1], capabilities={}))
    print("retry tools:", ", ".join(tool["name"] for tool in retry["result"]["tools"]))
