from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

_URL_USERINFO_RE = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^\s/]+)@")
_BEARER_RE = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_NAMED_SECRET_RE = re.compile(
    r"(?P<key>\b(?:password|passwd|pwd|token|api[_-]?key|secret|authorization)\b)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^\s,;&'\"]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)
_MAX_SANITIZE_DEPTH = 4
_INSTALLED = False


def redact_sensitive_text(value: str) -> str:
    """Redact credential-like material from text without needing the secret value itself.

    This is a final logging safety net, not a substitute for avoiding sensitive data in logs.
    It deliberately understands URL userinfo and common credential assignment forms so a
    third-party exception cannot serialize a Redis/PostgreSQL/API credential verbatim.
    """
    text = str(value)
    text = _URL_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}<redacted>@", text)
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _NAMED_SECRET_RE.sub(
        lambda match: f"{match.group('key')}{match.group('separator')}<redacted>",
        text,
    )
    return text


def _sanitize_log_arg(value: Any, *, depth: int = 0) -> Any:
    if depth >= _MAX_SANITIZE_DEPTH:
        return "<redacted-complex-value>"
    if isinstance(value, BaseException):
        return f"{value.__class__.__name__}: {redact_sensitive_text(str(value))}"
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {
            _sanitize_log_arg(key, depth=depth + 1): _sanitize_log_arg(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_sanitize_log_arg(item, depth=depth + 1) for item in value)
    if isinstance(value, list):
        return [_sanitize_log_arg(item, depth=depth + 1) for item in value]
    return value


def _safe_log_record_factory(previous_factory: Any):
    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)
        if record.args:
            record.args = _sanitize_log_arg(record.args)

        if record.exc_info is not None and record.exc_info[1] is not None:
            original_exception = record.exc_info[1]
            safe_exception = RuntimeError(
                f"{original_exception.__class__.__name__}: "
                f"{redact_sensitive_text(str(original_exception))}"
            )
            record.exc_info = (RuntimeError, safe_exception, record.exc_info[2])
            record.exc_text = None
        return record

    setattr(factory, "_booktranslate_secret_redaction", True)
    return factory


def install_log_redaction() -> None:
    """Install the process-wide redacting LogRecord factory exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return

    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_booktranslate_secret_redaction", False):
        _INSTALLED = True
        return

    logging.setLogRecordFactory(_safe_log_record_factory(current_factory))
    _INSTALLED = True
