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

    def __init__(self, token: str, *, principal_id: str = "local-operator") -> None:
        if not token or not token.strip():
            raise ValueError("API bearer token must be configured")
        if not principal_id or not principal_id.strip():
            raise ValueError("Principal identity must be non-empty")
        self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._principal_id = principal_id

    def authenticate(self, authorization: str | None) -> AuthenticatedPrincipal | None:
        if not authorization:
            return None
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential:
            return None
        supplied_digest = hashlib.sha256(credential.encode("utf-8")).digest()
        if not hmac.compare_digest(self._token_digest, supplied_digest):
            return None
        return AuthenticatedPrincipal(principal_id=self._principal_id)
