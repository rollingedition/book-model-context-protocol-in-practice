"""The shop's authorization server: a small OAuth 2.1 authorization server on loopback (chapter 8).

A teaching server for the book's loopback examples. Never deploy it: it signs no one in, consent is scripted, and its
signing key derives from the book's public seed, so anyone with the book can mint tokens it would accept.

The Python SDK has an authorization server of its own, but its documentation discourages it for new servers, and it
advertises neither `iss` on authorization responses nor Client ID Metadata Documents. So the book keeps this one. It
does what the pinned revision's authorization spec asks of an authorization server, and nothing more:

    GET  /.well-known/oauth-authorization-server   metadata (RFC 8414): endpoints, S256, iss and CIMD support
    GET  /authorize                                authorization code with PKCE S256 only, `resource` required
                                                   (RFC 8707); answers with a redirect carrying `code`, `state`
                                                   and `iss` (RFC 9207)
    POST /token                                    the code, once, for a JWT access token whose `aud` is the
                                                   `resource` and whose `scope` is what the user granted
    GET  /jwks.json                                the public key

    from lib import auth_server
    with auth_server.serve() as issuer:             # issuer.url is "http://127.0.0.1:PORT"
        verifier = auth_server.JwtVerifier(issuer.url)
        issuer.events                               # each /authorize and /token request, as dicts

Clients: the only client ID it knows is a Client ID Metadata Document URL, `CLIENT_ID`, an `https://` URL on
`support.fernhill.example`, the support team's host. The examples run with no network and that name never resolves, so
the server never fetches the document: it reads it from `documents`, a mapping from client ID URL to document that
stands in for the fetch. CIMD-02 section 5 allows an authorization server to "associate a Client Identifier URL with
client metadata through other means, such as by pre-registering the URL"; a deployed server fetches it over HTTPS.
It applies the checks it would apply to a fetched document: `client_id` equal to the URL, an `https` URL with a path,
`client_name` and `redirect_uris` present, no `client_secret` and no secret-based `token_endpoint_auth_method`, and a
`redirect_uri` that the document lists.

Consent is scripted: the signed-in user, `subject`, may grant the scopes in `user_scopes`, and grants every requested
scope among them. A request for none of them is denied. `send_iss=False` makes a server that omits `iss` from its
redirects, `advertise_iss=False` one that doesn't say it sends it, `pkce_methods=None` one whose metadata leaves out
`code_challenge_methods_supported`, and `metadata_issuer=` one whose metadata names another issuer than its own URL.

Tokens are JWTs signed with Ed25519. The key is derived from `SHOP_SEED`, so it is the same on every run and in every
process; it is not a secret, and a deployment keeps its own. Tokens carry `iss`, `sub`, `aud`, `client_id`, `scope`,
`iat`, `exp` and a random `jti`, live `TOKEN_SECONDS`, and come with no refresh token. `mint()` signs a token
directly, for examples that need a token without the flow, such as one for another audience. `JwtVerifier` is a
`TokenVerifier` for the SDK's `AuthSettings`: it checks the signature, the issuer and the expiry, and the audience
only when given one, and reports `aud` as `AccessToken.resource`. `claims(token)` reads a token's claims, for
printing them.

`serve_built(build)` serves any ASGI app that must know its own URL before it starts, such as a protected MCP server
whose `resource_server_url` includes its port. `MixUp` and `serve_mix_up()` are an attacker's authorization server for
the mix-up attack (chapter 8, and chapter 9's partner): it forwards the user to the honest server and redeems the
code the client then sends it.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx2
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.server.auth.provider import AccessToken
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from lib.shop_data import SHOP_SEED

HOST = "127.0.0.1"
SCOPES = ("orders:read", "stock:read", "refunds:write")
CLIENT_ID = "https://support.fernhill.example/oauth/client.json"
REDIRECT_URI = "http://localhost:4280/callback"
SUBJECT = "staff-0007"
TOKEN_SECONDS = 300
CODE_SECONDS = 60
SECRET_METHODS = ("client_secret_basic", "client_secret_post", "client_secret_jwt")


def client_document(**changes) -> dict:
    """The support host's Client ID Metadata Document, as it would be served at `CLIENT_ID`."""
    document = {"client_id": CLIENT_ID, "client_name": "Fernhill support host",
                "client_uri": "https://support.fernhill.example", "redirect_uris": [REDIRECT_URI],
                "grant_types": ["authorization_code"], "response_types": ["code"],
                "token_endpoint_auth_method": "none"}
    document.update(changes)
    return {key: value for key, value in document.items() if value is not None}


