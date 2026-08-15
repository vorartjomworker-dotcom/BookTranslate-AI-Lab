from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.dependencies.db import get_db
from app.main import app
from app.models import Book, Chapter, Segment


@pytest.fixture
def chapter_segment_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_chapter_segments_are_isolated_by_chapter(chapter_segment_client, async_session_factory):
    async def seed() -> tuple[int, int]:
        async with async_session_factory() as session:
            book = Book(title="Isolation", author="Test", file_path="isolation.epub", file_type="epub", language="en")
            first = Chapter(book=book, chapter_number=1, title="First", content="First", status="segmented")
            second = Chapter(book=book, chapter_number=2, title="Second", content="Second", status="segmented")
            session.add_all([book, first, second])
            await session.flush()
            session.add_all([
                Segment(chapter_id=first.id, segment_number=1, original_text="Only first", status="pending"),
                Segment(chapter_id=second.id, segment_number=1, original_text="Only second", status="pending"),
            ])
            await session.commit()
            return first.id, second.id

    first_id, second_id = asyncio.run(seed())
    response = chapter_segment_client.get(f"/api/v1/chapters/{first_id}/segments")

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["original_text"] for item in response.json()["items"]] == ["Only first"]
    assert second_id != first_id