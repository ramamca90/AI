from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from identity_service.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from identity_service.service import IdentityService
from orderflow_common.db import get_session
from orderflow_common.security import CurrentPrincipal

router = APIRouter(prefix="/v1")


def get_identity_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> IdentityService:
    state = request.app.state
    return IdentityService(
        session, state.event_bus, state.token_service, source=state.settings.service_name
    )


Service = Annotated[IdentityService, Depends(get_identity_service)]


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    summary="Create a customer account",
)
async def register(body: RegisterRequest, service: Service) -> UserResponse:
    return UserResponse.model_validate(await service.register(body))


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["auth"],
    summary="Exchange credentials for a JWT",
)
async def login(body: LoginRequest, service: Service) -> TokenResponse:
    return await service.authenticate(body)


@router.get("/users/me", response_model=UserResponse, tags=["users"], summary="Current user")
async def me(principal: CurrentPrincipal, service: Service) -> UserResponse:
    return UserResponse.model_validate(await service.get_user(principal.user_id))
