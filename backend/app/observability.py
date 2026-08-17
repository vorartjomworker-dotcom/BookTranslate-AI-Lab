from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings


_HTTP_LOGGER_NAME = "booktranslate.http"
_http_logger = logging.getLogger(_HTTP_LOGGER_NAME)
_http_logger.propagate = False

if not _http_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _http_logger.addHandler(handler)

_http_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))


def build_http_request_event(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> dict[str, Any]:
    """Build a deliberately small request event without headers, body, query string, or client IP."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "http_request",
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(max(duration_ms, 0.0), 3),
    }


def log_http_request(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Emit one JSON line and never let observability failure affect request handling."""
    try:
        payload = build_http_request_event(
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if status_code >= 500:
            _http_logger.error(message)
        elif status_code >= 400:
            _http_logger.warning(message)
        else:
            _http_logger.info(message)
    except Exception:
        # Logging must never turn a valid application response into an error.
        return
