from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.dependencies.db import get_db
from app.main import app
from app.models import Book, Chapter, Segment, TranslationJob
from app.quality.service import QualityAssuranceService


@pytest.fixture
def quality_client(editor_client, async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        client.headers.update(editor_client.headers)
        yield client
    app.dependency_overrides.clear()


def _seed_book(async_session_factory, *, title: str = "Book QA", chapter_number: int = 1):
    async def _create():
        async with async_session_factory() as session:
            book = Book(
                title=title,
                author="Tester",
                file_path="/tmp/quality.pdf",
                file_type="pdf",
                language="en",
            )
            chapter = Chapter(book=book, chapter_number=chapter_number, title="Intro", content="Body", status="translated")
            segment = Segment(
                chapter=chapter,
                segment_number=1,
                original_text="Hello world.",
                translated_text="Hola mundo.",
                status="translated",
            )
            session.add_all([book, chapter, segment])
            await session.commit()
            await session.refresh(book)
            await session.refresh(chapter)
            await session.refresh(segment)
            return book, chapter, segment

    return asyncio.run(_create())


async def _write_segment_report(async_session_factory, *, segment_id: int, source_text: str, translated_text: str):
    async with async_session_factory() as session:
        service = QualityAssuranceService(session)
        report = await service.evaluate_segment(
            segment_id=segment_id,
            source_text=source_text,
            translated_text=translated_text,
            provider="openai",
            model="gpt-4o",
        )
        await session.commit()
        return report


def test_quality_api_get_report_by_id(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    report = asyncio.run(
        _write_segment_report(async_session_factory, segment_id=segment.id, source_text="Hello world.", translated_text="Hola mundo.")
    )

    response = quality_client.get(f"/api/v1/quality-reports/{report.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == report.id
    assert body["segment_id"] == segment.id


def test_quality_api_get_missing_report_returns_404(quality_client):
    response = quality_client.get("/api/v1/quality-reports/9999")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_quality_api_get_segment_quality_report(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    report = asyncio.run(
        _write_segment_report(async_session_factory, segment_id=segment.id, source_text="Hello world.", translated_text="Hola mundo.")
    )

    response = quality_client.get(f"/api/v1/segments/{segment.id}/quality-report")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == report.id


def test_quality_api_missing_segment_quality_report_returns_404(quality_client):
    response = quality_client.get("/api/v1/segments/7777/quality-report")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_quality_api_missing_report_for_existing_segment_returns_404(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    response = quality_client.get(f"/api/v1/segments/{segment.id}/quality-report")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_quality_api_stale_report_is_hidden_after_manual_edit(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    report = asyncio.run(
        _write_segment_report(
            async_session_factory,
            segment_id=segment.id,
            source_text="Hello world.",
            translated_text="Hola mundo.",
        )
    )

    response = quality_client.patch(
        f"/api/v1/segments/{segment.id}/translation",
        json={"translated_text": "Hola mundo actualizado."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["qa_status"] == "stale"
    assert response.json()["qa_score"] == 0

    current = quality_client.get(f"/api/v1/segments/{segment.id}/quality-report")
    assert current.status_code == 404, current.text
    assert current.json()["code"] == "not_found"
    assert report.segment_id == segment.id


def test_quality_api_source_edit_marks_qa_stale_and_hides_old_report(quality_client, async_session_factory):
    book, _, segment = _seed_book(async_session_factory)
    asyncio.run(
        _write_segment_report(
            async_session_factory,
            segment_id=segment.id,
            source_text="Hello world.",
            translated_text="Hola mundo.",
        )
    )

    response = quality_client.patch(
        f"/api/v1/segments/{segment.id}",
        json={"original_text": "Hello updated world."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["qa_status"] == "stale"
    assert response.json()["qa_score"] == 0

    current = quality_client.get(f"/api/v1/segments/{segment.id}/quality-report")
    assert current.status_code == 404, current.text

    summary = quality_client.get(f"/api/v1/books/{book.id}/quality-summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["stale_reports"] == 1
    assert summary.json()["checked_segments"] == 0


def test_quality_api_source_checksum_rejects_old_report_even_if_legacy_status_is_not_stale(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    report = asyncio.run(
        _write_segment_report(
            async_session_factory,
            segment_id=segment.id,
            source_text="Hello world.",
            translated_text="Hola mundo.",
        )
    )

    async def _change_source_without_stale_flag():
        async with async_session_factory() as session:
            stored = await session.get(Segment, segment.id)
            assert stored is not None
            stored.original_text = "Changed source without legacy stale flag."
            stored.qa_status = report.status
            await session.commit()

    asyncio.run(_change_source_without_stale_flag())

    current = quality_client.get(f"/api/v1/segments/{segment.id}/quality-report")
    assert current.status_code == 404, current.text
    assert current.json()["code"] == "not_found"


def test_quality_api_book_summary_for_empty_book(quality_client, async_session_factory):
    async def _make_book():
        async with async_session_factory() as session:
            book = Book(title="Empty book", author="A", file_path="/tmp/empty.pdf", file_type="pdf", language="en")
            session.add(book)
            await session.commit()
            await session.refresh(book)
            return book

    book = asyncio.run(_make_book())
    response = quality_client.get(f"/api/v1/books/{book.id}/quality-summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_segments"] == 0
    assert body["checked_segments"] == 0
    assert body["average_score"] is None


def test_quality_api_book_summary_with_status_breakdown_and_average(quality_client, async_session_factory):
    async def _make_data():
        async with async_session_factory() as session:
            book = Book(title="Summary book", author="Tester", file_path="/tmp/summary.pdf", file_type="pdf", language="en")
            chapter = Chapter(book=book, chapter_number=1, title="One", content="Body", status="translated")
            segment_a = Segment(chapter=chapter, segment_number=1, original_text="Alpha.", translated_text="Álpha.", status="translated")
            segment_b = Segment(chapter=chapter, segment_number=2, original_text="Beta.", translated_text="Béta.", status="translated")
            segment_c = Segment(chapter=chapter, segment_number=3, original_text="Gamma.", translated_text="Gama.", status="translated")
            session.add_all([book, chapter, segment_a, segment_b, segment_c])
            await session.commit()
            await session.refresh(book)
            await session.refresh(chapter)
            await session.refresh(segment_a)
            await session.refresh(segment_b)
            await session.refresh(segment_c)

            service = QualityAssuranceService(session)
            await service.evaluate_segment(segment_id=segment_a.id, source_text="Alpha.", translated_text="Álpha.")
            await service.evaluate_segment(segment_id=segment_b.id, source_text="Beta.", translated_text="Béta.")
            await service.evaluate_segment(segment_id=segment_c.id, source_text="Gamma.", translated_text="Gama.")
            await session.commit()
            return book.id

    book_id = asyncio.run(_make_data())
    response = quality_client.get(f"/api/v1/books/{book_id}/quality-summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_segments"] == 3
    assert body["checked_segments"] == 3
    assert body["passed"] + body["needs_review"] + body["failed"] == 3
    assert body["average_score"] is not None
    assert body["average_score"] >= 0


def test_quality_api_segment_quality_check_deterministic_mode(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    response = quality_client.post(
        f"/api/v1/segments/{segment.id}/quality-check",
        json={"mode": "deterministic"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segment_id"] == segment.id
    assert body["mode"] == "deterministic"


def test_quality_api_segment_quality_check_full_mode(quality_client, async_session_factory, monkeypatch):
    _, _, segment = _seed_book(async_session_factory)
    monkeypatch.setattr("app.quality.service.settings.quality_ai_enabled", True, raising=False)

    class FakeAI:
        async def evaluate(self, **kwargs):
            return []

    monkeypatch.setattr("app.api.v1.quality.AIQualityEvaluator", FakeAI)

    response = quality_client.post(
        f"/api/v1/segments/{segment.id}/quality-check",
        json={"mode": "full"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["segment_id"] == segment.id
    assert body["mode"] == "full"


def test_quality_api_segment_quality_check_full_mode_without_ai_returns_deterministic(quality_client, async_session_factory, monkeypatch):
    _, _, segment = _seed_book(async_session_factory)
    monkeypatch.setattr("app.quality.service.settings.quality_ai_enabled", False, raising=False)
    response = quality_client.post(
        f"/api/v1/segments/{segment.id}/quality-check",
        json={"mode": "full"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "full"
    assert body["ai_score"] is None


def test_quality_api_rejects_unknown_quality_mode(quality_client):
    response = quality_client.post("/api/v1/segments/1/quality-check", json={"mode": "unknown"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_quality_api_missing_segment_for_quality_check_returns_404(quality_client):
    response = quality_client.post("/api/v1/segments/777/quality-check", json={"mode": "deterministic"})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_quality_api_check_segment_quality_is_idempotent(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)
    first = quality_client.post(f"/api/v1/segments/{segment.id}/quality-check", json={"mode": "deterministic"})
    second = quality_client.post(f"/api/v1/segments/{segment.id}/quality-check", json={"mode": "deterministic"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_quality_api_legacy_aliases_delegate_to_canonical_routes(quality_client, async_session_factory):
    _, _, segment = _seed_book(async_session_factory)

    async def _seed_report():
        async with async_session_factory() as session:
            service = QualityAssuranceService(session)
            report = await service.evaluate_segment(
                segment_id=segment.id,
                source_text="Hello world.",
                translated_text="Hola mundo.",
                provider="openai",
                model="gpt-4o",
            )
            await session.commit()
            return report

    asyncio.run(_seed_report())
    legacy_get = quality_client.get(f"/api/v1/segments/{segment.id}/quality")
    assert legacy_get.status_code == 200, legacy_get.text

    job = TranslationJob(segment_id=segment.id, provider="openai", model="gpt-4o", status="completed", attempt=1, max_attempts=3)

    async def _save_job():
        async with async_session_factory() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)

    asyncio.run(_save_job())
    legacy_post = quality_client.post(f"/api/v1/translation-jobs/{job.id}/quality")
    assert legacy_post.status_code == 200, legacy_post.text
    assert legacy_post.json()["segment_id"] == segment.id


def test_quality_api_exposes_request_id_in_error_envelope(quality_client):
    response = quality_client.get("/api/v1/quality-reports/90999")
    assert response.status_code == 404
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "traceback" not in str(body).lower()
    assert "api_key" not in str(body).lower()
    assert "internal" not in str(body).lower()
