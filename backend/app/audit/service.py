from __future__ import annotations

import hashlib
import hmac
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AuditEvent


def audit_hash(namespace: str, value: str | None) -> str | None:
    """Return a stable HMAC digest suitable for correlating sensitive identifiers without storing them raw."""
    if not value:
        return None
    message = f"{namespace}:{value}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


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
            details=details,
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
