import pytest

from app.ai.exceptions import InvalidTranslationResponseError, ProviderAuthenticationError, ProviderRateLimitError, ProviderTimeoutError
from app.ai.openai_provider import OpenAIProvider
from app.ai.types import TranslationRequest


@pytest.mark.asyncio
async def test_openai_provider_success():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    return type(
                        "Resp",
                        (),
                        {
                            "choices": [type("Choice", (), {"message": type("Message", (), {"content": "Привет"})()})()],
                            "usage": type("Usage", (), {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33})(),
                            "model": "gpt-4o-mini",
                        },
                    )()

    provider = OpenAIProvider(client_factory=lambda: FakeClient(), api_key="test-key", model="gpt-4o-mini")
    request = TranslationRequest(text="Hello", source_language="en", target_language="ru")
    result = await provider.translate(request)
    assert result.translated_text == "Привет"
    assert result.total_tokens == 33


@pytest.mark.asyncio
async def test_openai_provider_handles_auth_error():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise Exception("401 Unauthorized")

    provider = OpenAIProvider(client_factory=lambda: FakeClient(), api_key="bad-key", model="gpt-4o-mini")
    with pytest.raises(ProviderAuthenticationError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))


@pytest.mark.asyncio
async def test_openai_provider_handles_timeout():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise TimeoutError("slow")

    provider = OpenAIProvider(client_factory=lambda: FakeClient(), api_key="test-key", model="gpt-4o-mini")
    with pytest.raises(ProviderTimeoutError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))


@pytest.mark.asyncio
async def test_openai_provider_rejects_empty_response():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    return type("Resp", (), {"choices": [], "usage": None, "model": "gpt-4o-mini"})()

    provider = OpenAIProvider(client_factory=lambda: FakeClient(), api_key="test-key", model="gpt-4o-mini")
    with pytest.raises(InvalidTranslationResponseError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))
