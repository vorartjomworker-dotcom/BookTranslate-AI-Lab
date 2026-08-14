from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx
from openai import AsyncOpenAI
from openai import AuthenticationError as OpenAIAuthenticationError
from openai import APIConnectionError as OpenAIAPIConnectionError
from openai import APIStatusError as OpenAIAPIStatusError
from openai import RateLimitError as OpenAIRateLimitError

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


class OpenAIProvider(TranslationProvider):
    def __init__(
        self,
        *,
        settings: Any | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | int | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._api_key = api_key or (getattr(settings, "openai_api_key", "") if settings is not None else "")
        self.model = model or (getattr(settings, "openai_model", "gpt-4o") if settings is not None else "gpt-4o")
        self.base_url = base_url or (getattr(settings, "openai_base_url", None) if settings is not None else None)
        self.timeout = float(timeout if timeout is not None else (getattr(settings, "translation_timeout", 30) if settings is not None else 30))
        self._client: Any | None = None
        self._client_factory = client_factory or self._create_client

    @property
    def name(self) -> str:
        return "openai"

    def _create_client(self) -> Any:
        return AsyncOpenAI(api_key=self._api_key or None, base_url=self.base_url, timeout=self.timeout)

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def validate_configuration(self) -> None:
        configured_key = self._api_key or (getattr(self.settings, "openai_api_key", "") if self.settings is not None else "")
        if not configured_key:
            raise ProviderConfigurationError("OpenAI API key is not configured.", provider=self.name)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self._api_key and self.settings is not None:
            self._api_key = getattr(self.settings, "openai_api_key", "")
        self.validate_configuration()

        model_name = request.model or self.model
        prompt = build_prompt_from_request(request)
        started = time.perf_counter()

        try:
            response = await self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a precise translation engine."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        except OpenAIAuthenticationError as exc:
            raise ProviderAuthenticationError("OpenAI authentication failed.", provider=self.name) from exc
        except OpenAIRateLimitError as exc:
            raise ProviderRateLimitError("OpenAI rate limit exceeded.", provider=self.name, retry_after=getattr(exc, "retry_after", None)) from exc
        except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeoutError("OpenAI request timed out.", provider=self.name) from exc
        except OpenAIAPIConnectionError as exc:
            raise ProviderUnavailableError("OpenAI service is unavailable.", provider=self.name) from exc
        except OpenAIAPIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status == 401:
                raise ProviderAuthenticationError("OpenAI authentication failed.", provider=self.name) from exc
            if status == 429:
                raise ProviderRateLimitError("OpenAI rate limit exceeded.", provider=self.name, retry_after=getattr(exc, "retry_after", None)) from exc
            raise ProviderUnavailableError("OpenAI request failed.", provider=self.name) from exc
        except Exception as exc:  # pragma: no cover - safety fallback for unknown SDK exceptions
            text = str(exc).lower()
            if "401" in text or "unauthorized" in text or "forbidden" in text:
                raise ProviderAuthenticationError("OpenAI authentication failed.", provider=self.name) from exc
            if "429" in text or "rate limit" in text:
                raise ProviderRateLimitError("OpenAI rate limit exceeded.", provider=self.name) from exc
            if "timeout" in text or "timed out" in text:
                raise ProviderTimeoutError("OpenAI request timed out.", provider=self.name) from exc
            raise ProviderUnavailableError("OpenAI provider error.", provider=self.name) from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise InvalidTranslationResponseError("OpenAI returned an empty response.", provider=self.name)

        choice = choices[0]
        message = getattr(choice, "message", None)
        raw_content = getattr(message, "content", None) if message is not None else None

        if isinstance(raw_content, list):
            text_parts = []
            for item in raw_content:
                if getattr(item, "type", None) == "text":
                    text_parts.append(getattr(item, "text", ""))
            translated_text = "".join(text_parts)
        elif isinstance(raw_content, str):
            translated_text = raw_content
        else:
            translated_text = ""

        if not translated_text or not translated_text.strip():
            raise InvalidTranslationResponseError("OpenAI returned empty translated text.", provider=self.name)

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or input_tokens + output_tokens)
        finish_reason = getattr(choice, "finish_reason", None)

        return TranslationResult(
            translated_text=translated_text.strip(),
            provider=self.name,
            model=str(model_name),
            source_language=request.source_language,
            target_language=request.target_language,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            confidence=None,
            finish_reason=str(finish_reason) if finish_reason is not None else None,
        )
