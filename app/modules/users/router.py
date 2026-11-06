"""Users module router."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import http_not_found
from app.modules.auth.repository import UserRepository
from app.modules.users.schemas import UpdateUserRequest, UserProfileResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(user_id: CurrentUserId, db: DbSession) -> UserProfileResponse:
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise http_not_found("User not found")
    return UserProfileResponse.model_validate(user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    body: UpdateUserRequest,
    user_id: CurrentUserId,
    db: DbSession,
) -> UserProfileResponse:
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise http_not_found("User not found")

    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        user = await repo.update(user, **update_data)
    return UserProfileResponse.model_validate(user)
