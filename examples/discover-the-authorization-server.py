"""Protect the shop's server with OAuth, then follow its 401 to the authorization server, as a client does."""
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


with auth_server.serve() as issuer, auth_server.serve_built(protected(issuer.url)) as base_url:
    first = http_mcp.post(base_url + "/mcp", "tools/list")                     # no token
    print("status:", first.status_code)
    challenge = dict(part.split("=", 1) for part in first.headers["www-authenticate"][7:].split(", "))
    print("challenge parameters:", ", ".join(challenge))
    print("challenge error:", challenge["error"].strip('"'))
    metadata_url = challenge["resource_metadata"].strip('"')
    print("resource metadata path:", urlsplit(metadata_url).path)
    resource = httpx2.get(metadata_url).json()
    print("resource is the endpoint's URL:", resource["resource"] == base_url + "/mcp")
    print("authorization servers:", len(resource["authorization_servers"]))
    print("scopes_supported:", " ".join(resource["scopes_supported"]))
    found = resource["authorization_servers"][0]
    metadata = httpx2.get(found + "/.well-known/oauth-authorization-server").json()
    print("metadata issuer is the URL it came from:", metadata["issuer"] == found)
    for key in ("code_challenge_methods_supported", "client_id_metadata_document_supported",
                "authorization_response_iss_parameter_supported"):
        print(f"{key}:", metadata[key])
