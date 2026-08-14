from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from typing import Awaitable, Callable

from app.ai.base import TranslationProvider
from app.ai.exceptions import TranslationError, ProviderConfigurationError
from app.ai.registry import ProviderRegistry
from app.ai.types import TranslationRequest, TranslationResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(
        self,
        *,
        provider_factory: Callable[[TranslationRequest], TranslationProvider] | None = None,
        max_retries: int | None = None,
        sleep_fn: Callable[[float], Awaitable[None] | None] | None = None,
        settings_obj: object | None = None,
    ) -> None:
        self.settings = settings_obj or settings
        self.max_retries = int(max_retries if max_retries is not None else getattr(self.settings, "max_retries", 3))
        self.sleep_fn = sleep_fn or self._sleep
        self._provider_factory = provider_factory or self._default_provider_factory

    def _default_provider_factory(self, request: TranslationRequest) -> TranslationProvider:
        registry = ProviderRegistry(settings=self.settings)
        return registry.get_provider(request.provider)

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        await asyncio.sleep(seconds)

    def _build_retry_delay(self, attempt_number: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return float(retry_after)
        base = 0.5 * (2 ** max(0, attempt_number - 1))
        return min(base + random.uniform(0, 0.25), 5.0)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        payload = TranslationRequest.model_validate(request.model_dump())
        provider = self._provider_factory(payload)
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                started = time.perf_counter()
                result = await provider.translate(payload)
                latency_ms = int((time.perf_counter() - started) * 1000)
                if result.latency_ms == 0:
                    result.latency_ms = latency_ms
                logger.info(
                    "translation attempt provider=%s model=%s source=%s target=%s profile=%s attempt=%s latency_ms=%s",
                    result.provider,
                    result.model,
                    payload.source_language,
                    payload.target_language,
                    payload.profile,
                    attempt + 1,
                    result.latency_ms,
                )
                return result
            except asyncio.CancelledError:
                raise
            except TranslationError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                delay = self._build_retry_delay(attempt + 1, getattr(exc, "retry_after", None))
                logger.warning(
                    "translation retry provider=%s code=%s attempt=%s delay=%.2f",
                    exc.provider or payload.provider or provider.name,
                    exc.code,
                    attempt + 1,
                    delay,
                )
                sleep_result = self.sleep_fn(delay)
                if inspect.isawaitable(sleep_result):
                    await sleep_result
            except Exception as exc:  # pragma: no cover - safety wrap for unexpected non-translation errors
                last_error = TranslationError(
                    str(exc),
                    code="provider_unavailable_error",
                    provider=getattr(provider, "name", None),
                    retryable=True,
                )
                if attempt >= self.max_retries:
                    raise last_error
                delay = self._build_retry_delay(attempt + 1)
                sleep_result = self.sleep_fn(delay)
                if inspect.isawaitable(sleep_result):
                    await sleep_result

        if last_error is not None:
            raise last_error
        raise ProviderConfigurationError("Translation failed without a provider response.", provider=getattr(provider, "name", None))
