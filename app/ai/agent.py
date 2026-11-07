"""Low-level OpenAI client wrapper with retry, timeout, and tool calling."""

from __future__ import annotations

from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.core.exceptions import AIError
from app.core.logging import get_logger

logger = get_logger(__name__)


class NexaAgent:
    def __init__(self) -> None:
        if settings.is_gemini_active:
            self.api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY
            self.model = settings.GEMINI_MODEL or "gemini-1.5-flash"
            self.base_url: str | None = "https://generativelanguage.googleapis.com/v1beta/openai/"
            self.provider = "gemini"
        else:
            self.api_key = settings.OPENAI_API_KEY
            self.model = settings.OPENAI_MODEL
            self.base_url = settings.OPENAI_BASE_URL
            self.provider = "openai"

        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.timeout = settings.OPENAI_TIMEOUT
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if not self.api_key:
            raise AIError("No LLM API key configured. Please set GEMINI_API_KEY or OPENAI_API_KEY in .env.")
        if self._client is None:
            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": float(self.timeout),
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any:
        """Call OpenAI chat completion with error handling."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        try:
            return await self.client.chat.completions.create(**kwargs)
        except (RateLimitError, APIError) as exc:
            # If Gemini model is experiencing temporary high demand (503) or rate limit, fallback to gemini-3.5-flash
            err_msg = str(exc)
            if self.provider == "gemini" and ("503" in err_msg or "high demand" in err_msg.lower() or "overloaded" in err_msg.lower()):
                fallback_model = "gemini-3.5-flash"
                if kwargs.get("model") != fallback_model:
                    logger.warning("gemini_high_demand_fallback", requested=kwargs.get("model"), fallback=fallback_model)
                    kwargs["model"] = fallback_model
                    try:
                        return await self.client.chat.completions.create(**kwargs)
                    except Exception as fb_exc:
                        logger.error("gemini_fallback_failed", error=str(fb_exc))
            logger.error("ai_service_error", error=err_msg)
            raise AIError(f"AI service error: {err_msg}") from exc
        except APITimeoutError as exc:
            logger.error("openai_timeout", error=str(exc))
            raise AIError("AI request timed out. Please try again.") from exc
        except Exception as exc:
            logger.error("openai_unexpected_error", error=str(exc))
            raise AIError(f"Failed to communicate with AI agent: {exc}") from exc
