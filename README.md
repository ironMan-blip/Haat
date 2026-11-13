# Haat — MVP e-commerce

A simple general store for Bangladesh. React (Vite) frontend, Django + DRF backend, SQLite.
"Haat" (হাট) is the open village market; the design lays products out like goods at a haat stall.

## Run it

```bash
# backend (Python 3.9+)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed              # 47 sample products from Daraz listings
.venv/bin/python manage.py createsuperuser   # for /admin
.venv/bin/python manage.py runserver 127.0.0.1:8000

# frontend (Node 20+)
cd frontend
npm install
npm run dev -- --port 5174                   # open http://localhost:5174
```

Vite proxies `/api` to Django, so no CORS setup is needed in dev.

Demo buyer account on the dev database: `demo_buyer` / `haat-demo-2026`.

Tests: `cd backend && .venv/bin/python manage.py test shop`

## Architecture

```
frontend/  React 19 + react-router 7, no state library
  src/api.js         fetch wrapper, taka formatting, Daraz image resize
  src/store.jsx      cart (localStorage), auth token, store config
  src/components.jsx header, footer, product tile, delivery meter, qty stepper
  src/pages/         Home, Shop (category/search/sort), Product, Cart, Checkout, Login, Orders
backend/   Django 4.2 + DRF, one app: shop
  shop/models.py      Category, Product, Order, OrderItem
  shop/serializers.py order creation: DB prices, stock lock, delivery fee
  shop/views.py       REST endpoints
  shop/management/commands/seed.py  loads + cleans shop/fixtures/daraz_products.json
  scripts/fetch_daraz.py            re-pulls that fixture from Daraz search
```

| Endpoint | Method | Auth | Notes |
| --- | --- | --- | --- |
| `/api/config/` | GET | - | free-delivery threshold, fee |
| `/api/categories/` | GET | - | |
| `/api/products/?category=&q=&sort=` | GET | - | sort: `price`, `-price`, `-rating` |
| `/api/products/<slug>/` | GET | - | |
| `/api/auth/register/` | POST | - | returns token |
| `/api/auth/login/` | POST | - | returns token |
| `/api/orders/` | GET, POST | Token | own orders only |

Order rules (server side, tested): price comes from the database, never the client; stock is locked
and decremented in one transaction; delivery is free at ৳299 and above, otherwise ৳60; payment is
cash on delivery; phone must be a Bangladeshi mobile number.

Sellers manage products and order status in Django admin (`/admin`).

## Research that shaped it

- **Cartup**: header with search, flash deals, category grid; free delivery over a threshold; COD + bKash/Nagad.
- **Daraz**: product card = image, name, sale price, struck original, discount %.
- **Chaldal**: delivery fee rules shown up front, "pay after receiving". Became the cart's delivery meter.
- **Pickaboo**: COD as a first-class payment option.

## Not in the MVP

Online payment (bKash/SSLCommerz), product variants, reviews, pagination, order emails/SMS,
returns, seller accounts. Product images are hotlinked from Daraz's CDN and listings copied from
Daraz for demo only: replace them with your own before any public launch.
