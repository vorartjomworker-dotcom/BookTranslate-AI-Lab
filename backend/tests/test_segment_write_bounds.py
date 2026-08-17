from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.types import MAX_TRANSLATED_TEXT_CHARS
from app.schemas.segment import (
    MAX_SEGMENT_SOURCE_CHARS,
    SegmentCreate,
    SegmentRead,
    SegmentTranslationUpdate,
    SegmentUpdate,
)


def test_segment_create_accepts_text_at_write_bounds() -> None:
    payload = SegmentCreate(
        segment_number=1,
        original_text="s" * MAX_SEGMENT_SOURCE_CHARS,
        translated_text="t" * MAX_TRANSLATED_TEXT_CHARS,
    )

    assert len(payload.original_text) == MAX_SEGMENT_SOURCE_CHARS
    assert len(payload.translated_text or "") == MAX_TRANSLATED_TEXT_CHARS


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SegmentCreate(
            segment_number=1,
            original_text="s" * (MAX_SEGMENT_SOURCE_CHARS + 1),
        ),
        lambda: SegmentUpdate(
            original_text="s" * (MAX_SEGMENT_SOURCE_CHARS + 1),
        ),
        lambda: SegmentCreate(
            segment_number=1,
            original_text="source",
            translated_text="t" * (MAX_TRANSLATED_TEXT_CHARS + 1),
        ),
        lambda: SegmentUpdate(
            translated_text="t" * (MAX_TRANSLATED_TEXT_CHARS + 1),
        ),
        lambda: SegmentTranslationUpdate(
            translated_text="t" * (MAX_TRANSLATED_TEXT_CHARS + 1),
        ),
    ],
)
def test_segment_write_schemas_reject_oversized_text(factory) -> None:
    with pytest.raises(ValidationError):
        factory()


def test_segment_patch_defaults_remain_unset_friendly() -> None:
    payload = SegmentUpdate()

    assert payload.model_dump(exclude_unset=True) == {}


def test_segment_read_remains_compatible_with_legacy_oversized_rows() -> None:
    payload = SegmentRead(
        id=1,
        chapter_id=1,
        segment_number=1,
        original_text="s" * (MAX_SEGMENT_SOURCE_CHARS + 1),
        translated_text="t" * (MAX_TRANSLATED_TEXT_CHARS + 1),
    )

    assert len(payload.original_text) == MAX_SEGMENT_SOURCE_CHARS + 1
    assert len(payload.translated_text or "") == MAX_TRANSLATED_TEXT_CHARS + 1
