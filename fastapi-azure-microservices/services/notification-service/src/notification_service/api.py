import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notification_service.models import Notification
from notification_service.schemas import NotificationPage, NotificationResponse
from orderflow_common.db import get_session, utcnow
from orderflow_common.errors import NotFoundError
from orderflow_common.security import CurrentPrincipal

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=NotificationPage, summary="My notifications, newest first")
async def list_notifications(
    principal: CurrentPrincipal,
    session: Session,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationPage:
    mine = select(Notification).where(Notification.user_id == principal.user_id)
    filtered = mine.where(Notification.read_at.is_(None)) if unread_only else mine
    total = await session.scalar(select(func.count()).select_from(filtered.subquery()))
    unread = await session.scalar(
        select(func.count()).select_from(mine.where(Notification.read_at.is_(None)).subquery())
    )
    rows = await session.scalars(
        filtered.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    )
    return NotificationPage(
        items=[NotificationResponse.model_validate(n) for n in rows],
        total=int(total or 0),
        unread=int(unread or 0),
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse, summary="Mark read")
async def mark_read(
    notification_id: uuid.UUID, principal: CurrentPrincipal, session: Session
) -> NotificationResponse:
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != principal.user_id:
        raise NotFoundError("Notification not found")
    if notification.read_at is None:
        notification.read_at = utcnow()
        await session.commit()
    return NotificationResponse.model_validate(notification)
