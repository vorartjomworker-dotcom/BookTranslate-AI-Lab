from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.time import utc_now_naive


def test_utc_now_naive_returns_naive_datetime() -> None:
    value = utc_now_naive()

    assert isinstance(value, datetime)
    assert value.tzinfo is None


def test_utc_now_naive_matches_current_utc_within_tolerance() -> None:
    reference = datetime.now(UTC).replace(tzinfo=None)

    value = utc_now_naive()

    assert abs((value - reference).total_seconds()) < 5


def test_benchmark_run_id_pattern_still_matches_after_utcnow_replacement() -> None:
    pattern = re.compile(r"^bench-\d{14}-\d{4}$")
    sample = f"bench-{utc_now_naive().strftime('%Y%m%d%H%M%S')}-1234"

    assert pattern.match(sample)


def test_no_deprecated_utcnow_calls_in_backend_app_source() -> None:
    # Only the deprecated `datetime.utcnow()` call is disallowed; the project-local
    # `_utcnow()` wrapper helpers (which delegate to `utc_now_naive()`) are fine.
    # `app/core/time.py` itself is excluded: it only mentions the deprecated API by
    # name in its module docstring, it never calls it.
    app_root = Path(__file__).resolve().parent.parent / "app"
    time_helper_path = app_root / "core" / "time.py"
    offenders = [
        f"{path}: {line.strip()}"
        for path in app_root.rglob("*.py")
        if path != time_helper_path
        for line in path.read_text(encoding="utf-8").splitlines()
        if "datetime.utcnow(" in line
    ]

    assert not offenders, f"Found deprecated datetime.utcnow() usage: {offenders}"
