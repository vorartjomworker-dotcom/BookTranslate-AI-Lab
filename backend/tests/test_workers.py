"""Tests for workers module."""

import pytest
import importlib


def test_translator_worker_import() -> None:
    """Test that translator_worker module can be imported."""
    try:
        from app.workers import translator_worker
        assert translator_worker is not None
    except ImportError as e:
        pytest.fail(f"Failed to import translator_worker: {e}")


def test_translator_worker_class_exists() -> None:
    """Test that TranslatorWorker class exists."""
    from app.workers.translator_worker import TranslatorWorker
    assert TranslatorWorker is not None


def test_translator_worker_methods() -> None:
    """Test that TranslatorWorker has required methods."""
    from app.workers.translator_worker import TranslatorWorker

    required_methods = [
        "connect",
        "disconnect",
        "run",
        "main",
        "process_translation_job",
    ]

    for method in required_methods:
        assert hasattr(TranslatorWorker, method), f"Missing method: {method}"


def test_translator_worker_instantiation() -> None:
    """Test that TranslatorWorker can be instantiated."""
    from app.workers.translator_worker import TranslatorWorker

    worker = TranslatorWorker()
    assert worker is not None
    assert worker.should_exit is False


def test_translation_job_model_import() -> None:
    """Test that the durable translation job model is available."""
    from app.models import TranslationJob

    assert TranslationJob is not None


@pytest.mark.asyncio
async def test_translator_worker_processes_job_metadata() -> None:
    """Test worker job processing returns clear metadata for a tracked job."""
    from app.workers.translator_worker import TranslatorWorker

    worker = TranslatorWorker()
    result = await worker.process_translation_job(segment_id=1, job_id=99)

    assert result is not None
    assert isinstance(result, dict)
    assert result["segment_id"] == 1
    assert result["job_id"] == 99
    assert result["status"] in {"queued", "running", "completed", "failed"}
