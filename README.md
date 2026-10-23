# Food Delivery System Backend

A FastAPI REST + WebSocket backend where customers browse nearby restaurants, manage carts, apply coupons, place orders, track deliveries live and rate the experience. Roles: **Admin, Restaurant Owner, Delivery Partner, Customer**.

> **Verification status (read this first).** The code was written and syntax-checked (`compileall`, static import check) in a sandbox that had **no access to PyPI or MySQL**, so the application and the pytest suite were **not executed** there. Run `pytest` yourself (section 20) before relying on it; if something fails, it is most likely a small integration slip that the test output will point to directly.

## 1. Features (all 15 levels + bonuses)

| Level | Area |
|---|---|
| 1 | MySQL + SQLAlchemy 2, Alembic migrations (no `create_all`), `created_at/updated_at`, `sql/schema.sql` |
| 2 | Register / login / me, bcrypt, 30-min JWT, RBAC, admin approval, admin bootstrap CLI |
| 3 | Restaurants, categories, menu items, open/closed logic, soft-deleted items, grouped menu |
| 4 | Addresses (one default), Haversine nearby search with distance + ETA |
| 5 | Cart (one restaurant, qty 1-10, 409 conflict message) |
| 6 | Coupons (percent/flat, caps, min order, dates, global/per-user limits, first-order, case-insensitive, usage tracking & release) |
| 7 | Atomic order placement, exact billing rules, OTP, COD/online mock payments, cancel/refund, reorder |
| 8 | Restaurant accept/reject/preparing/ready with a validated state machine and history |
| 9 | Nearest-first partner offers (30 s), accept/decline, pickup, OTP delivery with 3-strike lock, earnings |
| 10 | WebSockets for order tracking, restaurants, partners (+ admin) and `/tracking-test` page |
| 11 | APScheduler jobs (auto-reject, offer expiry, retry/alert, stale partners, coupon expiry) |
| 12 | Ratings with automatic averages |
| 13 | Validation + consistent error body |
| 14 | `skip`/`limit`, search, filters, sorting |
| 15 | Admin dashboard and 4 more reports |
| Bonus | Surge pricing (x1.5 at 12-14h and 19-22h local), scheduled same-day orders, tests, Docker |

## 2. Technology stack
Python 3.9-3.12, FastAPI, Pydantic v2 / pydantic-settings, SQLAlchemy 2, MySQL 8 (PyMySQL), Alembic, PyJWT, Passlib+bcrypt, WebSockets, APScheduler, Uvicorn, Pytest, Docker Compose.

## 3. Folder structure
```
food_delivery_system/
├── app/
│   ├── main.py  config.py  database.py  dependencies.py  enums.py  cli.py
│   ├── models/      SQLAlchemy models
│   ├── schemas/     Pydantic request/response models
│   ├── routers/     HTTP layer only
│   ├── services/    business rules (billing, coupons, orders, assignment, ...)
│   ├── auth/        password hashing + JWT
│   ├── websockets/  connection manager + WS endpoints
│   ├── jobs/        APScheduler jobs
│   └── utils/       geo, money, time, errors, constants
├── alembic/versions/0001_initial_schema.py
├── static/tracking_test.html
├── tests/   sql/schema.sql   Dockerfile   docker-compose.yml
├── .env.example  requirements.txt  alembic.ini  pytest.ini
```

## 4. Prerequisites
Python 3.9+ (3.11 recommended), MySQL 8.0+, (optional) Docker.

## 5. Virtual environment
Linux/macOS:
```bash
python3 -m venv venv && source venv/bin/activate
```
Windows PowerShell:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

## 6. Install dependencies
```bash
pip install -r requirements.txt
```

## 7. Create the MySQL database
```sql
CREATE DATABASE food_delivery CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'fd_user'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON food_delivery.* TO 'fd_user'@'localhost';
```

## 8. Configure `.env`
```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # use as JWT_SECRET_KEY
```
Edit `DATABASE_URL` and `JWT_SECRET_KEY`. The app refuses to start without them (secret must be >= 32 chars). `.env` is git-ignored.

## 9. Migrations
```bash
alembic upgrade head          # create / update tables
alembic downgrade -1          # roll back one revision
alembic revision --autogenerate -m "describe change"   # after changing models
```
`sql/schema.sql` is an equivalent plain-SQL export for review or hand-off (prefer Alembic).

## 10. Admin bootstrap
Public registration can never create an Admin. Create the first one from the server:
```bash
python -m app.cli create-admin --email admin@example.com --name "Admin" --phone 9000000000
# prompts for the password (or set ADMIN_PASSWORD in the environment for non-interactive use)
```

