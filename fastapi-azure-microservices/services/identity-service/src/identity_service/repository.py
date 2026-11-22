import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_service.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email.lower()))

    def add(self, user: User) -> None:
        self._session.add(user)
