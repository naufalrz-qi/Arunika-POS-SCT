# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Arunika POS (Sukses Crown Toys) — a **Django 5 + Inertia-Django + Vue 3** admin panel over a **legacy MS SQL Server** dataset (grosir/gudang/retail). Not Laravel, not React. UI strings are Indonesian; keep new UI text Indonesian to match.

Docs worth reading before large changes: `context.md` (architecture + gotchas), `KESIAPAN-FITUR.md` (per-menu readiness audit + known-unfixed list), `PANDUAN-PENGGUNA.md` (end-user guide), `PRODUCTION.md` (Windows deploy), `README.md` (run guide).

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
python manage.py backup_db --dir D:\backup\arunika --keep-days 30   # VACUUM INTO daily backup of db.sqlite3
python manage.py seed_dev        # seed admin user + dev connection profile
python manage.py ensure_indexes  # create report/stock indexes on MS SQL (idempotent)
python manage.py check_stock_agg # self-check: SQL aggregation vs Python aggregation
python manage.py sync_cdc        # sync report_source replica via CDC (--backfill for initial full copy)
python manage.py sync_feed --source GUDANG --dry-run   # fan-out master data gudang → toko
python manage.py init_hub --hub AMPHOREUS --ref GUDANG # create/refresh the AMPHOREUS hub schema (idempotent)
python manage.py sync_hub --hub AMPHOREUS --dry-run    # DEPRECATED feed-based hub pull (no longer scheduled)
python manage.py pull_hub --mode segar --hari 7 --dry-run   # fill AMPHOREUS straight from the source tables
python manage.py pull_hub --mode cocok --dry-run            # report which days differ, branch vs hub
python manage.py pull_master --dry-run                      # master data into AMPHOREUS, from GUDANG only
python manage.py sync_harga --dry-run                       # GUDANG prices vs every toko; report what differs
python manage.py sync_master --dry-run                      # GUDANG names/brands vs every toko (suppliers deliberately excluded)
```

## Architecture

**Two datastores, deliberately split:**
- **SQLite (Django ORM)** — only app-local state: users/auth, sessions, `ActivityLog`, `ServerProfile` (MS SQL connection profiles), and `TautanUser` (legacy-user links, **one row per user × connection** — see `context.md` § "Tautan user legacy"; `kd_user` codes are generated independently by each server, so the same code means a different person elsewhere, and `apps/auth_app/tautan.py` never falls back to another connection's link). This is the only thing `migrate` touches.
- **MS SQL Server (raw `pyodbc`)** — all business data (`m_barang`, `t_penjualan`, `t_pembelian`, opname, mutasi, …). There are **no Django models/migrations for these tables**; access is hand-written SQL in per-app `services.py`. Don't try to model the legacy schema with the ORM.

**Single active connection, multi-server.** All MS SQL access flows through `core/mssql.py` → `get_active_profile()`, which returns the one globally-active `ServerProfile` (switched from the navbar, not per-user/per-request). Profile passwords are **Fernet-encrypted** (`POS_FERNET_KEY`) and only decrypted in-process inside `core/mssql.py`.

**Services pattern.** Views stay thin; heavy SQL + aggregation lives in `services.py` per app:
- `apps/inventory/services.py` — stock/movement engine (multi-way UNION of penjualan/pembelian/retur/opname/mutasi), master-data cache (~10 min TTL).
- `apps/transactions/services.py` — dashboard KPIs, report aggregation, index helpers.
- `apps/master_data/services.py` — products/customers, price update/compare.
- `apps/master_data/master_crud.py` — one CRUD engine for **13 master tables** (pelanggan, supplier, and the 11 reference tables behind the single `kelola_referensi` menu). Adding a table means adding a `_MASTER` entry, not new SQL. Read `context.md` § "CRUD master & kas" before touching it — above all that master codes are `{huruf}{blok}{NNN}` with a **rolling block** (`MAA999` → `MAB000`; `m_merk` is already at `MAB483`), that the `MAX()` pattern must be `LIKE 'X[A-Z][A-Z][0-9][0-9][0-9]'` and never `LIKE 'X%'`, and that **there is no `DELETE` here and never will be** — `ON DELETE CASCADE` from `m_merk`/`m_kategori`/… reaches `m_barang`. Cancellation is `status = 0`, and "active" is `2` in `m_biaya`, not `1`.
- `apps/master_data/barang.py` — Kelola Barang: the only path that **creates** `m_barang` (+ `m_barang_satuan`, optional `m_barang_divisi`) and the only one that can **add** a satuan or divisi row to an existing barang. Gudang-only via the existing `BukanServerGudang` gate; `kd_barang` is typed by the operator (no derivable pattern) and can never be changed afterwards. The split with Update Harga is one sentence: **structure here, prices there** — `ubah_barang` never writes `harga_jual` on an existing row, because that would bypass `services.update_harga` (whole-rupiah validation, margin recompute, cache invalidation, `BarangUpdateLog`, `_sebar_harga` to 8 toko).
- `apps/transactions/laba_rugi.py` + `apps/inventory/services.nilai_persediaan` — **Laba Rugi**, replacing legacy `GetRekapHarian`. Read `context.md` § "Laba Rugi" before touching it. Two things decide everything here: the legacy function takes **171 s** (nested per-barang cursors), and its inventory valuation is **LIFO — prohibited by PSAK 14 / IAS 2** and prices opname-added stock at Rp 0. So this is deliberately **not** a faithful port: it values inventory at weighted average cost over cost-bearing inflows only (opening balance + net purchases − purchase returns), and **the screen carries a permanent banner saying the numbers will not match the old app**. Quantity is divisi-filtered, cost is not — that is what makes per-divisi statements sum exactly to the server total. A period entirely before the closing date raises `PeriodeTertutup` rather than being silently shifted forward the way legacy does. Never use `_purchase_prices()` for valuation: it divides both numerator and denominator by `bs.jumlah`, so it returns a price per *purchase* unit while the quantity multiplying it is in *base* units (proven 10.00× on `AMP013`) — that same defect inflates the `nominal` column on Stok Akhir, which is still unfixed.
- `apps/transactions/kas.py` — write path for `t_biaya_operasional`, `t_pendapatan`, `t_penambahan_kas`, `t_mutasi_kas`, modelled on `opname.py`. The engine is data-driven (`SPEC`/`FORM`/`LOOKUP` + a generic `kas/input/<jenis>` route), so a fourth cash document needed no new view or route. Note `kd_kas_tujuan` references `m_kas` despite its `varchar(10)`/`JR_KODE_ACCOUNT` type — three legacy views settle it; check `sys.sql_modules` before inferring column meaning from a schema.
- `apps/transactions/penjualan.py` + `transaksi.py` — the cashier write paths (nota, **penjualan order**, retur, pembelian), plus the cashier **info panel** reads (`info_customer` / `piutang_customer` / `histori_nota`, served by `{layar}/info-customer` and `{layar}/histori-user`). Those three reuse `reports._nota_net()` rather than restating the money formula, run without any date predicate, and push their filter *inside* it so the `(kd_customer, tanggal)` / `(kd_user, tanggal)` indexes actually filter — see `context.md` § "Panel info layar kasir". `transaksi.py` drives four screens from one `SPEC` dict (retur penjualan, pembelian, **order pembelian**, retur pembelian) — read `context.md` § "Order Pembelian" before touching that entry: its table is the only write target with **zero existing rows on every reachable server**, it spells the payment column `kd_jenis_bayar`, and unlike `t_penjualan_order` it **does** carry `insert_temp_m_*` triggers, so purchase orders reach the central sink the moment they are saved. Read `context.md` § "Layar kasir" before changing them — especially why the order prefix `OJ` must not come from `m_divisi.kepala_nota`, why an open order is marked by `no_transaksi = no_order` rather than `status`, and why `t_penjualan_order.tanggal_server` has to be written explicitly.
- `apps/transactions/opname.py` — **koreksi stok**, the only write path into `t_opname_stok` (screen: `/admin-panel/inventory/koreksi-stok`). Read `context.md` § "Koreksi Stok" before touching it — above all why it inserts **one row per `execute`**: `trig_update_stok_opname_stok` assigns scalars from `inserted`, so a multi-row INSERT moves stock for exactly one arbitrary row and the rest fail silently. Also: the four kinds (`0 Hilang / 1 Rusak / 2 Lain-Lain(+) / 3 Lain-Lain(-)`) are named by the legacy view `mon_t_opname_stok`, direction is never a separate choice because only `status = 2` adds stock, `kd_divisi` must be *chosen* (gudang has five divisi and all its opname lives in DAA001, not the first one), and the number prefix comes from that divisi's `kepala_nota`.
- `apps/transactions/cdc_sync.py` — optional reporting-replica sync via SQL Server CDC (see `context.md` § Reporting replica). `ServerProfile.report_source` + `core/mssql.get_report_source()` route report reads to the replica when configured; write paths always target the primary profile.
- `apps/transactions/harga_sync.py` — **near-realtime GUDANG → toko price propagation**, deliberately not feed-based: it compares `m_barang_satuan` directly (55,365 rows in 1.9 s), on its own 60-second thread, plus an instant push from the Arunika write path (`_sebar_harga` in `apps/monitoring/views.py`). Read `context.md` § "Harga GUDANG → toko" first — especially why the first sweep after restart must be a full one, and why `master._harga_map()` must not be used here.
- `apps/transactions/hub_pull.py` + `hub_master.py` — **how AMPHOREUS is filled now**: read the source tables directly, by date range, split into three tiers by `g_tutup_buku` (archive once / match daily / re-copy the last 7 days every tick). Replaces the feed-based `hub_sync`, which is no longer scheduled. Read `context.md` § "AMPHOREUS diisi tarik-langsung" before changing it — especially `bind_varchar()`: pyodbc binds `str` as NVARCHAR against `varchar` key columns, which silently turns a long `IN` list into one table scan per value (measured 6.23 s → 0.01 s for 50 values).
- `apps/transactions/hub_sync.py` + `hub_schema.py` — **AMPHOREUS**, our own central database (`SERVER-RETAIL`/`AMPHOREUS`) holding gudang + 8 grosir (retail is out of scope). Read `context.md` § AMPHOREUS before changing it: the hub schema is *generated* from a reference branch rather than hand-written, `kd_sumber` must lead every primary key (nothing in the legacy data identifies the source server, and `no_transaksi` collides across servers), detail tables deliberately have no PK, and detail rows are pulled by the *header* feed because some branches emit no detail feed at all.
- `apps/monitoring/services_sync.py` + `apps/transactions/feed_sync.py` — cross-server sync we own, alongside the legacy SQL Agent jobs in `scripts/job/` (which cannot be replaced: the central PHP/MySQL sink is not ours and the DB triggers belong to the legacy POS app). Read `context.md` § Sinkronisasi antar-server before touching either — it records why the change feed is `tbl_log_transaksi` and not `tbl_tmp_post`, why the `key__` prefix in `formatted_data` must not be ignored, and why `m_barang_divisi` and `m_supplier` are deliberately outside the allowlist. Supplier is a standing rule, not a tuning choice: gudang does the buying and holds the full supplier list, a toko server carries only its own handful (PAGESANGAN: 3 rows), so gudang → toko supplier fan-out is never correct. Gudang → AMPHOREUS still carries it (`hub_sync.SEED_TABLES`).

**MS SQL gotcha — key normalization.** SQL Server collation is case-insensitive and ignores trailing spaces; Python dict keys are not. When joining SQL result sets on `kd_*` keys in Python, normalize both sides with the `_k()` helper (see `apps/inventory/services.py`). Mismatched joins silently drop rows otherwise.

**Request pipeline (`config/settings.py` MIDDLEWARE):** `InertiaMiddleware` → `inertia_share` (lazy shared props: auth user, app name, active connection, flash) → `auth_required` (login gate) → `admin_network_guard` (guards `/admin-panel/*` **and** `/kasir/*`; access is decided by granted **menu**, not by role — the old role wall was removed because it rejected users before the menu check could run. When `ENFORCE_TAILSCALE=1`, `/admin-panel/*` additionally requires the client IP to be in `ADMIN_ALLOWED_NETWORKS` — the Tailscale CGNAT range plus any `ADMIN_EXTRA_CIDRS`. Client IP comes from `apps.core.http.client_ip`, which trusts `X-Forwarded-For` only from `TRUSTED_PROXIES`. This deployment deliberately runs with `ENFORCE_TAILSCALE=0` — see `PRODUCTION.md` § "Batas jaringan sengaja BUKAN lapisan pertahanan"). Shared props are lambdas so they're only evaluated on real Inertia responses.

**Routing.** `config/urls.py` mounts `apps.auth_app` at `/` and `apps.monitoring` + `apps.connections` under `/admin-panel/`. `apps/monitoring/views.py` holds most admin menu endpoints. RBAC roles: kasir / supervisor / admin / superadmin, with per-user `allowed_menu_keys`; menu definitions in `apps/core/menus.py`. Three menu flags override the per-user grants: `superadmin_only` (excluded from `assignable_menus()` entirely), `admin_only` (still grantable — admins are managed through Kelola Menu — but dropped by `menus_for()` for kasir/supervisor no matter what is checked), and `butuh_tautan` (the seven screens that WRITE to the legacy server, dropped when the account has no `TautanUser` for the *currently active connection* — superadmin included; derive the count from `KEYS_BUTUH_TAUTAN`, don't trust a number written in prose). All three are enforced in `menus_for()`, which `admin_network_guard` also reads, so a revoked menu cannot be reached by typing its URL — sub-paths included, via prefix matching. A `butuh_tautan` block says so explicitly (`middleware._pesan_tautan`, same wording as `tautan_wajib`) instead of the generic "menu not granted" message, which would send the user to Kelola Menu when the missing piece is in Kelola Tautan User. See `context.md` § "Tautan user legacy".

**Notifications are `ActivityLog`, scoped per account.** `apps/core/models.log_untuk(user)` is the one rule — own rows unless superadmin — shared by the dashboard card, the navbar bell (`nav/NotifMenu.vue`, shared prop `notif`), and `/admin-panel/logs`. Unread state is a single `User.notif_dibaca_at` timestamp; `POST /notif/baca` is mounted at the **root**, not under `/admin-panel`, because the Tailscale guard would otherwise kill the bell for exactly the shop-floor cashiers who see it most. Read `context.md` § "Notif per akun" before changing it.

**Field-level permissions (`User.hidden_data_keys`).** A second, independent axis: which *money values* a user may see (`harga_jual` / `harga_beli` / `nominal`), set alongside menus at `/admin-panel/menus`. Unlike `allowed_menu_keys` it is a **denylist** — empty means nothing is hidden, so unchecking every box hides everything instead of silently granting full access. Enforcement is server-side only: `_hidden_fields()` in `apps/monitoring/views.py` maps a permission to the field names, and the fields are dropped from the response before it leaves Django (`stock_index`, `stock_export`, `barang_histori_index`, `dashboard`). The Vue side (`useHiddenData.js`) only drops now-empty columns — it is cosmetic and must never be the sole guard.

Two traps here. (1) The Stok Akhir payload is cached **per profile, not per user**, so it must be filtered with `_tanpa_kolom()`, which returns a shallow copy; editing the cached object would strip the columns for everyone until the next warm. (2) Any new route serving the same data needs the same filter — the XLSX export did, and without it the restriction is decorative. Scope is now **every screen that shows money**: Stok Akhir, Barang Histori, Dashboard, the cashier info panel, all 23 server-side report specs, and the four bespoke views (Kas Harian, FMI Stok, Transaksi Barang, Master Produk). Mutasi Stok has no money column at all — it was listed as a gap by mistake. Laba Rugi is a special case: it is money end to end, so it refuses outright rather than rendering blank rows.

Bespoke views cannot use the name map, and that is not laziness: `masuk`/`keluar`/`total_masuk`/`total_keluar` are rupiah in Kas Harian but **quantities** in Mutasi Stok, Opname Stok, and Transaksi Barang, so registering those names would blank three reports that never mention money. They call `_uang_bespoke(request, <kolomnya sendiri>, kunci=...)`, which checks the **permission key** instead, and each screen names its own money columns (`_KAS_UANG`, `_FMI_STOK_UANG`, `_TRANSAKSI_UANG`). Master Produk uses `kunci="harga_jual"` because its column really is a selling price — an account that only revoked `nominal` still sees it, which is the point of having three separate keys.

Two traps these screens taught. (1) FMI Stok's Vue never renders `nilai_stok`, but the payload carried it anyway — "not on screen" is not a restriction, the row still reaches the browser. (2) A test that calls `_uang_bespoke()` directly proves the helper works, not that the view uses it: the first version stayed green when the filter was cut out of `kas_harian`. `apps/monitoring/test_uang_e2e.UangBespoke` therefore drives real HTTP requests with Inertia partial-reload headers and asserts on the JSON props.

Server-side report pages are covered **automatically, with no per-spec opt-in**: `_report_view` drops every hidden field name from rows *and* summary, and `_kolom_tanpa_uang()` drops them from export column lists (the export streams tuples, so there is no dict to filter). There used to be a `spec["money_fields"]` gate, and that opt-in shape *was* the bug — a report that forgot to declare kept sending rupiah, silently, twice: first the Klasifikasi Pelanggan export's second sheet (its money column is named `nilai`, not `total_belanja`), then every sales/purchase report plus Piutang Pelanggan. The policy now lives in exactly one place, `_FIELDS_BY_DATA_KEY`, so a new report inherits it without its author remembering anything.

Adding a money column therefore means **adding its name to `_FIELDS_BY_DATA_KEY`** — and `apps/monitoring/test_hidden_data.KolomRupiahTerdaftar` enforces it by scraping how the value is *rendered* (`format: "rupiah"` for table columns, `rp.format(s.x)` for summary cards) rather than trusting a hand-copied list. Summary keys must be scraped too: `total_sisa_piutang` leaked precisely because it only ever exists in the summary, never as a table column.

Two limits worth knowing before you assume a screen is covered. (1) A column named just `harga` is a selling price in Penjualan, a purchase price in Pembelian, and both at once in Transaksi Barang, so it sits under `nominal` only — an account that revokes *just* `harga_beli` still sees it. Fixing that needs column names that state their side, not another entry here. (2) Bespoke views (`kas_harian`, `fmi_stok`) are **not** covered at all; registering their names would achieve nothing since they never call the filter. They are listed in that test's `BELUM_TERTUTUP` so the gap stays visible instead of being mistaken for coverage.

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

All admin menus render real MS SQL data — `frontend/mock/*` has been deleted. Report pages come in two stacks that should not be mixed: the server-side stack (`ReportPage.vue` + `ServerTable.vue` + `useServerReport.js`; server pagination/sort/filter, XLSX export via the backend `/export` routes) used by `Reports/*`, `Promo/*`, `Cash/*`, `Analytics/*`, Opname, and TransaksiBarang; and the client-side stack (`ReportView.vue` + `DataTable.vue` + `useReportFilters.js`; in-browser sort/paginate, lazy-loaded SheetJS export) used by the inventory pages.

A server-side report is a `spec` dict fed to `_report_view` / `_report_export` (`apps/monitoring/views.py`). Optional keys, all defaulting to current behaviour so existing pages are unaffected: `max_range_days` (set `None` to lift the 92-day interactive clamp — only for pages asking about *history* rather than one period), `default_from_days` (relative default start date instead of month-start), `default_sort_dir` (`"asc"` when the default sort column is a priority rank, since desc buries the most urgent rows on the last page), and `filter_defaults` (echo effective values back into `filters` so a threshold box never renders blank while silently being applied). Klasifikasi Pelanggan uses all four and is the reference. There is deliberately **no** money-permission key here — money filtering is automatic, see the permissions section above.

There is a third shape, used by **Stok Akhir** and **Stok per Divisi**: columnar client-side (`useColumnarTable.js` + `BaseTable.vue`, fed by `inv.stok_akhir_kolumnar()` / `inv.stock_levels_kolumnar()`). Reach for it only when a page must search across a large dataset without round-trips — server pagination is the default and is simpler.

It exists because Stok Akhir shipped the whole ~55k-row barang×divisi universe as list-of-dict (15.6 MB JSON → 54,955 reactive Vue objects → 123 MB heap) and never finished loading on Firefox Android. The same rows column-major with a string dictionary are 4.65 MB and 25 MB heap (Stok per Divisi: 2.66 MB / 13 MB).

Rules if you touch it, each one bought by a measurement:

- The payload never enters `ref`/`reactive` — Vue proxying 55k entries was about half the original 123 MB.
- Never sort the *filtered* result. Sort the full index once per sort key and let filtering walk it in order; sorting per keystroke measured 1265 ms per character at 6× CPU throttle.
- The search box is debounced (`SEARCH_DEBOUNCE_MS`). One character triggers ~110k substring scans.
- Column kinds come from `payload.types`, set by `_kolumnar()` in `apps/inventory/services.py`. Do not sniff them from `typeof data[c][0]` — a numeric column holding one `null` then becomes a `Float64Array` full of `NaN` and the screen prints "NaN".
- Server-side, only *today* + *no divisi filter* is cached (`stok_kolumnar:<date>` / `divisi_kolumnar:<date>`) and warmed by the scheduler for the `is_default` profile only. Caching every date/divisi combination someone clicks would pile up 5 MB payloads in the Django process.
- On Stok per Divisi the divisi filter must stay a server round-trip: `stock_levels` aggregates differently with and without `kd_divisi`, so picking a divisi changes the numbers, not just which rows show. A CDC-based reporting replica (`apps/transactions/cdc_sync.py`, `report_source` on `ServerProfile`) exists but is parked — with `report_source` unset, reports read the primary directly. Follow the deferred convention above for any new page.