## 11. Run
```bash
uvicorn app.main:app --reload          # development
uvicorn app.main:app --host 0.0.0.0 --port 8000   # single worker (see Assumptions)
```

## 12. API docs
Swagger UI: http://localhost:8000/docs - ReDoc: http://localhost:8000/redoc - WS test page: http://localhost:8000/tracking-test

## 13. Endpoint summary
- **Auth/Admin:** `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `PUT /admin/users/{id}/approve`, `GET /admin/users`, `GET /admin/notifications`
- **Restaurants/Menu:** `POST /restaurants`, `GET /restaurants/me`, `GET|PUT /restaurants/{id}`, `PUT /restaurants/{id}/open-status`, `POST /restaurants/{id}/categories`, `POST /restaurants/{id}/menu-items`, `GET /restaurants/{id}/menu`, `PUT /menu-items/{id}`, `PUT /menu-items/{id}/availability`, `DELETE /menu-items/{id}`
- **Search/Addresses:** `GET /restaurants/nearby`, `POST|GET /addresses`, `PUT|DELETE /addresses/{id}`, `PUT /addresses/{id}/default`
- **Cart:** `GET|DELETE /cart`, `POST /cart/items`, `PUT|DELETE /cart/items/{id}`, `POST /cart/apply-coupon`, `DELETE /cart/coupon`
- **Coupons:** `POST|GET /coupons`, `GET /coupons/available`, `PUT /coupons/{id}`, `PUT /coupons/{id}/deactivate`
- **Orders:** `POST|GET /orders`, `GET /orders/{id}`, `PUT /orders/{id}/cancel`, `POST /orders/{id}/reorder`
- **Restaurant orders:** `GET /restaurants/me/orders`, `PUT /orders/{id}/accept|reject|preparing|ready`
- **Delivery:** `PUT /partners/me/availability|location`, `GET /partners/me/offers`, `PUT /offers/{id}/accept|decline`, `PUT /orders/{id}/pickup|out-for-delivery|deliver`, `GET /partners/me/earnings`
- **Ratings:** `POST /orders/{id}/rating`, `GET /restaurants/{id}/ratings`
- **Reports (role-restricted):** `GET /reports/admin-dashboard|top-restaurants|coupon-usage|restaurant-sales|partner-summary`
- **WebSockets:** `WS /ws/orders/{id}`, `/ws/restaurant`, `/ws/partner`, `/ws/admin`

Pagination: `?skip=0&limit=20` (limit 1-100). Errors: `{"success": false, "error": {"status_code": 409, "message": "...", "details": null}}`.

## 14. Example requests
```bash
curl -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"name":"Asha","email":"asha@example.com","phone":"9876543210","password":"Passw0rd123","role":"Customer"}'

curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"asha@example.com","password":"Passw0rd123"}'      # -> access_token

curl localhost:8000/auth/me -H "Authorization: Bearer <access_token>"
curl "localhost:8000/restaurants/nearby?latitude=17.4486&longitude=78.3908&sort_by=rating" -H "Authorization: Bearer <token>"
```
Owners and partners register as `"role": "Restaurant Owner"` / `"Delivery Partner"` (partners also need `vehicle_number`, `vehicle_type`) and **cannot act until an admin approves them**.

## 15. Creating test accounts (all four roles)
1. Create an admin with the CLI (section 10).
2. Register a Customer, a Restaurant Owner and a Delivery Partner through `/auth/register` (development-only example password: `Passw0rd123`).
3. Log in as the admin and call `PUT /admin/users/{id}/approve` for the owner and the partner (`GET /admin/users?is_approved=false` lists who is waiting).

## 16. Sample coordinates (Hyderabad)
- Restaurant: `17.4486, 78.3908` (radius 5 km)
- Customer address: `17.4500, 78.3920` (about 0.2 km away)
- Partner start: `17.4496, 78.3908` (about 0.1 km from the restaurant)
- Outside radius: `17.6000, 78.6000`

## 17. Sample data
Restaurant `Spice Hub` (South Indian, open 00:00-23:59, min order 100). Category `Mains`; items `Masala Dosa` (price 120, packaging 10, veg), `Idli` (60, packaging 5).
Coupons (admin): `SAVE10` = 10 % up to 50, min order 100; `FLAT30` = flat 30, min order 100. Codes are case-insensitive.

## 18. Order-to-delivery walkthrough
1. Owner: `POST /restaurants`, `/categories`, `/menu-items`.
2. Partner: `PUT /partners/me/location` then `PUT /partners/me/availability {"is_online": true}`.
3. Customer: `POST /addresses`, `POST /cart/items`, optionally `POST /cart/apply-coupon`, then `POST /orders` (note `delivery_otp` in the response; only the customer sees it).
4. Owner: `PUT /orders/{id}/accept {"preparation_minutes": 15}` - the nearest partner receives an offer.
5. Partner: `GET /partners/me/offers` -> `PUT /offers/{offer_id}/accept` (within 30 s).
6. Owner: `PUT /orders/{id}/preparing`, then `/ready`.
7. Partner: `PUT /orders/{id}/pickup`, `/out-for-delivery`, then `PUT /orders/{id}/deliver {"otp": "1234"}`.
8. Customer: `POST /orders/{id}/rating {"restaurant_rating": 5, "partner_rating": 5}`.

## 19. WebSocket testing
**Test page:** open `/tracking-test`, paste a JWT and an order id, click **Connect**, then perform steps 4-7 above in Swagger; status and location events appear live.
**Postman:** New -> WebSocket Request -> `ws://localhost:8000/ws/orders/<order_id>?token=<JWT>` -> Connect. Use `/ws/restaurant?token=` (new-order alerts), `/ws/partner?token=` (offers with restaurant, distances, expected earning, `seconds_remaining`). Send the text `ping` to get `{"type":"pong"}`.
Invalid tokens or unauthorised users are closed during the handshake (code 1008). Partners should call `PUT /partners/me/location` every 5-10 s; customers receive `partner_location` events with `remaining_distance_km` and `estimated_arrival_minutes`.

