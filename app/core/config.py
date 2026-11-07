"""Central application configuration using Pydantic Settings v2."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_cors(v: Any) -> list[str]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return [i.strip() for i in v.split(",") if i.strip()]
    raise ValueError("CORS_ORIGINS must be a string or list")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_ENV: str = "development"
    APP_NAME: str = "NEXA"
    APP_VERSION: str = "0.1.0"
    APP_DEBUG: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    PORT: int | None = None
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(64))

    @model_validator(mode="after")
    def sync_port(self) -> Settings:
        if self.PORT is not None:
            self.APP_PORT = self.PORT
        return self

    # JWT
    JWT_SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(64))
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Encryption (Fernet key for OAuth tokens at rest)
    ENCRYPTION_KEY: str = ""

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "nexa"
    POSTGRES_USER: str = "nexa_user"
    POSTGRES_PASSWORD: str = "nexa_password"
    DATABASE_URL: str = ""

    @model_validator(mode="after")
    def build_database_url(self) -> Settings:
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        else:
            if self.DATABASE_URL.startswith("postgres://"):
                self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
            elif self.DATABASE_URL.startswith("postgresql://") and not self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = ""

    @model_validator(mode="after")
    def build_redis_url(self) -> Settings:
        if not self.REDIS_URL:
            if self.REDIS_PASSWORD:
                self.REDIS_URL = f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            else:
                self.REDIS_URL = f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return self

    # Celery
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"

    @model_validator(mode="after")
    def build_celery_urls(self) -> Settings:
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL.replace(f"/{self.REDIS_DB}", "/1")
        return self

    # AI / LLM Provider (Google Gemini is the default)
    LLM_PROVIDER: str = "gemini"  # "gemini" or "openai"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.2
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TIMEOUT: int = 60

    @property
    def is_gemini_active(self) -> bool:
        if self.LLM_PROVIDER.lower() == "openai" and self.OPENAI_API_KEY and not self.GEMINI_API_KEY:
            return False
        return True

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/google/callback"
    GOOGLE_SCOPES: str = (
        "openid,email,profile,"
        "https://www.googleapis.com/auth/calendar,"
        "https://www.googleapis.com/auth/gmail.send,"
        "https://www.googleapis.com/auth/tasks"
    )

    @property
    def google_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.GOOGLE_SCOPES.split(",") if s.strip()]

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""

    @property
    def telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN)

    # n8n
    N8N_BASE_URL: str = "http://localhost:5678"
    N8N_API_KEY: str = ""
    N8N_WEBHOOK_SECRET: str = ""
    N8N_WORKFLOW_CALENDAR_EVENT: str = ""
    N8N_WORKFLOW_SEND_EMAIL: str = ""
    N8N_WORKFLOW_SEND_REMINDER: str = ""

    @property
    def n8n_configured(self) -> bool:
        return bool(self.N8N_API_KEY)

    # CORS
    CORS_ORIGINS: str | list[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_FILE: str = ""

    # Timezone
    DEFAULT_TIMEZONE: str = "Africa/Addis_Ababa"

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
