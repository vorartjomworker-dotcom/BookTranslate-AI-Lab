"""Centralized UTC time helpers (avoids deprecated `datetime.utcnow()`)."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_naive() -> datetime:
    """Return the current UTC time as a naive datetime for legacy timezone-naive DB columns."""
    return datetime.now(UTC).replace(tzinfo=None)
