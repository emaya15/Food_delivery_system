"""Shared model mixins."""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.types import UTCDateTime
from app.utils.timeutils import utcnow


class TimestampMixin:
    """``created_at`` / ``updated_at`` columns (stored in UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class CreatedAtMixin:
    """For immutable rows that only need ``created_at``."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=func.now(), nullable=False
    )
