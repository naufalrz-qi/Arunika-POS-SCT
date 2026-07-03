# Plan: Tulis `planing/backend_plan.md` (playbook backend + integrasi frontend)

## Context

User punya `planing/prd.md` (spek produk) dan `planing/frontend_plan.md` + `planing/frontend_tasks.md` (playbook frontend untuk model rendah — Haiku 4.5 / Gemini Flash 3, berisi kode penuh siap paste). Yang belum ada: sisi backend. Frontend_tasks.md eksplisit berkata "Backend endpoints are built separately" dan mendefinisikan PROP CONTRACT yang backend wajib penuhi.

Deliverable: **satu file `planing/backend_plan.md`** (keputusan user: 1 dokumen, kode penuh siap paste), format playbook seperti `frontend_tasks.md` — instruksi bahasa Inggris, task berurutan dengan checkbox, kode Python/SQL lengkap per task, DoD per task, kontrak integrasi frontend eksplisit. Tidak ada perubahan kode aplikasi pada fase ini — hanya menulis dokumen planning.

## Fakta hasil eksplorasi (grounding dokumen)

- **Semua URL halaman mock sudah terdaftar.** `apps/monitoring/views.py:466-552` — factory `_mock_page(component)` render `props={}` untuk 15 halaman (8 laporan penjualan/pembelian, opname, fmi ×2, promo, voucher, kas, shift). Kerja backend = ganti assignment `penjualan_all = _mock_page(...)` dst. jadi fungsi view real deferred. URL path sudah persis cocok kontrak frontend (`/admin-panel/laporan/penjualan`, `/admin-panel/kas/harian`, dst.).
- **Pola view deferred referensi**: `barang_histori_index` (`views.py:370`) — nested `load_x()`, `pyodbc.Error → conn_error` Indonesia, `defer(load_x)`, `filters` echo. Helper existing: `_active()`, `_parse_date()`, `_eod()`, `CONN_ERROR`.
- **Services existing**: `core/mssql.py` (`cursor(profile)` context manager, `get_active_profile()` auto-trigger `ensure_indexes_async`), `apps/inventory/services.py` (`_k()`, `_cached()` TTL 600s, movement engine, `list_divisi`, `stok_akhir_per_tanggal`, `stock_levels`), `apps/master_data/services.py` (`list_products/customers`, `update_harga`, `compare_harga_jual`, `sync_harga_jual`, `MAX_ROWS=500`), `apps/core/models.py` (`ActivityLog`, `log_activity`).
- **Index registry**: `apps/transactions/indexes.py` — dict `INDEXES {name: DDL}`, `ensure_indexes` idempotent (cek `sys.indexes`), `ensure_indexes_async` (thread daemon, dedup `(host,port,db_name)`), baru 6 index tanggal. PRD §9 minta ekspansi.
- **Belum ada**: helper pagination server-side (OFFSET/FETCH + COUNT), library XLSX di requirements.txt (openpyxl absen), model `SyncRun`/`SyncRunItem`, menu key `supplier` & `sync_history`, endpoint export.
- **Menu**: `apps/core/menus.py` — semua key halaman sudah ada kecuali 2 baru. `menus_for(user)` drive nav frontend otomatis.
- **RBAC**: `admin_network_guard` middleware sudah melindungi `/admin-panel/*`; tidak perlu guard baru per view.

## Kontrak integrasi frontend (dari frontend_tasks.md — backend wajib match persis)

1. **Halaman server-side** (deferred prop **`report`**): `{ rows, total, summary, options, conn_error }` + prop **`filters`** echo `{ date_from, date_to, ..., search, sort, sort_dir, page, per_page }`. Query params masuk via GET; `per_page` default 50.
2. **Halaman client-side** (deferred prop **`data`**): `{ rows, conn_error }`.
3. **Nama field row per halaman** harus sama dengan `columns[].key` di frontend_tasks.md T9–T32 (mis. PenjualanAll: `no_transaksi, tanggal, customer, barang, qty, harga, subtotal`; Kas: `_rid, tanggal, kas, keterangan, masuk, keluar, saldo`; SyncHistory: `id, created_at, user, src, dst, mode, total_items, status, items[]`).
4. **Export**: `GET <url>/export?<query sama>` → file XLSX.
5. **Options dropdown**: `report.options.divisi/customer/supplier/kas/user` = `[{value,label}]`.
6. **Menu key baru**: `supplier` (href `/admin-panel/master/suppliers`), `sync_history` (href `/admin-panel/master/sync-history`), section `master` — nav frontend muncul otomatis.

