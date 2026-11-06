"""API v1 master router aggregating all modules."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.integrations.telegram.router import router as telegram_webhook_router
from app.modules.action_plans.router import router as action_plans_router
from app.modules.auth.router import router as auth_router
from app.modules.calendar.router import router as calendar_router
from app.modules.contacts.router import router as contacts_router
from app.modules.conversations.router import router as conversations_router
from app.modules.integrations.router import router as integrations_router
from app.modules.notifications.router import router as notifications_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as users_router

api_v1_router = APIRouter(prefix="/api/v1")

# Mount health endpoints both at root and v1 for convenience
api_v1_router.include_router(health_router)

# Mount business module routers
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(conversations_router)
api_v1_router.include_router(tasks_router)
api_v1_router.include_router(calendar_router)
api_v1_router.include_router(contacts_router)
api_v1_router.include_router(action_plans_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(integrations_router)
api_v1_router.include_router(telegram_webhook_router)
