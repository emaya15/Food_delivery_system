-- Food Delivery System - MySQL 8.0 schema export
-- Mirrors alembic/versions/0001_initial_schema.py. Prefer running `alembic upgrade head`;
-- this file is provided for review, DBA hand-off and quick bootstrap of an empty database.
-- All timestamps are stored in UTC.

CREATE DATABASE IF NOT EXISTS food_delivery CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE food_delivery;

SET time_zone = '+00:00';

CREATE TABLE users (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(255) NOT NULL,
  phone VARCHAR(10) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(30) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  is_approved TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE INDEX ix_users_email (email),
  INDEX ix_users_role (role)
) ENGINE=InnoDB;

CREATE TABLE delivery_partner_profiles (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  vehicle_number VARCHAR(20) NOT NULL,
  vehicle_type VARCHAR(30) NOT NULL,
  is_online TINYINT(1) NOT NULL DEFAULT 0,
  latitude DOUBLE NULL,
  longitude DOUBLE NULL,
  last_location_at DATETIME NULL,
  last_seen_at DATETIME NULL,
  average_rating DECIMAL(3,2) NOT NULL DEFAULT 0.00,
  rating_count INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_delivery_partner_profiles_user_id UNIQUE (user_id),
  CONSTRAINT uq_delivery_partner_profiles_vehicle_number UNIQUE (vehicle_number),
  CONSTRAINT fk_delivery_partner_profiles_user_id_users FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB;

CREATE TABLE restaurants (
  id INT NOT NULL AUTO_INCREMENT,
  owner_id INT NOT NULL,
  name VARCHAR(150) NOT NULL,
  cuisine_type VARCHAR(80) NOT NULL,
  address VARCHAR(255) NOT NULL,
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  opening_time TIME NOT NULL,
  closing_time TIME NOT NULL,
  is_temporarily_closed TINYINT(1) NOT NULL DEFAULT 0,
  delivery_radius_km DECIMAL(5,2) NOT NULL DEFAULT 5.00,
  min_order_value DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  avg_preparation_minutes INT NOT NULL DEFAULT 20,
  average_rating DECIMAL(3,2) NOT NULL DEFAULT 0.00,
  rating_count INT NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_restaurants_owner_id_users FOREIGN KEY (owner_id) REFERENCES users (id),
  INDEX ix_restaurants_owner_id (owner_id),
  INDEX ix_restaurants_name (name),
  INDEX ix_restaurants_cuisine_type (cuisine_type),
  INDEX ix_restaurants_lat_lng (latitude, longitude)
) ENGINE=InnoDB;

CREATE TABLE menu_categories (
  id INT NOT NULL AUTO_INCREMENT,
  restaurant_id INT NOT NULL,
  name VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_menu_categories_restaurant_id_name UNIQUE (restaurant_id, name),
  CONSTRAINT fk_menu_categories_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  INDEX ix_menu_categories_restaurant_id (restaurant_id)
) ENGINE=InnoDB;

CREATE TABLE menu_items (
  id INT NOT NULL AUTO_INCREMENT,
  restaurant_id INT NOT NULL,
  category_id INT NOT NULL,
  name VARCHAR(150) NOT NULL,
  description TEXT NULL,
  price DECIMAL(10,2) NOT NULL,
  is_veg TINYINT(1) NOT NULL DEFAULT 1,
  packaging_charge DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  is_available TINYINT(1) NOT NULL DEFAULT 1,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  deleted_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_menu_items_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  CONSTRAINT fk_menu_items_category_id_menu_categories FOREIGN KEY (category_id) REFERENCES menu_categories (id),
  INDEX ix_menu_items_category_id (category_id),
  INDEX ix_menu_items_restaurant_deleted (restaurant_id, is_deleted)
) ENGINE=InnoDB;

CREATE TABLE addresses (
  id INT NOT NULL AUTO_INCREMENT,
  customer_id INT NOT NULL,
  label VARCHAR(20) NOT NULL,
  address_line VARCHAR(255) NOT NULL,
  city VARCHAR(100) NOT NULL,
  pincode VARCHAR(6) NOT NULL,
  latitude DOUBLE NOT NULL,
  longitude DOUBLE NOT NULL,
  is_default TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_addresses_customer_id_users FOREIGN KEY (customer_id) REFERENCES users (id),
  INDEX ix_addresses_customer_default (customer_id, is_default)
) ENGINE=InnoDB;

CREATE TABLE coupons (
  id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(40) NOT NULL,
  description VARCHAR(255) NULL,
  restaurant_id INT NULL,
  discount_type VARCHAR(20) NOT NULL,
  discount_value DECIMAL(10,2) NOT NULL,
  max_discount DECIMAL(10,2) NULL,
  min_order_value DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  valid_from DATETIME NOT NULL,
  valid_until DATETIME NOT NULL,
  usage_limit_total INT NULL,
  usage_limit_per_user INT NULL,
  used_count INT NOT NULL DEFAULT 0,
  first_order_only TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE INDEX ix_coupons_code (code),
  INDEX ix_coupons_restaurant_id (restaurant_id),
  CONSTRAINT fk_coupons_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  CONSTRAINT fk_coupons_created_by_users FOREIGN KEY (created_by) REFERENCES users (id),
  CONSTRAINT ck_coupons_discount_positive CHECK (discount_value > 0),
  CONSTRAINT ck_coupons_valid_range CHECK (valid_until > valid_from)
) ENGINE=InnoDB;

CREATE TABLE carts (
  id INT NOT NULL AUTO_INCREMENT,
  customer_id INT NOT NULL,
  restaurant_id INT NULL,
  coupon_id INT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_carts_customer_id UNIQUE (customer_id),
  CONSTRAINT fk_carts_customer_id_users FOREIGN KEY (customer_id) REFERENCES users (id),
  CONSTRAINT fk_carts_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  CONSTRAINT fk_carts_coupon_id_coupons FOREIGN KEY (coupon_id) REFERENCES coupons (id)
) ENGINE=InnoDB;

CREATE TABLE cart_items (
  id INT NOT NULL AUTO_INCREMENT,
  cart_id INT NOT NULL,
  menu_item_id INT NOT NULL,
  quantity INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_cart_items_cart_id_menu_item_id UNIQUE (cart_id, menu_item_id),
  CONSTRAINT fk_cart_items_cart_id_carts FOREIGN KEY (cart_id) REFERENCES carts (id) ON DELETE CASCADE,
  CONSTRAINT fk_cart_items_menu_item_id_menu_items FOREIGN KEY (menu_item_id) REFERENCES menu_items (id),
  CONSTRAINT ck_cart_items_quantity_range CHECK (quantity >= 1 AND quantity <= 10)
) ENGINE=InnoDB;

CREATE TABLE orders (
  id INT NOT NULL AUTO_INCREMENT,
  order_number VARCHAR(30) NOT NULL,
  customer_id INT NOT NULL,
  restaurant_id INT NOT NULL,
  partner_id INT NULL,
  address_id INT NULL,
  delivery_address_line VARCHAR(255) NOT NULL,
  delivery_city VARCHAR(100) NOT NULL,
  delivery_pincode VARCHAR(6) NOT NULL,
  delivery_latitude DOUBLE NOT NULL,
  delivery_longitude DOUBLE NOT NULL,
  distance_km DECIMAL(7,2) NOT NULL,
  status VARCHAR(30) NOT NULL,
  payment_method VARCHAR(10) NOT NULL,
  payment_status VARCHAR(10) NOT NULL,
  item_total DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  discount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  packaging_charges DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  delivery_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  platform_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  gst DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  tip DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  grand_total DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  surge_applied TINYINT(1) NOT NULL DEFAULT 0,
  coupon_id INT NULL,
  coupon_code VARCHAR(40) NULL,
  delivery_otp VARCHAR(4) NOT NULL,
  otp_attempts INT NOT NULL DEFAULT 0,
  otp_locked TINYINT(1) NOT NULL DEFAULT 0,
  preparation_minutes INT NULL,
  rejection_reason VARCHAR(255) NULL,
  cancellation_reason VARCHAR(255) NULL,
  scheduled_for DATETIME NULL,
  unassigned_alert_sent TINYINT(1) NOT NULL DEFAULT 0,
  partner_earning DECIMAL(10,2) NULL,
  placed_at DATETIME NOT NULL,
  accepted_at DATETIME NULL,
  ready_at DATETIME NULL,
  picked_up_at DATETIME NULL,
  delivered_at DATETIME NULL,
  cancelled_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_orders_order_number UNIQUE (order_number),
  CONSTRAINT fk_orders_customer_id_users FOREIGN KEY (customer_id) REFERENCES users (id),
  CONSTRAINT fk_orders_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  CONSTRAINT fk_orders_partner_id_users FOREIGN KEY (partner_id) REFERENCES users (id),
  CONSTRAINT fk_orders_address_id_addresses FOREIGN KEY (address_id) REFERENCES addresses (id) ON DELETE SET NULL,
  CONSTRAINT fk_orders_coupon_id_coupons FOREIGN KEY (coupon_id) REFERENCES coupons (id),
  INDEX ix_orders_customer_created (customer_id, created_at),
  INDEX ix_orders_restaurant_status (restaurant_id, status),
  INDEX ix_orders_status_placed_at (status, placed_at),
  INDEX ix_orders_partner_status (partner_id, status)
) ENGINE=InnoDB;

CREATE TABLE order_items (
  id INT NOT NULL AUTO_INCREMENT,
  order_id INT NOT NULL,
  menu_item_id INT NULL,
  name VARCHAR(150) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  packaging_charge DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  quantity INT NOT NULL,
  line_total DECIMAL(10,2) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_order_items_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
  CONSTRAINT fk_order_items_menu_item_id_menu_items FOREIGN KEY (menu_item_id) REFERENCES menu_items (id),
  INDEX ix_order_items_order_id (order_id),
  INDEX ix_order_items_menu_item_id (menu_item_id)
) ENGINE=InnoDB;

CREATE TABLE order_status_history (
  id INT NOT NULL AUTO_INCREMENT,
  order_id INT NOT NULL,
  from_status VARCHAR(30) NULL,
  to_status VARCHAR(30) NOT NULL,
  changed_by VARCHAR(60) NOT NULL,
  note VARCHAR(255) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_order_status_history_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
  INDEX ix_order_status_history_order_id (order_id)
) ENGINE=InnoDB;

CREATE TABLE order_sequences (
  seq_date VARCHAR(8) NOT NULL,
  last_value INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (seq_date)
) ENGINE=InnoDB;

CREATE TABLE coupon_usages (
  id INT NOT NULL AUTO_INCREMENT,
  coupon_id INT NOT NULL,
  user_id INT NOT NULL,
  order_id INT NOT NULL,
  is_released TINYINT(1) NOT NULL DEFAULT 0,
  released_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_coupon_usages_order_id UNIQUE (order_id),
  CONSTRAINT fk_coupon_usages_coupon_id_coupons FOREIGN KEY (coupon_id) REFERENCES coupons (id),
  CONSTRAINT fk_coupon_usages_user_id_users FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_coupon_usages_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id),
  INDEX ix_coupon_usages_coupon_user (coupon_id, user_id)
) ENGINE=InnoDB;

