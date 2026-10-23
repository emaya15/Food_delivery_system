"""Reusable pagination / sorting helpers."""
from dataclasses import dataclass
from typing import Optional

from app.utils.constants import DEFAULT_LIMIT, MAX_LIMIT


@dataclass
class PageParams:
    """Validated ``skip`` / ``limit`` values."""

    skip: int = 0
    limit: int = DEFAULT_LIMIT


def validate_page(skip: Optional[int], limit: Optional[int]) -> PageParams:
    """Validate raw pagination values (used outside FastAPI's query validation)."""
    skip = 0 if skip is None else skip
    limit = DEFAULT_LIMIT if limit is None else limit
    if skip < 0:
        raise ValueError("skip must be >= 0")
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return PageParams(skip=skip, limit=limit)
