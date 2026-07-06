# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Arunika POS (Sukses Crown Toys) — a **Django 5 + Inertia-Django + Vue 3** admin panel over a **legacy MS SQL Server** dataset (grosir/gudang/retail). Not Laravel, not React. UI strings are Indonesian; keep new UI text Indonesian to match.

Docs worth reading before large changes: `context.md` (architecture + gotchas), `implementation_plan.md` (phase roadmap / what's still mock), `PRODUCTION.md` (Windows deploy), `README.md` (run guide).

## Commands

No linter, formatter, or type-checker is configured. Frontend is plain JS (no TypeScript).

```bash
# Setup (once)
python -m venv venv && .\venv\Scripts\activate
pip install -r requirements.txt
npm install
copy .env.example .env
python manage.py generate_key   # → paste into POS_FERNET_KEY in .env
python manage.py migrate        # SQLite: auth, sessions, logs, connection profiles
python manage.py seed_dev       # optional: admin user + dev grosir connection

# Run — Mode A: dev / hot-reload, localhost only (.env DJANGO_VITE_DEV=1), two terminals
npm run dev                     # Vite HMR on :5173 (hardcoded localhost)
python manage.py runserver      # Django on :8000

# Run — Mode B: cross-device LAN/Tailscale, no hot-reload (.env DJANGO_VITE_DEV=0)
npm run build                   # REQUIRED after every frontend change in this mode
python manage.py runserver 0.0.0.0:8000

# Production (Windows): waitress, see PRODUCTION.md
npm run build
python manage.py collectstatic --noinput
waitress-serve --threads=32 --listen=0.0.0.0:8000 config.wsgi:application

# Tests (Django built-in; only one project test exists today)
python manage.py test                              # full suite
python manage.py test apps.master_data.test_margin # single module

# Custom manage.py commands
python manage.py generate_key    # generate POS_FERNET_KEY (encrypts connection passwords)
python manage.py seed_dev        # seed admin user + dev connection profile
python manage.py ensure_indexes  # create report/stock indexes on MS SQL (idempotent)
python manage.py check_stock_agg # self-check: SQL aggregation vs Python aggregation
python manage.py sync_cdc        # sync report_source replica via CDC (--backfill for initial full copy)
```

## Architecture

**Two datastores, deliberately split:**
- **SQLite (Django ORM)** — only app-local state: users/auth, sessions, `ActivityLog`, and `ServerProfile` (MS SQL connection profiles). This is the only thing `migrate` touches.
- **MS SQL Server (raw `pyodbc`)** — all business data (`m_barang`, `t_penjualan`, `t_pembelian`, opname, mutasi, …). There are **no Django models/migrations for these tables**; access is hand-written SQL in per-app `services.py`. Don't try to model the legacy schema with the ORM.

**Single active connection, multi-server.** All MS SQL access flows through `core/mssql.py` → `get_active_profile()`, which returns the one globally-active `ServerProfile` (switched from the navbar, not per-user/per-request). Profile passwords are **Fernet-encrypted** (`POS_FERNET_KEY`) and only decrypted in-process inside `core/mssql.py`.

**Services pattern.** Views stay thin; heavy SQL + aggregation lives in `services.py` per app:
- `apps/inventory/services.py` — stock/movement engine (multi-way UNION of penjualan/pembelian/retur/opname/mutasi), master-data cache (~10 min TTL).
- `apps/transactions/services.py` — dashboard KPIs, report aggregation, index helpers.
- `apps/master_data/services.py` — products/customers, price update/compare.
- `apps/transactions/cdc_sync.py` — optional reporting-replica sync via SQL Server CDC (see `context.md` § Reporting replica). `ServerProfile.report_source` + `core/mssql.get_report_source()` route report reads to the replica when configured; write paths always target the primary profile.

**MS SQL gotcha — key normalization.** SQL Server collation is case-insensitive and ignores trailing spaces; Python dict keys are not. When joining SQL result sets on `kd_*` keys in Python, normalize both sides with the `_k()` helper (see `apps/inventory/services.py`). Mismatched joins silently drop rows otherwise.

**Request pipeline (`config/settings.py` MIDDLEWARE):** `InertiaMiddleware` → `inertia_share` (lazy shared props: auth user, app name, active connection, flash) → `auth_required` (login gate) → `admin_network_guard` (`/admin-panel/*` requires admin-tier role; when `ENFORCE_TAILSCALE=1` the client IP must be in the Tailscale CGNAT range `100.64.0.0/10`). Shared props are lambdas so they're only evaluated on real Inertia responses.

**Routing.** `config/urls.py` mounts `apps.auth_app` at `/` and `apps.monitoring` + `apps.connections` under `/admin-panel/`. `apps/monitoring/views.py` holds most admin menu endpoints. RBAC roles: kasir / supervisor / admin / superadmin, with per-user `allowed_menu_keys`; menu definitions in `apps/core/menus.py`.

## The deferred-props convention (do this for any slow page)

Heavy queries must not block first paint. Backend wraps the slow bundle in `defer(callable)`; frontend renders the shell instantly and shows a fallback until Inertia fetches the prop.

Backend (`apps/monitoring/views.py`):
```python
from inertia import defer, render

def barang_histori_index(request):
    def load_histori():
        profile = _active()
        # ... raw SQL via services, catch pyodbc.Error into conn_error ...
        return {"rows": rows, "divisi_list": divisi_list, "conn_error": conn_error}
    return render(request, "Admin/Inventory/BarangHistori",
                  props={"histori": defer(load_histori), "filters": {...}})
```

Frontend (`frontend/pages/Admin/Inventory/BarangHistori.vue`) — study this file as the reference:
```vue
<script setup>
import { Deferred, router } from "@inertiajs/vue3";
const props = defineProps({ histori: { type: Object, default: null }, filters: Object });
const data = computed(() => props.histori || {});   // guard null while loading
</script>
<template>
  <!-- filters/forms live OUTSIDE <Deferred> so they render immediately -->
  <Deferred data="histori">
    <template #fallback><LoadingCard message="Mengambil data…" /></template>
    <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />
    <DataTable :rows="displayed" :columns="columns" />
  </Deferred>
</template>
```
Rules: wrap deferred data in `<Deferred data="propName">` with a `LoadingCard` fallback; keep filters/forms outside it; access the prop through a `computed(() => props.x || {})` guard; carry `conn_error` inside the bundle and render it inside `<Deferred>`. Re-fetching from a filter form uses `router.get(url, params, { preserveState: true, preserveScroll: true })`, which re-runs the deferred load.

## Frontend specifics

- Vite entry `frontend/js/main.js`; `base: "/static/"`; build output `frontend/dist` (manifest `manifest.json`). Alias `@` → `frontend/` (`vite.config.js`).
- Inertia page names map to `frontend/pages/<name>.vue` (e.g. view renders `"Admin/Dashboard"`). All admin pages wrap in `frontend/layouts/AdminLayout.vue`.
- Reusable primitives in `frontend/components/ui/` — notably `DataTable.vue` (client-side sort + pagination), `LoadingCard.vue` (deferred fallback). Excel export via `frontend/utils/xlsx.js` (`downloadXlsx`). Nav logic in `composables/useNav.js`.
- Pinia stores (`stores/user.js`, `ui.js`, `connection.js`) hydrate from `inertia_share` props; toasts are driven by Django session flash messages.
- Mode A hardcodes the Vite origin to `localhost:5173`, so cross-device access only works in Mode B (`DJANGO_VITE_DEV=0` + `npm run build`).

## Environment / config

Project-specific config comes from `.env` (see `.env.example` for the full annotated list). Key vars: `POS_FERNET_KEY` (required), `DEBUG`, `SECRET_KEY` (set in prod), `ALLOWED_HOSTS` (CSV; add LAN IP / Tailscale hostname for cross-device), `DJANGO_VITE_DEV`, `ENFORCE_TAILSCALE` / `TAILSCALE_CIDR`, `SESSION_IDLE_SECONDS`, and the `POS_DB_GROSIR_*` seed values used by `seed_dev`.

> Windows: do **not** edit `.env` with `Set-Content -Encoding utf8` — it writes a BOM that corrupts the first key. Edit in a plain editor (or `Out-File -Encoding utf8NoBOM`).

## Project status

Foundation + inventory histori/stock are live on real MS SQL data via the deferred pattern. Several report pages (penjualan/pembelian/fmi/promo/kas/shift) still render mock data from `frontend/mock/*.js`; converting them to real deferred loads is the ongoing work tracked in `implementation_plan.md`. Follow the deferred convention above when making one real.
