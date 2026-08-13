from __future__ import annotations

from typing import Any

MAX_PAGE_SIZE = 100


def normalize_pagination(page: int, page_size: int) -> tuple[int, int]:
    safe_page = max(page, 1)
    safe_page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    return safe_page, safe_page_size


def build_paginated_response(
    items: list[Any],
    total: int,
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    total_pages = 0 if total == 0 else (total + page_size - 1) // page_size
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": total_pages,
    }
