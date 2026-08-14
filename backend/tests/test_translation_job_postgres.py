from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models import Segment, TranslationJob


@pytest.mark.asyncio
async def test_translation_job_table_and_active_constraint(async_session_factory):
    async with async_session_factory() as session:
        segment = Segment(chapter_id=1, segment_number=1, original_text="hello", status="pending")
        session.add(segment)
        await session.commit()
        await session.refresh(segment)

        job = TranslationJob(segment_id=segment.id, provider="openai", status="pending_enqueue")
        session.add(job)
        await session.commit()

        row = await session.execute(text("SELECT count(*) FROM translation_jobs WHERE segment_id = :segment_id"), {"segment_id": segment.id})
        assert row.scalar() == 1
