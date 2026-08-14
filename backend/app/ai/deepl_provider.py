from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.ai.base import TranslationProvider
from app.ai.exceptions import (
    InvalidTranslationRequestError,
    InvalidTranslationResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.types import TranslationRequest, TranslationResult

logger = logging.getLogger(__name__)


class DeepLProvider(TranslationProvider):
    def __init__(
        self,
        *,
        settings: Any | None = None,
        api_key: str | None = None,
        use_pro: bool | None = None,
        timeout: float | int | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self._api_key = api_key or (getattr(settings, "deepl_api_key", "") if settings is not None else "")
        self.use_pro = bool(use_pro if use_pro is not None else (getattr(settings, "deepl_use_pro", False) if settings is not None else False))
        self.timeout = float(timeout if timeout is not None else (getattr(settings, "translation_timeout", 30) if settings is not None else 30))
        self._client_factory = client_factory or httpx.AsyncClient

    @property
    def name(self) -> str:
        return "deepl"

    @property
    def base_url(self) -> str:
        if self.use_pro:
            return "https://api.deepl.com/v2/translate"
        return "https://api-free.deepl.com/v2/translate"

    def validate_configuration(self) -> None:
        if not self._api_key:
            raise ProviderConfigurationError("DeepL API key is not configured.", provider=self.name)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        if not self._api_key and self.settings is not None:
            self._api_key = getattr(self.settings, "deepl_api_key", "")
        self.validate_configuration()

        if request.glossary:
            raise InvalidTranslationRequestError(
                "DeepL glossary is not supported for this request.",
                provider=self.name,
                details={"glossary_entries": len(request.glossary)},
            )

        started = time.perf_counter()
        source_lang = request.source_language.upper()
        target_lang = request.target_language.upper()

        payload: dict[str, Any] = {
            "text": [request.text],
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        if request.context:
            payload["context"] = request.context.strip()

        async with self._client_factory(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self.base_url,
                    headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
                    data=payload,
                )
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError("DeepL request timed out.", provider=self.name) from exc
            except (httpx.HTTPError, OSError) as exc:
                raise ProviderUnavailableError("DeepL service is unavailable.", provider=self.name) from exc

        if response.status_code == 401 or response.status_code == 403:
            raise ProviderAuthenticationError("DeepL authentication failed.", provider=self.name)
        if response.status_code == 429:
            raise ProviderRateLimitError("DeepL rate limit exceeded.", provider=self.name)
        if response.status_code == 456:
            raise ProviderQuotaExceededError("DeepL quota exhausted.", provider=self.name)
        if response.status_code >= 500:
            raise ProviderUnavailableError("DeepL service is unavailable.", provider=self.name)
        if response.status_code == 400:
            raise InvalidTranslationRequestError("DeepL rejected the translation request.", provider=self.name)

        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise InvalidTranslationResponseError("DeepL returned invalid JSON.", provider=self.name) from exc

        translations = body.get("translations") or []
        if not translations or not translations[0].get("text"):
            raise InvalidTranslationResponseError("DeepL returned no translated text.", provider=self.name)

        translated_text = str(translations[0]["text"]).strip()
        if not translated_text:
            raise InvalidTranslationResponseError("DeepL returned empty translated text.", provider=self.name)

        logger.debug("DeepL translation completed status=%s provider=%s", response.status_code, self.name)
        return TranslationResult(
            translated_text=translated_text,
            provider=self.name,
            model="deepl",
            source_language=request.source_language,
            target_language=request.target_language,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            confidence=None,
            finish_reason="ok",
        )
