"""Protect the shop's server with OAuth, then follow its 401 to the authorization server, as a client does. The point
rests on the challenge's error line and on the PKCE methods line; the asserts check the rest of the chain."""
from urllib.parse import urlsplit

import httpx2
from mcp.server.auth.settings import AuthSettings

from lib import auth_server, http_mcp, shop_tools


def protected(issuer: str):
    def build(base_url: str):                                   # the server must know its own URL: the resource
        settings = AuthSettings(issuer_url=issuer, resource_server_url=base_url + "/mcp",
                                required_scopes=["orders:read", "stock:read"], validate_token_resource=True)
        verifier = auth_server.JwtVerifier(issuer)
        return shop_tools.create_server(version="0.8.0", auth=settings, token_verifier=verifier).streamable_http_app()
    return build


with auth_server.serve() as issuer, auth_server.serve_built(protected(issuer.url)) as base_url:  # the socket opens before the app is built, so the app knows its URL
    first = http_mcp.post(base_url + "/mcp", "tools/list")                     # no token
    print("status:", first.status_code)
    # [7:] drops the scheme, "Bearer ", which is 7 characters; the values that follow are quoted
    challenge = dict(part.split("=", 1) for part in first.headers["www-authenticate"][7:].split(", "))
    print("challenge parameters:", ", ".join(challenge))
    print("challenge error:", challenge["error"].strip('"'))
    metadata_url = challenge["resource_metadata"].strip('"')
    print("resource metadata path:", urlsplit(metadata_url).path)
    resource = httpx2.get(metadata_url).json()
    assert resource["resource"] == base_url + "/mcp"                            # RFC 9728: the endpoint's own URL
    print("authorization servers:", len(resource["authorization_servers"]))
    print("scopes_supported:", " ".join(resource["scopes_supported"]))
    found = resource["authorization_servers"][0]                                # the one server the metadata lists
    metadata = httpx2.get(found + "/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == found                                          # RFC 8414: the URL it was fetched from
    print("code_challenge_methods_supported:", metadata["code_challenge_methods_supported"])
    assert metadata["client_id_metadata_document_supported"]                    # the server advertises metadata documents
    assert metadata["authorization_response_iss_parameter_supported"]           # and iss on every authorization response
