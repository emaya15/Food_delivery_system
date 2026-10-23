"""WebSocket endpoints (Level 10).

Authentication: ``?token=<JWT>`` query parameter. Invalid/expired tokens and
unauthorised users are rejected during the handshake (policy-violation close).
Clients may send ``"ping"``; the server answers ``{"type": "pong"}``.

A database session is used only for the handshake check and closed immediately,
so long-lived sockets never hold a pooled DB connection.
"""
import logging
from typing import Callable, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import database
from app.dependencies import user_from_token
from app.enums import Role
from app.models.order import Order
from app.models.user import User
from app.services import order_service
from app.utils.errors import AppError
from app.websockets.manager import (
    ADMIN_CHANNEL,
    Channel,
    manager,
    order_channel,
    partner_channel,
    restaurant_channel,
)

logger = logging.getLogger(__name__)
router = APIRouter()

WS_POLICY_VIOLATION = 1008


def _authorize(token: Optional[str], check: Callable[[Session, User], Optional[dict]]) -> dict:
    """Validate the token and run ``check``; return the hello payload or raise ``AppError``."""
    if not token:
        raise AppError("Missing token", 401)
    db = database.SessionLocal()
    try:
        user = user_from_token(db, token)
        hello = check(db, user)
        if hello is None:
            raise AppError("Not authorised", 403)
        return hello
    finally:
        db.close()


async def _serve(websocket: WebSocket, channel: Channel, hello: dict) -> None:
    """Accept, register, then keep the socket open until the client leaves."""
    await websocket.accept()
    await manager.connect(channel, websocket)
    try:
        await websocket.send_json(hello)
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:  # never let a broken client crash the server
        logger.debug("websocket error on %s", channel, exc_info=True)
    finally:
        manager.disconnect(channel, websocket)


async def _handle(websocket: WebSocket, token: Optional[str], channel: Channel,
                  check: Callable[[Session, User], Optional[dict]]) -> None:
    try:
        hello = await run_in_threadpool(_authorize, token, check)
    except AppError as exc:
        await websocket.close(code=WS_POLICY_VIOLATION, reason=exc.message)
        return
    await _serve(websocket, channel, hello)


@router.websocket("/ws/orders/{order_id}")
async def ws_order(websocket: WebSocket, order_id: int, token: Optional[str] = Query(None)):
    """Live tracking: status changes, partner location, remaining distance and ETA.

    Allowed: the order's customer, its restaurant owner, the assigned partner and admins.
    """

    def check(db: Session, user: User) -> Optional[dict]:
        order = db.get(Order, order_id)
        if order is None or not order_service.can_access_order(db, user, order):
            return None
        return {"type": "connected", "order_id": order.id, "order_number": order.order_number, "status": order.status}

    await _handle(websocket, token, order_channel(order_id), check)


@router.websocket("/ws/restaurant")
async def ws_restaurant(websocket: WebSocket, token: Optional[str] = Query(None)):
    """New-order and order-status notifications for a Restaurant Owner."""
    holder: dict = {}

    def check(db: Session, user: User) -> Optional[dict]:
        if user.role != Role.RESTAURANT_OWNER.value:
            return None
        holder["id"] = user.id
        return {"type": "connected", "role": user.role}

    try:
        hello = await run_in_threadpool(_authorize, token, check)
    except AppError as exc:
        return await websocket.close(code=WS_POLICY_VIOLATION, reason=exc.message)
    await _serve(websocket, restaurant_channel(holder["id"]), hello)


@router.websocket("/ws/partner")
async def ws_partner(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Delivery offers (restaurant, distances, expected earning, seconds remaining) for a partner."""
    holder: dict = {}

    def check(db: Session, user: User) -> Optional[dict]:
        if user.role != Role.DELIVERY_PARTNER.value:
            return None
        holder["id"] = user.id
        return {"type": "connected", "role": user.role}

    try:
        hello = await run_in_threadpool(_authorize, token, check)
    except AppError as exc:
        return await websocket.close(code=WS_POLICY_VIOLATION, reason=exc.message)
    await _serve(websocket, partner_channel(holder["id"]), hello)


@router.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Admin alerts (unassigned orders, OTP lockouts)."""

    def check(db: Session, user: User) -> Optional[dict]:
        return {"type": "connected", "role": user.role} if user.role == Role.ADMIN.value else None

    await _handle(websocket, token, ADMIN_CHANNEL, check)
