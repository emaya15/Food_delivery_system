"""Level 10: WebSocket authentication, authorisation and event delivery."""
import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import HQ


def connect(client, path, token=None):
    url = path + (f"?token={token}" if token is not None else "")
    return client.websocket_connect(url)


def test_order_socket_rejects_missing_and_invalid_tokens(setup, placed_order):
    c = setup["w"].c
    path = f"/ws/orders/{placed_order['id']}"
    with pytest.raises(WebSocketDisconnect):
        with connect(c, path):
            pass
    with pytest.raises(WebSocketDisconnect):
        with connect(c, path, "not-a-jwt"):
            pass


def test_order_socket_authorisation_matrix(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    path = f"/ws/orders/{placed_order['id']}"
    stranger = w.customer()
    other_owner = w.owner(setup["admin"])
    other_partner = w.partner(setup["admin"])
    for who in (stranger, other_owner, other_partner):
        with pytest.raises(WebSocketDisconnect):
            with connect(c, path, who["token"]):
                pass
    for who in (setup["customer"], setup["owner"], setup["admin"]):
        with connect(c, path, who["token"]) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "connected" and hello["order_id"] == placed_order["id"]
            ws.send_text("ping")
            assert ws.receive_json() == {"type": "pong"}


def test_unknown_order_is_rejected(setup):
    with pytest.raises(WebSocketDisconnect):
        with connect(setup["w"].c, "/ws/orders/9999", setup["admin"]["token"]):
            pass


def test_status_changes_are_pushed_instantly(setup, placed_order):
    c = setup["w"].c
    with connect(c, f"/ws/orders/{placed_order['id']}", setup["customer"]["token"]) as ws:
        assert ws.receive_json()["type"] == "connected"
        c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=setup["owner"]["h"])
        msg = ws.receive_json()
        assert msg["type"] == "order_status" and msg["status"] == "Accepted" and msg["previous_status"] == "Placed"


def test_restaurant_socket_role_check_and_new_order_notification(setup):
    w, c = setup["w"], setup["w"].c
    with pytest.raises(WebSocketDisconnect):
        with connect(c, "/ws/restaurant", setup["customer"]["token"]):
            pass
    with connect(c, "/ws/restaurant", setup["owner"]["token"]) as ws:
        assert ws.receive_json()["type"] == "connected"
        w.add_to_cart(setup["customer"], setup["item"]["id"], 1)
        order = w.place(setup["customer"], setup["address"]["id"]).json()
        msg = ws.receive_json()
        assert msg["type"] == "new_order" and msg["order_id"] == order["id"]


def test_partner_socket_receives_offer_details(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    with pytest.raises(WebSocketDisconnect):
        with connect(c, "/ws/partner", setup["owner"]["token"]):
            pass
    with connect(c, "/ws/partner", p["token"]) as ws:
        assert ws.receive_json()["type"] == "connected"
        c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=setup["owner"]["h"])
        offer = ws.receive_json()
        assert offer["type"] == "delivery_offer"
        for key in ("restaurant_name", "pickup_distance_km", "delivery_distance_km", "expected_earning", "seconds_remaining"):
            assert key in offer
        assert offer["restaurant_name"] == "Spice Hub" and offer["seconds_remaining"] == 30


def test_partner_location_broadcast_with_distance_and_eta(setup, placed_order):
    w, c = setup["w"], setup["w"].c
    p = w.partner(setup["admin"], HQ[0] + 0.001, HQ[1])
    c.put(f"/orders/{placed_order['id']}/accept", json={"preparation_minutes": 10}, headers=setup["owner"]["h"])
    offer_id = c.get("/partners/me/offers", headers=p["h"]).json()["items"][0]["id"]
    c.put(f"/offers/{offer_id}/accept", headers=p["h"])
    with connect(c, f"/ws/orders/{placed_order['id']}", setup["customer"]["token"]) as ws:
        ws.receive_json()
        c.put("/partners/me/location", json={"latitude": HQ[0] + 0.002, "longitude": HQ[1]}, headers=p["h"])
        msg = ws.receive_json()
        assert msg["type"] == "partner_location"
        assert msg["remaining_distance_km"] >= 0 and "estimated_arrival_minutes" in msg


def test_disconnected_clients_are_cleaned_up(setup, placed_order):
    from app.websockets.manager import manager, order_channel

    c = setup["w"].c
    channel = order_channel(placed_order["id"])
    with connect(c, f"/ws/orders/{placed_order['id']}", setup["customer"]["token"]) as ws:
        ws.receive_json()
        assert manager.connection_count(channel) == 1
    assert manager.connection_count(channel) == 0
