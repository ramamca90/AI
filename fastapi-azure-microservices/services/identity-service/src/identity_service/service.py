import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from identity_service.models import User
from identity_service.passwords import hash_password, verify_password
from identity_service.repository import UserRepository
from identity_service.schemas import LoginRequest, RegisterRequest, TokenResponse
from orderflow_common.errors import ConflictError, NotFoundError, UnauthorizedError
from orderflow_common.events import Event, EventBus
from orderflow_common.events.contracts import EventTypes, UserRegisteredData
from orderflow_common.logging import get_logger
from orderflow_common.security import TokenService

logger = get_logger(__name__)


class IdentityService:
    def __init__(
        self, session: AsyncSession, event_bus: EventBus, tokens: TokenService, source: str
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._bus = event_bus
        self._tokens = tokens
        self._source = source

    async def register(self, request: RegisterRequest) -> User:
        email = request.email.lower()
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists")

        user = User(
            id=uuid.uuid4(),
            email=email,
            full_name=request.full_name.strip(),
            password_hash=await hash_password(request.password.get_secret_value()),
            roles=["customer"],
        )
        self._users.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:  # concurrent registration with same email
            await self._session.rollback()
            raise ConflictError("An account with this email already exists") from exc

        logger.info("user_registered", user_id=str(user.id))
        await self._publish_best_effort(
            Event(
                type=EventTypes.USER_REGISTERED,
                source=self._source,
                subject=str(user.id),
                data=UserRegisteredData(
                    user_id=user.id, email=user.email, full_name=user.full_name
                ).model_dump(mode="json"),
            )
        )
        return user

    async def authenticate(self, request: LoginRequest) -> TokenResponse:
        user = await self._users.get_by_email(request.email)
        password_ok = await verify_password(
            user.password_hash if user else None, request.password.get_secret_value()
        )
        if user is None or not password_ok or not user.is_active:
            logger.info("login_failed")
            raise UnauthorizedError("Invalid email or password")

        token, expires_in = self._tokens.issue(
            subject=str(user.id), email=user.email, roles=list(user.roles)
        )
        logger.info("login_succeeded", user_id=str(user.id))
        return TokenResponse(access_token=token, expires_in=expires_in)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def _publish_best_effort(self, event: Event) -> None:
        # The welcome notification is non-critical, so a direct publish is an
        # acceptable trade-off here. orders-service shows the stronger
        # transactional-outbox pattern for events that must never be lost.
        try:
            await self._bus.publish(event)
        except Exception:
            logger.exception("event_publish_failed", event_type=event.type)
