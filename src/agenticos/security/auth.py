"""Local bearer-token authentication for single-operator deployments."""

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Server-derived identity attached to an authenticated request."""

    principal_id: str


class BearerTokenAuthenticator:
    """Authenticate one configured operator token without retaining plaintext."""

    def __init__(self, token: str) -> None:
        if not token or not token.strip():
            raise ValueError("API bearer token must be configured")
        self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal | None:
        if not authorization:
            return None
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential:
            return None
        supplied_digest = hashlib.sha256(credential.encode("utf-8")).digest()
        if not hmac.compare_digest(self._token_digest, supplied_digest):
            return None
        return AuthenticatedPrincipal(principal_id="local-operator")
