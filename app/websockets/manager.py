"""WebSocket connection registry and thread-safe event publishing.

Services run in worker threads (sync FastAPI endpoints, APScheduler jobs) while
WebSockets live on the asyncio event loop. Services therefore *queue* events on
the SQLAlchemy session; the events are published only **after a successful
commit** (so clients never see state that was rolled back) via
``asyncio.run_coroutine_threadsafe``.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Hashable, List, Optional, Set, Tuple

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PENDING_KEY = "pending_ws_events"

Channel = Tuple[str, Optional[int]]


def order_channel(order_id: int) -> Channel:
    return ("order", order_id)


def restaurant_channel(owner_id: int) -> Channel:
    return ("restaurant", owner_id)


def partner_channel(partner_id: int) -> Channel:
    return ("partner", partner_id)


ADMIN_CHANNEL: Channel = ("admin", None)


class ConnectionManager:
    """Tracks open WebSockets per channel and broadcasts JSON messages."""

    def __init__(self) -> None:
        self._connections: Dict[Hashable, Set[WebSocket]] = defaultdict(set)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # When set to a list, every published message is also appended (used by tests).
        self.capture: Optional[List[Tuple[Channel, Dict[str, Any]]]] = None

    def set_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        """Remember the server event loop so worker threads can schedule sends."""
        self._loop = loop

    async def connect(self, channel: Channel, websocket: WebSocket) -> None:
        """Register an already-accepted websocket."""
        self._connections[channel].add(websocket)

    def disconnect(self, channel: Channel, websocket: WebSocket) -> None:
        """Safely remove a websocket (idempotent)."""
        conns = self._connections.get(channel)
        if conns is None:
            return
        conns.discard(websocket)
        if not conns:
            self._connections.pop(channel, None)

    def connection_count(self, channel: Optional[Channel] = None) -> int:
        if channel is not None:
            return len(self._connections.get(channel, ()))
        return sum(len(v) for v in self._connections.values())

    async def _send(self, channel: Channel, message: Dict[str, Any]) -> None:
        for ws in list(self._connections.get(channel, ())):
            try:
                await ws.send_json(message)
            except Exception:  # client went away: clean up instead of failing the broadcast
                logger.debug("dropping dead websocket on %s", channel)
                self.disconnect(channel, ws)

    def publish(self, channel: Channel, message: Dict[str, Any]) -> None:
        """Publish from any thread. No-op when nobody is connected."""
        if self.capture is not None:
            self.capture.append((channel, message))
        loop = self._loop
        if loop is None or loop.is_closed() or not self._connections.get(channel):
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(channel, message), loop)
        except RuntimeError:  # loop shutting down
            logger.debug("event loop closed; dropping message for %s", channel)


manager = ConnectionManager()


def queue_event(db: Session, channel: Channel, message: Dict[str, Any]) -> None:
    """Queue a message to be delivered to ``channel`` after ``db`` commits."""
    db.info.setdefault(_PENDING_KEY, []).append((channel, message))


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    for channel, message in session.info.pop(_PENDING_KEY, []):
        manager.publish(channel, message)


@event.listens_for(Session, "after_rollback")
def _discard_after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