def signing_key() -> Ed25519PrivateKey:
    """The authorization server's signing key, derived from the shop's seed: the same in every process."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(f"auth-server:{SHOP_SEED}".encode()).digest())


def mint(issuer: str, audience: str, scopes: Iterable[str], *, subject: str = SUBJECT,
         client_id: str = CLIENT_ID, seconds: int = TOKEN_SECONDS) -> str:
    """A signed access token, as the token endpoint issues it."""
    now = int(time.time())
    claims = {"iss": issuer, "sub": subject, "aud": audience, "client_id": client_id, "scope": " ".join(scopes),
              "iat": now, "exp": now + seconds, "jti": secrets.token_urlsafe(12)}
    return jwt.encode(claims, signing_key(), algorithm="EdDSA")


def claims(token: str) -> dict:
    """A token's claims, signature checked, audience not: for printing what a token says."""
    return jwt.decode(token, signing_key().public_key(), algorithms=["EdDSA"], options={"verify_aud": False})


class JwtVerifier:
    """A `TokenVerifier` for the SDK: signature, issuer, expiry, and `aud` too when `audience` is given."""

    def __init__(self, issuer: str, *, audience: str | None = None):
        self.issuer, self.audience = issuer, audience

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            found = jwt.decode(token, signing_key().public_key(), algorithms=["EdDSA"], issuer=self.issuer,
                               audience=self.audience, options={"verify_aud": self.audience is not None,
                                                                "require": ["exp", "iat", "sub", "aud"]})
        except jwt.InvalidTokenError:
            return None
        return AccessToken(token=token, client_id=found["client_id"], scopes=found["scope"].split(),
                           expires_at=found["exp"], resource=found["aud"], subject=found["sub"], claims=found)


def document_problem(url: str, document: dict | None) -> str | None:
    """Why the authorization server refuses a Client ID Metadata Document, or None if it accepts it."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.path in ("", "/"):
        return "client_id must be an https URL with a path"
    if document is None:
        return "no metadata document at the client_id URL"
    if document.get("client_id") != url:
        return "document client_id differs from its URL"
    if not document.get("client_name") or not document.get("redirect_uris"):
        return "document lacks client_name or redirect_uris"
    if "client_secret" in document or document.get("token_endpoint_auth_method") in SECRET_METHODS:
        return "document carries a shared secret"
    return None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@dataclass
class AuthServer:
    """One authorization server's settings and what it saw; `app()` is its Starlette app."""
    url: str
    documents: Mapping[str, dict] = field(default_factory=lambda: {CLIENT_ID: client_document()})
    user_scopes: Iterable[str] = SCOPES
    subject: str = SUBJECT
    send_iss: bool = True
    advertise_iss: bool = True
    advertise_cimd: bool = True
    pkce_methods: tuple[str, ...] | None = ("S256",)
    metadata_issuer: str | None = None
    events: list[dict] = field(default_factory=list)
    codes: dict[str, dict] = field(default_factory=dict)

    def metadata(self) -> dict:
        found = {"issuer": self.metadata_issuer or self.url, "authorization_endpoint": f"{self.url}/authorize",
                 "token_endpoint": f"{self.url}/token", "jwks_uri": f"{self.url}/jwks.json",
                 "scopes_supported": list(SCOPES), "response_types_supported": ["code"],
                 "grant_types_supported": ["authorization_code"],
                 "token_endpoint_auth_methods_supported": ["none"],
                 "code_challenge_methods_supported": list(self.pkce_methods or ()),
                 "client_id_metadata_document_supported": self.advertise_cimd,
                 "authorization_response_iss_parameter_supported": self.advertise_iss}
        if self.pkce_methods is None:
            del found["code_challenge_methods_supported"]
        return found

    def app(self) -> Starlette:
        async def metadata(request: Request) -> JSONResponse:
            return JSONResponse(self.metadata())

        async def jwks(request: Request) -> JSONResponse:
            public = signing_key().public_key().public_bytes_raw()
            return JSONResponse({"keys": [{"kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig",
                                           "x": _b64(public)}]})

        return Starlette(routes=[Route("/.well-known/oauth-authorization-server", metadata),
                                 Route("/jwks.json", jwks), Route("/authorize", self._authorize),
                                 Route("/token", self._token, methods=["POST"])])

    async def _authorize(self, request: Request):
        query = dict(request.query_params)
        self.events.append({"endpoint": "authorize", **query})
        client_id, redirect_uri = query.get("client_id", ""), query.get("redirect_uri", "")
        problem = document_problem(client_id, self.documents.get(client_id))
        if problem:                                          # never redirect to an unverified client
            return JSONResponse({"error": "invalid_client", "error_description": problem}, status_code=400)
        if redirect_uri not in self.documents[client_id]["redirect_uris"]:
            return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri not in the "
                                 "client's metadata document"}, status_code=400)
        requested = query.get("scope", "").split()
        granted = [scope for scope in requested if scope in set(self.user_scopes)]
        if query.get("response_type") != "code":
            reply = {"error": "unsupported_response_type"}
        elif query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
            reply = {"error": "invalid_request", "error_description": "PKCE with S256 is required"}
        elif not query.get("resource"):
            reply = {"error": "invalid_target", "error_description": "resource is required"}
        elif any(scope not in SCOPES for scope in requested):
            reply = {"error": "invalid_scope"}
        elif not granted:
            reply = {"error": "access_denied"}
        else:
            code = secrets.token_urlsafe(24)
            self.codes[code] = {"client_id": client_id, "redirect_uri": redirect_uri, "scope": granted,
                                "challenge": query["code_challenge"], "resource": query["resource"],
                                "expires": time.monotonic() + CODE_SECONDS}
            reply = {"code": code}
        reply["state"] = query.get("state", "")
        if self.send_iss:
            reply["iss"] = self.url
        return RedirectResponse(f"{redirect_uri}?{urlencode(reply)}", status_code=302)

    async def _token(self, request: Request) -> JSONResponse:
        form = dict(await request.form())
        self.events.append({"endpoint": "token", **form})
        grant = self.codes.pop(form.get("code", ""), None)       # a code works once
        verifier = form.get("code_verifier", "")

        def error(code: str, description: str) -> JSONResponse:
            return JSONResponse({"error": code, "error_description": description}, status_code=400)

        if form.get("grant_type") != "authorization_code":
            return error("unsupported_grant_type", "only authorization_code")
        if grant is None or grant["expires"] < time.monotonic():
            return error("invalid_grant", "unknown, used or expired code")
        if form.get("client_id") != grant["client_id"] or form.get("redirect_uri") != grant["redirect_uri"]:
            return error("invalid_grant", "client_id or redirect_uri differs from the authorization request")
        if not verifier or _b64(hashlib.sha256(verifier.encode()).digest()) != grant["challenge"]:
            return error("invalid_grant", "code_verifier does not match code_challenge")
        if form.get("resource", grant["resource"]) != grant["resource"]:
            return error("invalid_target", "resource differs from the authorization request")
        token = mint(self.url, grant["resource"], grant["scope"], subject=self.subject, client_id=grant["client_id"])
        return JSONResponse({"access_token": token, "token_type": "Bearer", "expires_in": TOKEN_SECONDS,
                             "scope": " ".join(grant["scope"])}, headers={"Cache-Control": "no-store"})


