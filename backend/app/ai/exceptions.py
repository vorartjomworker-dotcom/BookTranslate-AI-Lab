from __future__ import annotations

from typing import Any


class TranslationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        provider: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider = provider
        self.retryable = retryable
        self.retry_after = retry_after
        self.details = details or {}

    def __str__(self) -> str:
        base = self.message
        if self.provider:
            return f"[{self.provider}] {base}"
        return base


class ProviderConfigurationError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="provider_configuration_error", provider=provider, retryable=False, details=details)


class ProviderAuthenticationError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="provider_authentication_error", provider=provider, retryable=False, details=details)


class ProviderRateLimitError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, retry_after: float | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="provider_rate_limit_error", provider=provider, retryable=True, retry_after=retry_after, details=details)


class ProviderTimeoutError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="provider_timeout_error", provider=provider, retryable=True, details=details)


class ProviderUnavailableError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, retry_after: float | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="provider_unavailable_error", provider=provider, retryable=True, retry_after=retry_after, details=details)


class InvalidTranslationRequestError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="invalid_translation_request_error", provider=provider, retryable=False, details=details)


class InvalidTranslationResponseError(TranslationError):
    def __init__(self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="invalid_translation_response_error", provider=provider, retryable=False, details=details)
