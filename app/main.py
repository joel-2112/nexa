"""FastAPI application entrypoint for NEXA."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1.health import router as health_router
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import (
    ApprovalRequiredError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    IntegrationError,
    IntegrationNotConfiguredError,
    NexaError,
    NotFoundError,
    TokenExpiredError,
    ValidationError,
)
from app.core.logging import configure_logging, get_logger
from app.db.session import engine

# Configure structured logging
configure_logging()
logger = get_logger(__name__)

# Rate limiter setup
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_ENABLED else [],
    enabled=settings.RATE_LIMIT_ENABLED,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "nexa_startup",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        timezone=settings.DEFAULT_TIMEZONE,
    )
    if settings.telegram_configured:
        try:
            from app.integrations.telegram.bot import TelegramBotService

            bot_svc = TelegramBotService()
            await bot_svc.set_bot_commands()
            logger.info("telegram_bot_commands_registered")
        except Exception as e:
            logger.warning("telegram_bot_commands_registration_failed", error=str(e))
    yield
    logger.info("nexa_shutdown")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="NEXA – AI-Powered Personal Executive Assistant Backend API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Attach state limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "Not Found", "detail": exc.detail},
    )


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "Conflict", "detail": exc.detail},
    )


@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
        content={"error": "Unauthorized", "detail": exc.detail},
    )


@app.exception_handler(AuthorizationError)
async def forbidden_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": "Forbidden", "detail": exc.detail},
    )


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "Validation Error", "detail": exc.detail},
    )


@app.exception_handler(ApprovalRequiredError)
async def approval_required_handler(request: Request, exc: ApprovalRequiredError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Approval Required",
            "detail": exc.detail,
            "action_plan_id": exc.plan_id,
        },
    )


@app.exception_handler(IntegrationNotConfiguredError)
async def integration_not_configured_handler(request: Request, exc: IntegrationNotConfiguredError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "Integration Not Configured", "provider": exc.provider, "detail": exc.detail},
    )


@app.exception_handler(TokenExpiredError)
async def token_expired_handler(request: Request, exc: TokenExpiredError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": "Integration Token Expired", "provider": exc.provider, "detail": exc.detail},
    )


@app.exception_handler(IntegrationError)
async def integration_error_handler(request: Request, exc: IntegrationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"error": "Integration Error", "provider": exc.provider, "detail": exc.detail},
    )


@app.exception_handler(NexaError)
async def nexa_base_error_handler(request: Request, exc: NexaError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Application Error", "detail": exc.detail},
    )


# Top-level health probes (for Docker health checks)
app.include_router(health_router)

# Mount API v1
app.include_router(api_v1_router)