@contextmanager
def serve_built(build) -> Iterator[str]:
    """Serve the ASGI app `build(base_url)` returns on 127.0.0.1, for apps that must know their own URL, such as an
    authorization server (its issuer) or a protected MCP server (its resource). Yields the base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, 0))
    base_url = f"http://{HOST}:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(build(base_url), log_level="warning", access_log=False, lifespan="auto"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"server at {base_url} did not start")
        time.sleep(0.01)
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@contextmanager
def serve(**options) -> Iterator[AuthServer]:
    """Run an authorization server on loopback; `options` are `AuthServer` fields. Yields the `AuthServer`."""
    made: list[AuthServer] = []

    def build(base_url: str) -> Starlette:
        made.append(AuthServer(url=base_url, **options))
        return made[0].app()

    with serve_built(build):
        yield made[0]


@dataclass
class MixUp:
    """An attacker's authorization server for a mix-up attack (RFC 9207, section 1). Its metadata looks like an honest
    server's, without `iss` support. Its authorization endpoint sends the browser on to the honest server's, with the
    client's own request but `resource` set to `target` and every scope asked for. Its token endpoint takes the code
    and the PKCE verifier the client sends it, redeems them at the honest server, and keeps what it got in `stolen`."""
    url: str
    honest: str
    target: str
    stolen: list[dict] = field(default_factory=list)

    def app(self) -> Starlette:
        async def metadata(request: Request) -> JSONResponse:
            found = AuthServer(url=self.url, advertise_iss=False).metadata()
            return JSONResponse(found)

        async def authorize(request: Request) -> RedirectResponse:
            query = {**request.query_params, "resource": self.target, "scope": " ".join(SCOPES)}
            return RedirectResponse(f"{self.honest}/authorize?{urlencode(query)}", status_code=302)

        async def token(request: Request) -> JSONResponse:
            form = {**await request.form(), "resource": self.target}
            async with httpx2.AsyncClient() as http:
                redeemed = await http.post(f"{self.honest}/token", data=form)
            self.stolen.append({"status": redeemed.status_code, **redeemed.json()})
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=400)

        return Starlette(routes=[Route("/.well-known/oauth-authorization-server", metadata),
                                 Route("/authorize", authorize), Route("/token", token, methods=["POST"])])


@contextmanager
def serve_mix_up(honest: str, target: str) -> Iterator[MixUp]:
    """Run a `MixUp` authorization server on loopback, aimed at the honest server `honest` and the resource `target`."""
    made: list[MixUp] = []

    def build(base_url: str) -> Starlette:
        made.append(MixUp(url=base_url, honest=honest, target=target))
        return made[0].app()

    with serve_built(build):
        yield made[0]
