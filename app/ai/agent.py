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
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.OPENAI_MODEL
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.timeout = settings.OPENAI_TIMEOUT
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if not self.api_key:
            raise AIError("OpenAI API key is not configured. Please supply OPENAI_API_KEY in .env.")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                timeout=float(self.timeout),
            )
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
        except RateLimitError as exc:
            logger.error("openai_rate_limited", error=str(exc))
            raise AIError("OpenAI rate limit exceeded. Please retry in a few moments.") from exc
        except APITimeoutError as exc:
            logger.error("openai_timeout", error=str(exc))
            raise AIError("AI request timed out. Please try again.") from exc
        except APIError as exc:
            logger.error("openai_api_error", error=str(exc))
            raise AIError(f"OpenAI service error: {exc.message}") from exc
        except Exception as exc:
            logger.error("openai_unexpected_error", error=str(exc))
            raise AIError(f"Failed to communicate with AI agent: {exc}") from exc
