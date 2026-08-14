from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True)
class TranslationQueueMessage:
    job_id: int
    segment_id: int
    provider: str | None = None
    model: str | None = None
    attempt: int = 0
    max_attempts: int = 3

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "TranslationQueueMessage":
        raw = dict(payload or {})
        job_id = int(raw.get("job_id") or 0)
        segment_id = int(raw.get("segment_id") or 0)
        provider = raw.get("provider")
        model = raw.get("model")
        attempt = int(raw.get("attempt") or 0)
        max_attempts = int(raw.get("max_attempts") or 3)
        return cls(job_id=job_id, segment_id=segment_id, provider=provider, model=model, attempt=attempt, max_attempts=max_attempts)

    def to_payload(self) -> dict[str, str]:
        data: dict[str, str] = {
            "job_id": str(self.job_id),
            "segment_id": str(self.segment_id),
            "attempt": str(self.attempt),
            "max_attempts": str(self.max_attempts),
        }
        if self.provider:
            data["provider"] = self.provider
        if self.model:
            data["model"] = self.model
        return data
