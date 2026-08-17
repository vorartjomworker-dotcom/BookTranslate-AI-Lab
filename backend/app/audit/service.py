from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.log_safety import is_sensitive_field_name, redact_sensitive_text
from app.models import AuditEvent


_MAX_AUDIT_DETAIL_DEPTH = 4
_MAX_AUDIT_DETAIL_ITEMS = 50
_MAX_AUDIT_DETAIL_STRING_LENGTH = 1000
_MAX_AUDIT_DETAIL_KEY_LENGTH = 100


def audit_hash(namespace: str, value: str | None) -> str | None:
    """Return a stable HMAC digest suitable for correlating sensitive identifiers without storing them raw."""
    if not value:
        return None
    message = f"{namespace}:{value}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _sanitize_audit_detail(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded JSON-safe audit value with credential-like text redacted.

    Audit details are durable security records. They must remain useful for operators
    without becoming a long-lived sink for request text, provider credentials, or
    secret-bearing exception fragments.
    """
    if depth >= _MAX_AUDIT_DETAIL_DEPTH:
        return "<redacted-complex-value>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_sensitive_text(value)[:_MAX_AUDIT_DETAIL_STRING_LENGTH]
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_AUDIT_DETAIL_ITEMS:
                sanitized["<truncated>"] = True
                break
            safe_key = redact_sensitive_text(str(key))[:_MAX_AUDIT_DETAIL_KEY_LENGTH]
            sanitized[safe_key] = (
                "<redacted>"
                if is_sensitive_field_name(key)
                else _sanitize_audit_detail(item, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        sanitized_items = [
            _sanitize_audit_detail(item, depth=depth + 1)
            for item in value[:_MAX_AUDIT_DETAIL_ITEMS]
        ]
        if len(value) > _MAX_AUDIT_DETAIL_ITEMS:
            sanitized_items.append("<truncated>")
        return sanitized_items
    return f"<{value.__class__.__name__}>"


def sanitize_audit_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize and bound durable audit details before they reach the database."""
    if details is None:
        return None
    sanitized = _sanitize_audit_detail(details)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        outcome: str,
        actor_user_id: int | None = None,
        target_type: str | None = None,
        target_id: str | int | None = None,
        subject_hash: str | None = None,
        source_hash: str | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
        flush: bool = True,
    ) -> AuditEvent:
        event = AuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            outcome=outcome,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            subject_hash=subject_hash,
            source_hash=source_hash,
            request_id=request_id,
            details=sanitize_audit_details(details),
        )
        self.session.add(event)
        if flush:
            await self.session.flush()
        return event

    async def list_events(self, *, page: int, page_size: int) -> tuple[list[AuditEvent], int]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size
        items = list(
            (
                await self.session.execute(
                    select(AuditEvent)
                    .order_by(desc(AuditEvent.id))
                    .offset(offset)
                    .limit(page_size)
                )
            ).scalars()
        )
        total = int((await self.session.execute(select(func.count(AuditEvent.id)))).scalar_one())
        return items, total
