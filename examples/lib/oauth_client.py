"""The support host's side of OAuth: the SDK's `OAuthClientProvider`, with a scripted browser and in-memory storage
(chapter 8).

    from lib import oauth_client
    browser = oauth_client.ScriptedBrowser()
    async with oauth_client.connect(url, browser=browser) as client:     # a protected MCP server's endpoint
        await client.call_tool(...)
    browser.requests          # the query of each authorization request the host sent, as dicts

`provider(url, ...)` builds the SDK's `OAuthClientProvider` for one MCP server, with the support host's Client ID
Metadata Document URL (`lib.auth_server.CLIENT_ID`) as its `client_metadata_url` and the document's redirect URI. The
SDK does the rest: the 401, Protected Resource Metadata, authorization server metadata, PKCE, the `resource`
parameter, the `iss` check, the token request and step-up on 403.

A host opens the authorization URL in the user's browser and listens on the redirect URI for the answer.
`ScriptedBrowser` stands in for both, with no person and no listener: it requests the authorization URL, follows
the redirects an authorization server sends, and stops at the first one addressed to the redirect URI, whose `code`,
`state` and `iss` it hands to the SDK. Consent happens at the authorization server, which `lib.auth_server`
scripts. Each request's query is kept in `requests`, so an example can print what the host asked for.

`authorize_by_hand()` sends one authorization request without the SDK and returns the redirect's query, and
`s256(verifier)` computes a PKCE S256 challenge, for examples that show what an authorization server refuses.

`MemoryStorage` keeps tokens and client information for one provider, in memory. `connect()` returns a `Client`
whose HTTP client carries the provider, through the SDK's `streamable_http_client(url, http_client=...)`.
"""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qsl, urlsplit

import httpx2
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, OAuthFlowError
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from lib.auth_server import CLIENT_ID, REDIRECT_URI


class ScriptedBrowser:
    """Opens an authorization URL, follows redirects to the redirect URI, and returns what arrived there."""

    def __init__(self, redirect_uri: str = REDIRECT_URI):
        self.redirect_uri = redirect_uri
        self.requests: list[dict] = []
        self.arrived: dict | None = None

    async def open(self, url: str) -> None:
        async with httpx2.AsyncClient() as http:
            for _ in range(5):
                if url.startswith(self.redirect_uri):
                    self.arrived = dict(parse_qsl(urlsplit(url).query))
                    return
                self.requests.append(dict(parse_qsl(urlsplit(url).query)))
                response = await http.get(url)
                if response.status_code != 302:
                    raise OAuthFlowError(f"authorization server answered {response.status_code}: {response.text}")
                url = response.headers["location"]
        raise OAuthFlowError("too many redirects")

    async def answer(self) -> AuthorizationCodeResult:
        arrived = self.arrived or {}
        if "error" in arrived:
            raise OAuthFlowError(f"authorization failed: {arrived['error']}")
        return AuthorizationCodeResult(code=arrived.get("code", ""), state=arrived.get("state"),
                                       iss=arrived.get("iss"))


class MemoryStorage:
    """The SDK's `TokenStorage`, in memory."""

    def __init__(self):
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


def provider(url: str, *, browser: ScriptedBrowser, storage: MemoryStorage | None = None,
             client_metadata_url: str = CLIENT_ID) -> OAuthClientProvider:
    """The SDK's OAuth client for the MCP server at `url`, identified by the support host's metadata document."""
    metadata = OAuthClientMetadata(client_name="Fernhill support host", redirect_uris=[browser.redirect_uri],
                                   grant_types=["authorization_code"], response_types=["code"],
                                   token_endpoint_auth_method="none")
    return OAuthClientProvider(url, metadata, storage or MemoryStorage(), redirect_handler=browser.open,
                               callback_handler=browser.answer, client_metadata_url=client_metadata_url)


def connect(url: str, *, browser: ScriptedBrowser, storage: MemoryStorage | None = None, **client_options) -> Client:
    """A `Client` for the protected MCP server at `url`, authorizing through `provider()`."""
    auth = provider(url, browser=browser, storage=storage)
    http_client = httpx2.AsyncClient(auth=auth, timeout=30.0)
    return Client(streamable_http_client(url, http_client=http_client), **client_options)


def authorize_by_hand(issuer: str, resource: str, *, challenge: str, method: str = "S256",
                      scope: str = "orders:read") -> dict:
    """Send one authorization request with no SDK, as the support host, and return the query of the redirect it gets:
    `code`, `state` and `iss`, or `error`. For showing what an authorization server refuses."""
    query = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "state": "by-hand",
             "code_challenge": challenge, "code_challenge_method": method, "resource": resource, "scope": scope}
    response = httpx2.get(f"{issuer}/authorize", params=query)
    return dict(parse_qsl(urlsplit(response.headers["location"]).query))


def s256(verifier: str) -> str:
    """The PKCE S256 code challenge for `verifier`: BASE64URL(SHA-256(verifier)), unpadded."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
