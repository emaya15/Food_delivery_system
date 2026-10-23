"""Initial schema: users, restaurants, menu, carts, coupons, orders, delivery, ratings.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-21 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts() -> "list[sa.Column]":
    """created_at / updated_at columns (UTC)."""
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def _money(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.Numeric(10, 2),
        nullable=nullable,
        server_default="0.00" if default else None,
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(10), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "delivery_partner_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vehicle_number", sa.String(20), nullable=False),
        sa.Column("vehicle_type", sa.String(30), nullable=False),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("last_location_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("average_rating", sa.Numeric(3, 2), nullable=False, server_default="0.00"),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
        sa.UniqueConstraint("user_id", name="uq_delivery_partner_profiles_user_id"),
        sa.UniqueConstraint("vehicle_number", name="uq_delivery_partner_profiles_vehicle_number"),
    )

    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("cuisine_type", sa.String(80), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("opening_time", sa.Time(), nullable=False),
        sa.Column("closing_time", sa.Time(), nullable=False),
        sa.Column("is_temporarily_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery_radius_km", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
        sa.Column("min_order_value", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("avg_preparation_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("average_rating", sa.Numeric(3, 2), nullable=False, server_default="0.00"),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_ts(),
    )
    op.create_index("ix_restaurants_owner_id", "restaurants", ["owner_id"])
    op.create_index("ix_restaurants_name", "restaurants", ["name"])
    op.create_index("ix_restaurants_cuisine_type", "restaurants", ["cuisine_type"])
    op.create_index("ix_restaurants_lat_lng", "restaurants", ["latitude", "longitude"])

    op.create_table(
        "menu_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        *_ts(),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_menu_categories_restaurant_id_name"),
    )
    op.create_index("ix_menu_categories_restaurant_id", "menu_categories", ["restaurant_id"])

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("menu_categories.id"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_veg", sa.Boolean(), nullable=False, server_default=sa.true()),
        _money("packaging_charge"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        *_ts(),
    )
    op.create_index("ix_menu_items_category_id", "menu_items", ["category_id"])
    op.create_index("ix_menu_items_restaurant_deleted", "menu_items", ["restaurant_id", "is_deleted"])

    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column("address_line", sa.String(255), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("pincode", sa.String(6), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
    )
    op.create_index("ix_addresses_customer_default", "addresses", ["customer_id", "is_default"])

    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=True),
        sa.Column("discount_type", sa.String(20), nullable=False),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_discount", sa.Numeric(10, 2), nullable=True),
        sa.Column("min_order_value", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=False),
        sa.Column("usage_limit_total", sa.Integer(), nullable=True),
        sa.Column("usage_limit_per_user", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_order_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_ts(),
        sa.CheckConstraint("discount_value > 0", name="discount_positive"),
        sa.CheckConstraint("valid_until > valid_from", name="valid_range"),
    )
    op.create_index("ix_coupons_code", "coupons", ["code"], unique=True)
    op.create_index("ix_coupons_restaurant_id", "coupons", ["restaurant_id"])

    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=True),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id"), nullable=True),
        *_ts(),
        sa.UniqueConstraint("customer_id", name="uq_carts_customer_id"),
    )

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_items_cart_id_menu_item_id"),
        sa.CheckConstraint("quantity >= 1 AND quantity <= 10", name="quantity_range"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_number", sa.String(30), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("address_id", sa.Integer(), sa.ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("delivery_address_line", sa.String(255), nullable=False),
        sa.Column("delivery_city", sa.String(100), nullable=False),
        sa.Column("delivery_pincode", sa.String(6), nullable=False),
        sa.Column("delivery_latitude", sa.Float(), nullable=False),
        sa.Column("delivery_longitude", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Numeric(7, 2), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("payment_method", sa.String(10), nullable=False),
        sa.Column("payment_status", sa.String(10), nullable=False),
        _money("item_total"),
        _money("discount"),
        _money("packaging_charges"),
        _money("delivery_fee"),
        _money("platform_fee"),
        _money("gst"),
        _money("tip"),
        _money("grand_total"),
        sa.Column("surge_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id"), nullable=True),
        sa.Column("coupon_code", sa.String(40), nullable=True),
        sa.Column("delivery_otp", sa.String(4), nullable=False),
        sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("otp_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preparation_minutes", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.String(255), nullable=True),
        sa.Column("cancellation_reason", sa.String(255), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("unassigned_alert_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partner_earning", sa.Numeric(10, 2), nullable=True),
        sa.Column("placed_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
    )
    op.create_index("ix_orders_customer_created", "orders", ["customer_id", "created_at"])
    op.create_index("ix_orders_restaurant_status", "orders", ["restaurant_id", "status"])
    op.create_index("ix_orders_status_placed_at", "orders", ["status", "placed_at"])
    op.create_index("ix_orders_partner_status", "orders", ["partner_id", "status"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), sa.ForeignKey("menu_items.id"), nullable=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        _money("packaging_charge"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        *_ts(),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_menu_item_id", "order_items", ["menu_item_id"])

    op.create_table(
        "order_status_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("changed_by", sa.String(60), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_order_status_history_order_id", "order_status_history", ["order_id"])

    op.create_table(
        "order_sequences",
        sa.Column("seq_date", sa.String(8), primary_key=True),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
    )

    op.create_table(
        "coupon_usages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("is_released", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.UniqueConstraint("order_id", name="uq_coupon_usages_order_id"),
    )
    op.create_index("ix_coupon_usages_coupon_user", "coupon_usages", ["coupon_id", "user_id"])

    op.create_table(
        "delivery_offers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("pickup_distance_km", sa.Numeric(7, 2), nullable=False),
        sa.Column("delivery_distance_km", sa.Numeric(7, 2), nullable=False),
        sa.Column("expected_earning", sa.Numeric(10, 2), nullable=False),
        sa.Column("offered_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.UniqueConstraint("order_id", "partner_id", name="uq_delivery_offers_order_id_partner_id"),
    )
    op.create_index("ix_delivery_offers_order_id", "delivery_offers", ["order_id"])
    op.create_index("ix_delivery_offers_status_expires", "delivery_offers", ["status", "expires_at"])
    op.create_index("ix_delivery_offers_partner_status", "delivery_offers", ["partner_id", "status"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("restaurant_rating", sa.SmallInteger(), nullable=False),
        sa.Column("partner_rating", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.String(500), nullable=True),
        *_ts(),
        sa.UniqueConstraint("order_id", name="uq_ratings_order_id"),
        sa.CheckConstraint("restaurant_rating BETWEEN 1 AND 5", name="restaurant_rating_range"),
        sa.CheckConstraint("partner_rating IS NULL OR partner_rating BETWEEN 1 AND 5", name="partner_rating_range"),
    )
    op.create_index("ix_ratings_restaurant_id", "ratings", ["restaurant_id"])

    op.create_table(
        "admin_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
    )
    op.create_index("ix_admin_notifications_type", "admin_notifications", ["type"])


def downgrade() -> None:
    for table in (
        "admin_notifications",
        "ratings",
        "delivery_offers",
        "coupon_usages",
        "order_sequences",
        "order_status_history",
        "order_items",
        "orders",
        "cart_items",
        "carts",
        "coupons",
        "addresses",
        "menu_items",
        "menu_categories",
        "restaurants",
        "delivery_partner_profiles",
        "users",
    ):
        op.drop_table(table)
