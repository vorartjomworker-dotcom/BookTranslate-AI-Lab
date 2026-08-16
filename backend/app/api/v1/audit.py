from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditService
from app.core.pagination import MAX_PAGE_SIZE, build_paginated_response, normalize_pagination
from app.core.roles import ADMIN_ROLES
from app.dependencies.auth import require_roles
from app.dependencies.db import get_db
from app.models import User

router = APIRouter(prefix="/api/v1/admin/audit-events", tags=["admin-audit"])


@router.get("", response_model=dict[str, Any])
async def list_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, Any]:
    page, page_size = normalize_pagination(page, page_size)
    items, total = await AuditService(db).list_events(page=page, page_size=page_size)
    return build_paginated_response(
        [
            {
                "id": event.id,
                "actor_user_id": event.actor_user_id,
                "action": event.action,
                "outcome": event.outcome,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "subject_hash": event.subject_hash,
                "source_hash": event.source_hash,
                "request_id": event.request_id,
                "details": event.details,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in items
        ],
        total,
        page=page,
        page_size=page_size,
    )
