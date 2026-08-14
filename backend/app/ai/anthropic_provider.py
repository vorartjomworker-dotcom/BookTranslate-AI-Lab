from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
from anthropic import AsyncAnthropic
from anthropic import AuthenticationError as AnthropicAuthenticationError
from anthropic import RateLimitError as AnthropicRateLimitError
from anthropic import APIConnectionError as AnthropicAPIConnectionError
from anthropic import APIStatusError as AnthropicAPIStatusError

from app.ai.base import TranslationProvider
from app.ai.exceptions import (
    InvalidTranslationResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.prompts import build_prompt_from_request
from app.ai.types import TranslationRequest, TranslationResult


class AnthropicProvider(TranslationProvider):
    def __init__(
        self,
        *,
        settings: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | int | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._api_key = api_key or (getattr(settings, "anthropic_api_key", "") if settings is not None else "")
        self.model = model or (getattr(settings, "anthropic_model", "claude-3-opus-20240229") if settings is not None else "claude-3-opus-20240229")
        self.timeout = float(timeout if timeout is not None else (getattr(settings, "translation_timeout", 30) if settings is not None else 30))
        self._client: Any | None = None
        self._client_factory = client_factory or self._create_client

    @property
    def name(self) -> str:
        return "anthropic"

    def _create_client(self) -> Any:
        return AsyncAnthropic(api_key=self._api_key or None, timeout=self.timeout)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def validate_configuration(self) -> None:
        configured_key = self._api_key or (getattr(self.settings, "anthropic_api_key", "") if self.settings is not None else "")
        if not configured_key:
            raise ProviderConfigurationError("Anthropic API key is not configured.", provider=self.name)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self._api_key and self.settings is not None:
            self._api_key = getattr(self.settings, "anthropic_api_key", "")
        self.validate_configuration()

        model_name = request.model or self.model
        prompt = build_prompt_from_request(request)
        started = time.perf_counter()

        try:
            response = await self.client.messages.create(
                model=model_name,
                max_tokens=2048,
                temperature=0.2,
                system="You are a precise translation engine.",
                messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            )
        except AnthropicAuthenticationError as exc:
            raise ProviderAuthenticationError("Anthropic authentication failed.", provider=self.name) from exc
        except AnthropicRateLimitError as exc:
            raise ProviderRateLimitError("Anthropic rate limit exceeded.", provider=self.name, retry_after=getattr(exc, "retry_after", None)) from exc
        except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeoutError("Anthropic request timed out.", provider=self.name) from exc
        except AnthropicAPIConnectionError as exc:
            raise ProviderUnavailableError("Anthropic service is unavailable.", provider=self.name) from exc
        except AnthropicAPIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                raise ProviderAuthenticationError("Anthropic authentication failed.", provider=self.name) from exc
            if status == 429:
                raise ProviderRateLimitError("Anthropic rate limit exceeded.", provider=self.name, retry_after=getattr(exc, "retry_after", None)) from exc
            raise ProviderUnavailableError("Anthropic request failed.", provider=self.name) from exc
        except Exception as exc:  # pragma: no cover - safety fallback for unknown SDK exceptions
            text = str(exc).lower()
            if "401" in text or "unauthorized" in text or "forbidden" in text:
                raise ProviderAuthenticationError("Anthropic authentication failed.", provider=self.name) from exc
            if "429" in text or "rate limit" in text:
                raise ProviderRateLimitError("Anthropic rate limit exceeded.", provider=self.name) from exc
            if "timeout" in text or "timed out" in text:
                raise ProviderTimeoutError("Anthropic request timed out.", provider=self.name) from exc
            raise ProviderUnavailableError("Anthropic provider error.", provider=self.name) from exc

        content = getattr(response, "content", None) or []
        if not content:
            raise InvalidTranslationResponseError("Anthropic returned empty content.", provider=self.name)

        text_parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        translated_text = "".join(text_parts).strip()
        if not translated_text:
            raise InvalidTranslationResponseError("Anthropic returned empty translated text.", provider=self.name)

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))

        return TranslationResult(
            translated_text=translated_text,
            provider=self.name,
            model=str(model_name),
            source_language=request.source_language,
            target_language=request.target_language,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            confidence=None,
            finish_reason=getattr(response, "stop_reason", None),
        )