CREATE TABLE delivery_offers (
  id INT NOT NULL AUTO_INCREMENT,
  order_id INT NOT NULL,
  partner_id INT NOT NULL,
  status VARCHAR(20) NOT NULL,
  pickup_distance_km DECIMAL(7,2) NOT NULL,
  delivery_distance_km DECIMAL(7,2) NOT NULL,
  expected_earning DECIMAL(10,2) NOT NULL,
  offered_at DATETIME NOT NULL,
  expires_at DATETIME NOT NULL,
  responded_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_delivery_offers_order_id_partner_id UNIQUE (order_id, partner_id),
  CONSTRAINT fk_delivery_offers_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id),
  CONSTRAINT fk_delivery_offers_partner_id_users FOREIGN KEY (partner_id) REFERENCES users (id),
  INDEX ix_delivery_offers_order_id (order_id),
  INDEX ix_delivery_offers_status_expires (status, expires_at),
  INDEX ix_delivery_offers_partner_status (partner_id, status)
) ENGINE=InnoDB;

CREATE TABLE ratings (
  id INT NOT NULL AUTO_INCREMENT,
  order_id INT NOT NULL,
  customer_id INT NOT NULL,
  restaurant_id INT NOT NULL,
  partner_id INT NULL,
  restaurant_rating SMALLINT NOT NULL,
  partner_rating SMALLINT NULL,
  comment VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uq_ratings_order_id UNIQUE (order_id),
  CONSTRAINT fk_ratings_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id),
  CONSTRAINT fk_ratings_customer_id_users FOREIGN KEY (customer_id) REFERENCES users (id),
  CONSTRAINT fk_ratings_restaurant_id_restaurants FOREIGN KEY (restaurant_id) REFERENCES restaurants (id),
  CONSTRAINT fk_ratings_partner_id_users FOREIGN KEY (partner_id) REFERENCES users (id),
  CONSTRAINT ck_ratings_restaurant_rating_range CHECK (restaurant_rating BETWEEN 1 AND 5),
  CONSTRAINT ck_ratings_partner_rating_range CHECK (partner_rating IS NULL OR partner_rating BETWEEN 1 AND 5),
  INDEX ix_ratings_restaurant_id (restaurant_id)
) ENGINE=InnoDB;

CREATE TABLE admin_notifications (
  id INT NOT NULL AUTO_INCREMENT,
  type VARCHAR(50) NOT NULL,
  message VARCHAR(500) NOT NULL,
  order_id INT NULL,
  is_read TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_admin_notifications_order_id_orders FOREIGN KEY (order_id) REFERENCES orders (id),
  INDEX ix_admin_notifications_type (type)
) ENGINE=InnoDB;

-- Alembic bookkeeping (only needed if you bootstrap with this file instead of `alembic upgrade head`):
-- CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, PRIMARY KEY (version_num));
-- INSERT INTO alembic_version (version_num) VALUES ('0001_initial_schema');
