import pytest

from app.ai.exceptions import ProviderConfigurationError, ProviderRateLimitError
from app.ai.translation_service import TranslationService
from app.ai.types import TranslationRequest


class DummyProvider:
    def __init__(self, name="dummy"):
        self.name = name

    async def translate(self, request):
        return type(
            "Result",
            (),
            {
                "translated_text": "Привет",
                "provider": self.name,
                "model": "dummy-model",
                "source_language": request.source_language,
                "target_language": request.target_language,
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "latency_ms": 5,
                "confidence": 0.9,
                "finish_reason": "stop",
            },
        )()


@pytest.mark.asyncio
async def test_translation_service_success():
    service = TranslationService(provider_factory=lambda _request: DummyProvider("dummy"), max_retries=1)
    request = TranslationRequest(text="Hello", source_language="en", target_language="ru")
    result = await service.translate(request)
    assert result.translated_text == "Привет"
    assert result.provider == "dummy"


@pytest.mark.asyncio
async def test_translation_service_retries_on_retryable_error():
    attempts = {"count": 0}

    class RetryProvider:
        name = "retry"

        async def translate(self, request):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise ProviderRateLimitError("Rate limited", provider="retry")
            return type(
                "Result",
                (),
                {
                    "translated_text": "Привет",
                    "provider": "retry",
                    "model": "retry-model",
                    "source_language": request.source_language,
                    "target_language": request.target_language,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "latency_ms": 10,
                    "confidence": 0.8,
                    "finish_reason": "stop",
                },
            )()

    service = TranslationService(provider_factory=lambda _request: RetryProvider(), max_retries=2, sleep_fn=lambda _s: None)
    request = TranslationRequest(text="Hello", source_language="en", target_language="ru")
    result = await service.translate(request)
    assert result.translated_text == "Привет"
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_translation_service_does_not_retry_auth_error():
    class AuthProvider:
        name = "auth"

        async def translate(self, request):
            raise ProviderConfigurationError("bad key", provider="auth")

    service = TranslationService(provider_factory=lambda _request: AuthProvider(), max_retries=3)
    request = TranslationRequest(text="Hello", source_language="en", target_language="ru")
    with pytest.raises(ProviderConfigurationError):
        await service.translate(request)
