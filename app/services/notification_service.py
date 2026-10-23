"""Admin notifications and real-time event helpers."""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delivery import AdminNotification
from app.websockets.manager import ADMIN_CHANNEL, queue_event

logger = logging.getLogger(__name__)


def notify_admins(db: Session, type_: str, message: str, order_id: Optional[int] = None) -> AdminNotification:
    """Persist an admin notification and push it to connected admin sockets.

    Must be called inside the caller's transaction; delivery happens after commit.
    """
    note = AdminNotification(type=type_, message=message[:500], order_id=order_id)
    db.add(note)
    db.flush()
    logger.warning("ADMIN NOTIFICATION [%s] %s", type_, message)
    queue_event(
        db,
        ADMIN_CHANNEL,
        {"type": "admin_notification", "notification_type": type_, "message": message, "order_id": order_id},
    )
    return note


def list_admin_notifications(db: Session, skip: int, limit: int, unread_only: bool = False):
    """Paginated admin notifications, newest first."""
    from sqlalchemy import func

    stmt = select(AdminNotification)
    count_stmt = select(func.count(AdminNotification.id))
    if unread_only:
        stmt = stmt.where(AdminNotification.is_read.is_(False))
        count_stmt = count_stmt.where(AdminNotification.is_read.is_(False))
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(AdminNotification.id.desc()).offset(skip).limit(limit)).all()
    return total, rows
