"""JWT issuing/verification and FastAPI auth dependencies.

identity-service issues tokens; every other service only verifies them
locally (no network hop per request). See docs/architecture.md for the
path to asymmetric keys / Microsoft Entra ID.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from orderflow_common.config import ServiceSettings
from orderflow_common.errors import ForbiddenError, UnauthorizedError


class Principal(BaseModel):
    subject: str
    email: str | None = None
    roles: list[str] = []

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(self.subject)

    def has_role(self, role: str) -> bool:
        return role in self.roles


class TokenService:
    def __init__(self, settings: ServiceSettings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl = timedelta(minutes=settings.jwt_access_token_ttl_minutes)

    def issue(self, *, subject: str, email: str | None, roles: list[str]) -> tuple[str, int]:
        now = datetime.now(UTC)
        payload = {
            "sub": subject,
            "email": email,
            "roles": roles,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "nbf": now,
            "exp": now + self._ttl,
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, int(self._ttl.total_seconds())

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=10,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthorizedError("Invalid token") from exc
        return Principal(
            subject=claims["sub"], email=claims.get("email"), roles=claims.get("roles") or []
        )


_bearer = HTTPBearer(
    auto_error=False, description="JWT access token from identity-service POST /v1/auth/token"
)


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")
    token_service: TokenService = request.app.state.token_service
    principal = token_service.verify(credentials.credentials)
    structlog.contextvars.bind_contextvars(user_id=principal.subject)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_role(role: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: `Depends(require_role("admin"))`."""

    async def _dependency(principal: CurrentPrincipal) -> Principal:
        if not principal.has_role(role):
            raise ForbiddenError(f"Requires role '{role}'")
        return principal

    return _dependency
