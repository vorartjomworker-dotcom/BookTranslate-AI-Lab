from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai.types import TranslationRequest, TranslationResult


class TranslationProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def translate(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError

    def validate_configuration(self) -> None:
        return None