## 20. Scheduled jobs and tests
Jobs start with the app (`SCHEDULER_ENABLED=true`): auto-reject Placed orders > 5 min (every 30 s), expire offers > 30 s (every 5 s), retry unassigned + 15-min admin alert (every minute), partners offline after 10 min without location (every 5 min), deactivate expired coupons (daily). All run in transactions and record `changed_by = "System"`.

Tests (no MySQL needed - they use an in-memory SQLite database and never touch your configured DB):
```bash
pip install -r requirements.txt
pytest
```
Covers auth/JWT expiry/RBAC, approval, ownership, Haversine, cart, coupons, billing, rollback, cancel/refund, transitions, nearest partner, offer expiry, OTP lock, WebSocket auth, jobs, ratings, reports. **Limitation:** SQLite ignores `SELECT ... FOR UPDATE`, so the test for "only one partner wins" checks the sequential outcome; verify true parallel behaviour against MySQL (e.g. two simultaneous `PUT /offers/{id}/accept` calls).

## 21. Docker
```bash
cp .env.example .env     # set MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD, JWT_SECRET_KEY
docker compose up --build
docker compose exec api python -m app.cli create-admin --email admin@example.com
```
The API container runs `alembic upgrade head` on start.

## 22. Troubleshooting
- `ValidationError ... database_url / jwt_secret_key`: `.env` missing or incomplete.
- `Can't connect to MySQL`: check host/port/user and that the database exists.
- `Access denied` on `alembic upgrade`: grant the DB user privileges (section 7).
- 401: missing/expired token (30 min). 403 on restaurant/partner actions: account not approved yet.
- Orders "restaurant currently closed": opening hours are evaluated in `TIMEZONE`.
- bcrypt/passlib warnings: keep the pinned `bcrypt==4.0.1`.

## 23. Assumptions, rules and known limitations
- Money uses `Decimal`; timestamps are stored in UTC; opening hours, surge windows and "today" use `TIMEZONE` (default Asia/Kolkata).
- Distance is straight-line (Haversine); delivery fee uses the restaurant-to-address distance rounded to 2 decimals, extra km rounded up.
- Customers are auto-approved; owners/partners need admin approval. Inactive users get 403.
- Orders auto-reject after 5 min in `Placed` (including scheduled orders - the restaurant must still confirm). Scheduled orders must be >= 30 min ahead and later the same local day; partner search for them starts shortly before they are due.
- Online payments are mocked (marked Paid, then Refunded on cancel/reject); there is no real gateway.
- A coupon use is counted only when an order is placed and released on cancel/reject/auto-reject. Per-user/global limits are enforced under a row lock on the coupon.
- Admin alerts are stored in `admin_notifications` (`GET /admin/notifications`) and pushed to `/ws/admin`.
- A partner who has a live (pending) offer for one order is not offered another until it is answered or expires.
- The scheduler and WebSocket registry are **in-process**: run a single Uvicorn worker (or set `SCHEDULER_ENABLED=false` on extra workers and add a broker such as Redis for cross-process broadcasts).
- No rate limiting, refresh tokens or email verification.
