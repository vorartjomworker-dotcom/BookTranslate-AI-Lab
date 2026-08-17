from __future__ import annotations

from app.models.translation_job import MAX_TRANSLATION_JOB_ERROR_MESSAGE_LENGTH, TranslationJob
from app.schemas.translation_job import TranslationJobRead


def _failed_job(error_message: str | None) -> TranslationJob:
    return TranslationJob(
        segment_id=1,
        provider="openai",
        model="gpt-4o",
        status="failed",
        attempt=1,
        max_attempts=3,
        error_code="worker_failed",
        error_message=error_message,
    )


def test_translation_job_redacts_credentials_on_initial_assignment() -> None:
    redis_password = "redis-job-secret"
    bearer_token = "bearer-job-secret"
    api_key = "sk-job-secret"
    raw = (
        f"redis://default:{redis_password}@cache.example:6379/0 "
        f"Authorization: Bearer {bearer_token} api_key={api_key}"
    )

    job = _failed_job(raw)

    assert job.error_message is not None
    assert "<redacted>" in job.error_message
    for secret in (redis_password, bearer_token, api_key):
        assert secret not in job.error_message


def test_translation_job_redacts_credentials_on_worker_style_reassignment() -> None:
    job = _failed_job("initial failure")
    database_password = "database-driver-secret"
    query_token = "query-driver-secret"

    job.error_message = (
        f"asyncpg failed for postgresql://book:{database_password}@db.example/booktranslate"
        f"?token={query_token}"
    )

    assert job.error_message is not None
    assert database_password not in job.error_message
    assert query_token not in job.error_message
    assert "<redacted>" in job.error_message


def test_translation_job_error_message_is_bounded_and_blank_becomes_none() -> None:
    job = _failed_job("x" * (MAX_TRANSLATION_JOB_ERROR_MESSAGE_LENGTH + 500))
    assert job.error_message is not None
    assert len(job.error_message) == MAX_TRANSLATION_JOB_ERROR_MESSAGE_LENGTH

    job.error_message = "   "
    assert job.error_message is None

    job.error_message = None
    assert job.error_message is None


def test_translation_job_read_sanitizes_legacy_raw_error_message() -> None:
    legacy_password = "legacy-db-secret"
    legacy_bearer = "legacy-bearer-secret"
    job = _failed_job(None)
    job.id = 42

    # Simulate a row written before the ORM validator existed. Direct __dict__ assignment
    # intentionally bypasses the model validator so this test exercises the API read guard.
    job.__dict__["error_message"] = (
        f"postgresql://book:{legacy_password}@db.example/booktranslate "
        f"Authorization: Bearer {legacy_bearer} "
        + ("x" * (MAX_TRANSLATION_JOB_ERROR_MESSAGE_LENGTH + 500))
    )

    response = TranslationJobRead.model_validate(job)

    assert response.error_message is not None
    assert "<redacted>" in response.error_message
    assert legacy_password not in response.error_message
    assert legacy_bearer not in response.error_message
    assert len(response.error_message) <= MAX_TRANSLATION_JOB_ERROR_MESSAGE_LENGTH
