"""Conversations router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserId, DbSession
from app.core.exceptions import NotFoundError, http_not_found
from app.modules.conversations.schemas import (
    ChatTurnResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageRequest,
    MessageResponse,
)
from app.modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    user_id: CurrentUserId,
    db: DbSession,
) -> ConversationResponse:
    svc = ConversationService(db)
    conv = await svc.create(user_id, body.title)
    return ConversationResponse.model_validate(conv)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user_id: CurrentUserId,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> ConversationListResponse:
    svc = ConversationService(db)
    items, total = await svc.list(user_id, page, size)
    return ConversationListResponse(
        items=[ConversationResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
) -> ConversationDetailResponse:
    svc = ConversationService(db)
    try:
        conv = await svc.get(conversation_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.message)
    return ConversationDetailResponse.model_validate(conv)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED, response_model=ChatTurnResponse)
async def add_message(
    conversation_id: UUID,
    body: MessageRequest,
    user_id: CurrentUserId,
    db: DbSession,
) -> ChatTurnResponse:
    svc = ConversationService(db)
    try:
        msg, orch_res = await svc.add_user_message_and_respond(conversation_id, user_id, body.content)
    except NotFoundError as exc:
        raise http_not_found(exc.message)

    return ChatTurnResponse(
        message=MessageResponse.model_validate(msg),
        action_plan_id=orch_res.action_plan_id,
        clarification_needed=orch_res.clarification_needed,
        follow_up_questions=orch_res.follow_up_questions,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(
    conversation_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
) -> None:
    svc = ConversationService(db)
    try:
        await svc.archive(conversation_id, user_id)
    except NotFoundError as exc:
        raise http_not_found(exc.message)
