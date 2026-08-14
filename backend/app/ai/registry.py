from __future__ import annotations

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.deepl_provider import DeepLProvider
from app.ai.exceptions import ProviderConfigurationError
from app.ai.openai_provider import OpenAIProvider


class ProviderRegistry:
    def __init__(self, settings: object | None = None) -> None:
        self.settings = settings
        self._providers: dict[str, object] = {}

    @property
    def default_provider(self) -> str:
        if self.settings is not None:
            return getattr(self.settings, "default_ai_provider", "openai")
        return "openai"

    def get_provider(self, provider: str | None = None) -> object:
        provider_name = (provider or self.default_provider).strip().lower()
        aliases = {
            "openai": "openai",
            "openai-compatible": "openai",
            "openai_compatible": "openai",
            "anthropic": "anthropic",
            "deepl": "deepl",
        }
        canonical = aliases.get(provider_name, provider_name)
        if canonical in self._providers:
            return self._providers[canonical]

        mapping = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
            "deepl": DeepLProvider,
        }
        factory = mapping.get(canonical)
        if factory is None:
            raise ProviderConfigurationError(f"Unsupported provider: {provider_name}", provider=provider_name)

        instance = factory(settings=self.settings)
        self._providers[canonical] = instance
        return instance
