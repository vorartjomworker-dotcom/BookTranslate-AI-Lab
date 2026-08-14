import pytest

from app.ai.exceptions import ProviderConfigurationError
from app.ai.registry import ProviderRegistry


def test_default_provider_name():
    registry = ProviderRegistry()
    assert registry.default_provider == "openai"


def test_explicit_provider_resolution():
    registry = ProviderRegistry()
    provider = registry.get_provider("anthropic")
    assert provider.name == "anthropic"


def test_unknown_provider_raises_configuration_error():
    registry = ProviderRegistry()
    with pytest.raises(ProviderConfigurationError):
        registry.get_provider("unknown")


def test_registry_builds_lazy_provider_objects():
    registry = ProviderRegistry()
    provider = registry.get_provider("openai")
    assert provider is not None
    assert provider.name == "openai"