## Struktur `planing/backend_plan.md` yang akan ditulis

Header: audience (AI model rendah), companion docs, aturan "Instructions in English, UI/error strings Indonesian".

- **SECTION 0 — RULES**: hanya sentuh file backend (Python) + `requirements.txt`; jangan sentuh `frontend/` kecuali disebut; kerjakan berurutan; jangan mengarang nama prop/URL; wajib `_k()` saat join dict Python; jangan pakai kolom `total` computed-UDF (`t_penjualan_detail`) — selalu hitung `qty × harga × (1−d1/100)(1−d2/100)(1−d3/100)(1−d4/100)`; semua query transaksi wajib predikat tanggal (default bulan berjalan, tolak rentang > 3 bulan untuk halaman detail); parameterized query (`?`) selalu; sort whitelist dict per report (anti-injection); tiap task selesai → jalankan check yang disebut di DoD.
- **Referensi R1–R4** (paste-ready): R1 API helper existing (`mssql.cursor`, `_active`, `CONN_ERROR`, `_parse_date/_eod`, `defer/render`, `log_activity`, `_k`, `_cached`); R2 bentuk payload server/client + filters echo; R3 tabel URL ↔ view ↔ komponen ↔ deferred prop ↔ frontend task number; R4 rumus diskon berjenjang + aturan `g_tutup_buku`.
- **SECTION 1 — FOUNDATION** (≈4 task):
  - B1: tambah `openpyxl` ke `requirements.txt`.
  - B2: CREATE `apps/core/reporting.py` — helper generik full code: `parse_report_params(request, default_sort, allowed_sorts)` (validasi tanggal, default bulan berjalan, clamp per_page 10–200), `paginate(cur, base_sql, params, order_by, page, per_page)` (COUNT + OFFSET/FETCH), `xlsx_response(filename, columns, rows)` (openpyxl write_only, hard cap `EXPORT_CAP=100_000`), `opt(rows, value_key, label_key)` → `[{value,label}]`.
  - B3: EDIT `apps/transactions/indexes.py` — REPLACE dict `INDEXES` dengan registry penuh PRD §9 (paste-ready: composite `(kd_divisi,tanggal)`, `(kd_customer,tanggal)`, `(kd_user,tanggal)` di `t_penjualan`; `(no_transaksi)`, `(kd_barang)` di tabel detail; index kas; `m_barang(kd_kategori)`, `m_barang(nama)`, `m_customer(nama)`); env `POS_AUTO_INDEX` (default 1) dicek di `ensure_indexes_async`; hasil sukses/gagal per index dicatat `ActivityLog`.
  - B4: EDIT `apps/connections/views.py` — `connections_save` juga memanggil `ensure_indexes_async(profile)` saat profil baru dibuat (trigger registrasi, PRD §9).
