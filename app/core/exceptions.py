"""Application-wide exception hierarchy."""

from __future__ import annotations

from fastapi import HTTPException, status


class NexaError(Exception):
    """Base error for all NEXA application errors."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail or message
        super().__init__(message)


class NotFoundError(NexaError):
    pass


class ConflictError(NexaError):
    pass


class AuthenticationError(NexaError):
    pass


class AuthorizationError(NexaError):
    pass


class ValidationError(NexaError):
    pass


class IntegrationError(NexaError):
    """External integration failure."""

    def __init__(self, message: str, provider: str, detail: str | None = None) -> None:
        self.provider = provider
        super().__init__(message, detail)


class IntegrationNotConfiguredError(IntegrationError):
    pass


class TokenExpiredError(IntegrationError):
    pass


class AIError(NexaError):
    pass


class ToolExecutionError(NexaError):
    pass


class ApprovalRequiredError(NexaError):
    """Raised when an action requires explicit user approval."""

    def __init__(self, plan_id: str, message: str = "Action requires approval") -> None:
        self.plan_id = plan_id
        super().__init__(message)


# --- HTTP exception factories ---


def http_not_found(detail: str = "Resource not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def http_conflict(detail: str = "Resource already exists") -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def http_unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def http_forbidden(detail: str = "Insufficient permissions") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def http_bad_request(detail: str = "Bad request") -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def http_service_unavailable(detail: str = "Service temporarily unavailable") -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
