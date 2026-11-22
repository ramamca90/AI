import uuid

import pytest

from orderflow_common.config import Environment, EventBusBackend, ServiceSettings
from orderflow_common.errors import UnauthorizedError
from orderflow_common.security import TokenService

SECRET = "unit-test-secret-that-is-long-enough-123"


def make_settings(**overrides) -> ServiceSettings:
    return ServiceSettings(environment=Environment.TEST, jwt_secret=SECRET, **overrides)


def test_issue_and_verify_round_trip() -> None:
    tokens = TokenService(make_settings())
    user_id = str(uuid.uuid4())
    token, expires_in = tokens.issue(subject=user_id, email="a@b.com", roles=["customer"])

    principal = tokens.verify(token)

    assert principal.subject == user_id
    assert principal.has_role("customer")
    assert expires_in == 30 * 60


def test_rejects_token_for_other_audience() -> None:
    issuer = TokenService(make_settings(jwt_audience="someone-else"))
    verifier = TokenService(make_settings())
    token, _ = issuer.issue(subject="x", email=None, roles=[])

    with pytest.raises(UnauthorizedError):
        verifier.verify(token)


def test_rejects_expired_token() -> None:
    tokens = TokenService(make_settings(jwt_access_token_ttl_minutes=-5))
    token, _ = tokens.issue(subject="x", email=None, roles=[])

    with pytest.raises(UnauthorizedError, match="expired"):
        tokens.verify(token)


def test_rejects_tampered_token() -> None:
    tokens = TokenService(make_settings())
    token, _ = tokens.issue(subject="x", email=None, roles=[])

    with pytest.raises(UnauthorizedError):
        tokens.verify(token[:-2] + "xx")


def test_deployed_environment_requires_strong_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        ServiceSettings(environment=Environment.PROD, jwt_secret="short")


def test_service_bus_backend_requires_namespace() -> None:
    with pytest.raises(ValueError, match="SERVICEBUS"):
        make_settings(event_bus_backend=EventBusBackend.AZURE_SERVICE_BUS)
