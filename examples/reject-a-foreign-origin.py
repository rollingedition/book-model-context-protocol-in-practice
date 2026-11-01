"""The loopback default checks Origin and Host on every request; host="0.0.0.0" turns both checks off."""
from urllib.parse import urlsplit

from lib import http_mcp, loopback

server = http_mcp.load_server("serve-on-loopback.py")             # chapter 3's five tools
FOREIGN = "http://attacker.example"                                # a page in the user's browser, on another site


def probe(label: str, url: str, headers: dict[str, str]) -> None:
    response = http_mcp.post(url, "tools/list", headers=headers)
    print(f"{label}:", response.status_code, response.text if response.status_code != 200 else "tools listed")


def main() -> None:
    with loopback.serve(server.streamable_http_app()) as base_url:             # host defaults to 127.0.0.1
        url, own = base_url + "/mcp", f"http://127.0.0.1:{urlsplit(base_url).port}"
        probe("no Origin", url, {})
        probe("own Origin", url, {"Origin": own})
        probe("foreign Origin", url, {"Origin": FOREIGN})
        probe("foreign Host", url, {"Host": "fernhill.example"})
    with loopback.serve(server.streamable_http_app(host="0.0.0.0")) as base_url:   # still bound to 127.0.0.1
        probe("0.0.0.0 app, foreign Origin", base_url + "/mcp", {"Origin": FOREIGN})
        probe("0.0.0.0 app, foreign Host", base_url + "/mcp", {"Host": "fernhill.example"})


main()
