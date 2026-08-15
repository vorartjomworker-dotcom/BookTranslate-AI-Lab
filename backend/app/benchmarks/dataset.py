from __future__ import annotations

import hashlib
import json

from app.benchmarks.types import BenchmarkCase, BenchmarkDataset

BENCHMARK_DATASET_NAME = "technical_translation"
TECHNICAL_TRANSLATION_DATASET_VERSION = "2026.08.15"
DATASET_DESCRIPTION = "Synthetic technical translation benchmark covering deterministic edge cases for QA and provider comparison."
DATASET_SOURCE = "Synthetic examples created for reproducible benchmarking; not copied from copyrighted book chapters or personal text."

DATASET_CASES: list[dict[str, object]] = [
    {
        "case_id": "case_001",
        "category": "technical",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "The deployment pipeline runs in parallel and stores artifacts in a secure object storage bucket.",
        "reference_translation": "Конвейер развертывания работает параллельно и сохраняет артефакты в безопасном объектном хранилище.",
        "protected_tokens": ["deployment", "pipeline", "object storage"],
        "metadata": {"section": "overview", "expected_behavior": "general technical translation"},
    },
    {
        "case_id": "case_002",
        "category": "terminology",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "The scheduler retries failed jobs with exponential backoff and marks the task as degraded.",
        "reference_translation": "Планировщик повторяет сбои задач с экспоненциальной задержкой и помечает задачу как деградированную.",
        "protected_tokens": ["scheduler", "backoff", "degraded"],
        "metadata": {"section": "operations", "expected_behavior": "terminology preservation"},
    },
    {
        "case_id": "case_003",
        "category": "numbers_units",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "The server handles 1,250 requests per minute at 95.6% utilization across 3 nodes and uses 12.5 GB RAM.",
        "reference_translation": "Сервер обрабатывает 1250 запросов в минуту при загрузке 95,6% на 3 узлах и использует 12,5 ГБ оперативной памяти.",
        "protected_tokens": ["1,250", "95.6%", "3", "12.5 GB"],
        "metadata": {"section": "metrics", "expected_behavior": "numbers and units"},
    },
    {
        "case_id": "case_004",
        "category": "placeholders",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "The request for {user_id} failed with status {status_code} after {retry_count} retries.",
        "reference_translation": "Запрос для {user_id} завершился с ошибкой со статусом {status_code} после {retry_count} повторов.",
        "protected_tokens": ["{user_id}", "{status_code}", "{retry_count}"],
        "metadata": {"section": "errors", "expected_behavior": "placeholder fidelity"},
    },
    {
        "case_id": "case_005",
        "category": "urls",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "Open https://docs.example.com/guide/api?lang=en and review the docs at www.example.org/blog/metrics.",
        "reference_translation": "Откройте https://docs.example.com/guide/api?lang=en и просмотрите документацию на сайте www.example.org/blog/metrics.",
        "protected_tokens": ["https://docs.example.com/guide/api?lang=en", "www.example.org/blog/metrics"],
        "metadata": {"section": "links", "expected_behavior": "url preservation"},
    },
    {
        "case_id": "case_006",
        "category": "markdown",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "# Release notes\n\n- Added caching for hot paths\n- Fixed retry logic\n- Updated the API contract\n",
        "reference_translation": "# Примечания к релизу\n\n- Добавлено кэширование горячих путей\n- Исправлена логика повторов\n- Обновлён контракт API\n",
        "protected_tokens": ["# Release notes", "- Added caching", "- Fixed retry logic"],
        "metadata": {"section": "release", "expected_behavior": "markdown bullets and heading"},
    },
    {
        "case_id": "case_007",
        "category": "code",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "def fetch_user(user_id: str) -> dict:\n    payload = {\"id\": user_id, \"active\": True}\n    return payload\n",
        "reference_translation": "def fetch_user(user_id: str) -> dict:\n    payload = {\"id\": user_id, \"active\": True}\n    return payload\n",
        "protected_tokens": ["def fetch_user", "payload = {\"id\": user_id, \"active\": True}", "return payload"],
        "metadata": {"section": "code", "expected_behavior": "code block must stay stable"},
    },
    {
        "case_id": "case_008",
        "category": "tables",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "| Environment | CPU | Memory | Status |\n| --- | --- | --- | --- |\n| prod | 8 vCPU | 32 GB | healthy |\n| stage | 4 vCPU | 16 GB | ready |",
        "reference_translation": "| Окружение | CPU | Память | Статус |\n| --- | --- | --- | --- |\n| prod | 8 vCPU | 32 ГБ | здорово |\n| stage | 4 vCPU | 16 ГБ | готово |",
        "protected_tokens": ["| Environment | CPU | Memory | Status |", "8 vCPU", "32 GB"],
        "metadata": {"section": "tables", "expected_behavior": "structured text formatting"},
    },
    {
        "case_id": "case_009",
        "category": "long_context",
        "source_language": "en",
        "target_language": "ru",
        "source_text": "The system reads the event stream from Kafka, validates every message against the JSON schema, deduplicates repeated IDs, writes to the warehouse, and emits a success metric to Prometheus while retrying transient network failures with exponential backoff. This posture keeps latency low and prevents data loss during burst periods.",
        "reference_translation": "Система читает поток событий из Kafka, проверяет каждое сообщение по JSON-схеме, удаляет повторяющиеся идентификаторы, записывает данные в хранилище и отправляет метрику успешного выполнения в Prometheus, одновременно повторяя временные сетевые сбои с экспоненциальной задержкой. Такая схема сохраняет низкую задержку и предотвращает потерю данных во время всплесков нагрузки.",
        "protected_tokens": ["Kafka", "JSON schema", "Prometheus", "exponential backoff"],
        "metadata": {"section": "long_context", "expected_behavior": "long technical narrative"},
    },
]


def _canonicalize_dataset_cases(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for entry in entries:
        normalized.append(
            {
                "case_id": str(entry["case_id"]),
                "category": str(entry["category"]),
                "source_language": str(entry["source_language"]).lower(),
                "target_language": str(entry["target_language"]).lower(),
                "source_text": str(entry["source_text"]),
                "reference_translation": str(entry.get("reference_translation") or ""),
                "protected_tokens": sorted(str(token).strip() for token in list(entry.get("protected_tokens") or [])),
                "metadata": {str(k): v for k, v in dict(entry.get("metadata") or {}).items()},
            }
        )
    return sorted(normalized, key=lambda item: str(item["case_id"]))


def _compute_checksum(entries: list[dict[str, object]]) -> str:
    canonical = json.dumps(_canonicalize_dataset_cases(entries), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


TECHNICAL_TRANSLATION_DATASET_CHECKSUM = _compute_checksum(DATASET_CASES)


def load_dataset() -> BenchmarkDataset:
    cases = [BenchmarkCase.model_validate(item) for item in _canonicalize_dataset_cases(DATASET_CASES)]
    return BenchmarkDataset(
        name=BENCHMARK_DATASET_NAME,
        version=TECHNICAL_TRANSLATION_DATASET_VERSION,
        checksum=TECHNICAL_TRANSLATION_DATASET_CHECKSUM,
        description=DATASET_DESCRIPTION,
        source=DATASET_SOURCE,
        cases=cases,
    )
