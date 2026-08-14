import json

import httpx
import pytest

from app.ai.deepl_provider import DeepLProvider
from app.ai.exceptions import (
    InvalidTranslationRequestError,
    InvalidTranslationResponseError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.types import TranslationRequest


class FakeAsyncClient:
    def __init__(self, *, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.closed = False
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True

    async def post(self, url, headers=None, data=None):
        self.calls.append({"url": url, "headers": headers, "data": data})
        if self.exc is not None:
            raise self.exc
        return self.response


@pytest.mark.asyncio
async def test_deepl_provider_success():
    response = httpx.Response(
        200,
        json={"translations": [{"text": "Привет"}]},
    )
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=response))
    result = await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))
    assert result.translated_text == "Привет"
    assert result.provider == "deepl"
    assert result.model == "deepl"


@pytest.mark.asyncio
async def test_deepl_provider_uses_free_and_pro_endpoints_and_request_fields():
    response = httpx.Response(200, json={"translations": [{"text": "Привет"}]})
    free_client = FakeAsyncClient(response=response)
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: free_client)
    await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    assert provider.base_url == "https://api-free.deepl.com/v2/translate"
    assert free_client.calls[0]["headers"]["Authorization"] == "DeepL-Auth-Key key"
    assert free_client.calls[0]["data"]["source_lang"] == "EN"
    assert free_client.calls[0]["data"]["target_lang"] == "RU"
    assert "Translate only the provided text" in free_client.calls[0]["data"]["text"][0]

    pro_client = FakeAsyncClient(response=response)
    pro_provider = DeepLProvider(api_key="key", use_pro=True, client_factory=lambda **kwargs: pro_client)
    await pro_provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    assert pro_provider.base_url == "https://api.deepl.com/v2/translate"
    assert pro_client.calls[0]["headers"]["Authorization"] == "DeepL-Auth-Key key"
    assert pro_client.calls[0]["data"]["source_lang"] == "EN"
    assert pro_client.calls[0]["data"]["target_lang"] == "RU"


@pytest.mark.asyncio
async def test_deepl_provider_handles_empty_translations_missing_text_invalid_json_and_400():
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(200, json={"translations": []})))
    with pytest.raises(InvalidTranslationResponseError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(200, json={"translations": [{"other": "x"}]})))
    with pytest.raises(InvalidTranslationResponseError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(200, text="not-json")))
    with pytest.raises(InvalidTranslationResponseError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(400, json={"message": "bad request"})))
    with pytest.raises(InvalidTranslationRequestError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))


@pytest.mark.asyncio
async def test_deepl_provider_auth_rate_limit_and_errors():
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(403, json={"message": "forbidden"})))
    with pytest.raises(ProviderAuthenticationError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(429, json={"message": "rate limited"})))
    with pytest.raises(ProviderRateLimitError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    for code in (456, 500, 502, 503):
        provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(code, json={"message": "error"})))
        if code == 456:
            with pytest.raises(InvalidTranslationResponseError):
                await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))
        else:
            with pytest.raises(ProviderUnavailableError):
                await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))


@pytest.mark.asyncio
async def test_deepl_provider_timeouts_and_network_errors():
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(exc=httpx.ReadTimeout("read timeout")))
    with pytest.raises(ProviderTimeoutError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(exc=httpx.ConnectError("connect error")))
    with pytest.raises(ProviderUnavailableError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: FakeAsyncClient(exc=OSError("network fail")))
    with pytest.raises(ProviderUnavailableError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))


@pytest.mark.asyncio
async def test_deepl_provider_validates_missing_key_and_hides_all_secrets():
    provider = DeepLProvider(api_key="", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(200, json={"translations": [{"text": "x"}]})))
    with pytest.raises(ProviderConfigurationError):
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))

    provider = DeepLProvider(api_key="super-secret-key", client_factory=lambda **kwargs: FakeAsyncClient(response=httpx.Response(403, json={"message": "forbidden"})))
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        await provider.translate(TranslationRequest(text="Hello", source_language="en", target_language="ru"))
    text = str(exc_info.value)
    assert "super-secret-key" not in text


def test_deepl_provider_client_lifecycle_and_no_system_prompt():
    response = httpx.Response(200, json={"translations": [{"text": "Привет"}]})
    client = FakeAsyncClient(response=response)
    provider = DeepLProvider(api_key="key", client_factory=lambda **kwargs: client)
    assert provider._client_factory is not None
    provider.validate_configuration()
    assert provider.name == "deepl"

    sent = client.calls
    assert sent == []
    assert not client.closed
