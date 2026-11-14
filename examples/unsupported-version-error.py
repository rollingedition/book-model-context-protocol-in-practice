"""Ask shop-support for a revision it doesn't implement, read its -32022 error, and retry with the newest revision both
sides list. The prose reads the error code, the versions in its data and the retry's tool list from the printed lines."""
import sys

from mcp import Client, StdioServerParameters
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from lib import raw_stdio

COMMAND = [sys.executable, "list-what-the-server-offers.py", "--serve"]
UNKNOWN = "2099-01-01"                       # stands for any revision this server doesn't implement

try:
    # the SDK's client checks the mode when it is built, so this raises before anything is sent
    Client(StdioServerParameters(command=COMMAND[0], args=COMMAND[1:]), mode=UNKNOWN)
except ValueError as refused:
    print("client refuses:", type(refused).__name__)

with raw_stdio.launch(COMMAND, env={}) as server:
    # capabilities={} declares no client capabilities: the request is well formed, and only its version is unknown
    error = server.request("tools/list", meta=raw_stdio.envelope(UNKNOWN, capabilities={}))["error"]
    print("error code:", error["code"])
    print("error message:", error["message"])
    print("server supports:", ", ".join(error["data"]["supported"]))     # the server lists its versions in the error's data
    print("client asked for:", error["data"]["requested"])

    # the versions both sides know, in the order the SDK lists them
    mutual = [version for version in MODERN_PROTOCOL_VERSIONS if version in error["data"]["supported"]]
    if not mutual:
        sys.exit("no version in common: show the user an error instead of retrying")
    print("retry with:", mutual[-1])        # the last of that list is the newest version both sides know
    # the same process: at this revision each request names its own version, so the retry needs no new connection
    retry = server.request("tools/list", meta=raw_stdio.envelope(mutual[-1], capabilities={}))
    print("retry tools:", ", ".join(tool["name"] for tool in retry["result"]["tools"]))
