from __future__ import annotations

from app.document.segmentation import TextSegmenter


def test_segmenter_is_deterministic_and_removes_empty_segments() -> None:
    text = (
        "This is the first sentence of a long paragraph. "
        "This is the second sentence of a long paragraph. "
        "This is the third sentence of a long paragraph. "
    ) * 20
    segmenter = TextSegmenter(target_chars=200, hard_limit=300)

    first = segmenter.segment(text)
    second = segmenter.segment(text)

    assert first == second
    assert first
    assert all(segment.strip() for segment in first)
    assert all(len(segment) <= segmenter.hard_limit for segment in first)


def test_segmenter_preserves_order_and_respects_hard_limit() -> None:
    text = "Alpha beta gamma delta. " * 80
    segmenter = TextSegmenter(target_chars=80, hard_limit=120)

    segments = segmenter.segment(text)

    assert segments
    assert all(len(segment) <= segmenter.hard_limit for segment in segments)
    reconstructed = " ".join(segments)
    assert "Alpha" in reconstructed
    assert "delta" in reconstructed


def test_segmenter_handles_empty_input() -> None:
    segmenter = TextSegmenter(target_chars=200, hard_limit=400)
    assert segmenter.segment("\n\n   \n") == []