- **SECTION 2 — PILOT (Penjualan Detail)** (≈3 task): CREATE `apps/transactions/reports.py` (service `penjualan_detail(profile, f)` — SQL penuh JOIN header⋈detail⋈m_barang⋈m_customer, WHERE dinamis, summary query, sort whitelist); EDIT `apps/monitoring/views.py` ganti `penjualan_all` jadi view deferred real + view `penjualan_all_export`; EDIT `apps/monitoring/urls.py` tambah path `laporan/penjualan/export`. Unblocks frontend T9.
- **SECTION 3 — SISA LAPORAN SERVER-SIDE** (≈9 task, satu per halaman): penjualan-nota, penjualan-customer, penjualan-user, penjualan-periode (granularitas harian/bulanan), retur-penjualan, pembelian, retur-pembelian, opname (`t_opname_stok⋈t_opname_proses`, kolom selisih), shift. Tiap task: fungsi service SQL penuh + view + export + URL. Pola copy dari pilot; bagian berubah ditandai.
- **SECTION 4 — KAS HARIAN** (task terpisah karena saldo berjalan): fetch semua baris rentang terfilter (UNION `t_mutasi_kas`/`t_penambahan_kas`/`t_biaya_operasional`/`t_pendapatan`/penjualan tunai), saldo awal dari `m_kas.saldo_awal` + mutasi sebelum `date_from`, hitung saldo berjalan di Python, `_rid` sintetis, paginasi slice Python (rentang divalidasi ≤ 3 bulan sehingga aman).
- **SECTION 5 — HALAMAN CLIENT-SIDE** (≈5 task, deferred prop `data`): promo (`m_barang_promo(_detail)`, status dari rentang tanggal+jam), voucher (`m_voucher` + agregat pemakaian `t_penjualan.kd_voucher`), fmi-penjualan (agregat per barang, ambang FAST/MEDIUM/SLOW konstanta service), fmi-stok (fmi ⋈ stok akhir movement engine → Kritis/Sehat/Overstock), master supplier (service `list_suppliers` di `apps/master_data/services.py` pola `list_customers`, view + URL `master/suppliers`).
- **SECTION 6 — SYNC HISTORY** (≈3 task): model `SyncRun`/`SyncRunItem` di `apps/master_data/models.py` (skema PRD §8, SQLite only) + migrasi; EDIT `sync_harga_apply` — buat run status `pending` + item per baris (harga lama dari `compare_harga_jual` data yang dikirim frontend) sebelum commit MSSQL, update `ok/gagal` sesudahnya; view `sync_history_index` (rows + nested `items`) + URL `master/sync-history`. Unblocks frontend T32.
- **SECTION 7 — MENUS & LOGS** (≈2 task): EDIT `apps/core/menus.py` tambah key `supplier` + `sync_history` (section master); EDIT `logs_index` tambah filter aksi/user/tanggal via query params + export XLSX.
- **SECTION 8 — VERIFIKASI FINAL**: checklist — `python manage.py check` bersih; `python manage.py migrate` jalan; `python manage.py check_stock_agg` lulus; `python manage.py test` lulus; grep `_mock_page` = 0 pemakaian; smoke test per halaman Mode B (skeleton → data, filter reload, pagination request baru, export unduh); cek `sys.indexes` profil baru.

Setiap task diberi label "**Unblocks frontend T<n>**" agar dua playbook bisa dieksekusi paralel dan sinkron.

## Keputusan desain yang dibakukan di dokumen

- **Model Sync history di `apps/master_data`** (bukan app baru) — app sudah terdaftar, cukup models.py + migrasi; PRD mengizinkan keduanya.
- **openpyxl mode `write_only`** untuk export besar (hemat memori), hard cap 100 ribu baris (konstanta `EXPORT_CAP`).
- **Sort whitelist** = dict `{param: "sql expr"}` per report; param di luar dict → fallback default sort. Tidak pernah interpolasi input user ke SQL.
- **Validasi rentang tanggal** di `parse_report_params`: kosong → bulan berjalan; > 92 hari untuk laporan detail → dipotong + `conn_error` berisi peringatan (bukan exception, halaman tetap render).
- **Options dropdown** dari master cache (`_cached`): divisi/kas/user penuh; customer/supplier `status=1` cap 1.000 baris urut nama.
- **Summary** = query agregat terpisah dengan WHERE sama (bukan agregasi Python atas satu halaman).

## File yang akan dibuat/diubah pada fase eksekusi plan ini

- CREATE: `planing/backend_plan.md` (satu-satunya file; dokumen ± besar, berisi kode penuh per task).

## Verifikasi (setelah menulis dokumen)

1. Cross-check tiap PROP CONTRACT di frontend_tasks.md (T9–T32) punya task backend padanan dengan field row identik — tabel R3 jadi matriks pemeriksaan.
2. Cross-check semua URL di dokumen vs `apps/monitoring/urls.py` existing (path sudah ada; hanya `/export`, `master/suppliers`, `master/sync-history` yang baru).
3. Pastikan tiap task punya: CREATE/EDIT + path file eksak + kode penuh + DoD + perintah check (`python manage.py check` minimal).
4. Baca ulang dokumen dengan kacamata "model rendah": tidak ada instruksi yang mengandaikan konteks di luar dokumen + file referensi yang disebut.