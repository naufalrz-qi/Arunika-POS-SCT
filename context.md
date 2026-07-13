# Context — Arunika POS (Sukses Crown Toys)

Ringkasan arsitektur + status untuk planning lanjutan. Django + Inertia.js + Vue 3, data dari MS SQL Server legacy (multi-server: grosir/gudang/retail).

## Stack & jalan

- Backend: Django 5 (`config/settings.py`), Inertia-Django 1.2 (`defer`/`optional` tersedia), pyodbc → MS SQL "ODBC Driver 17".
- Frontend: Vue 3.5 + `@inertiajs/vue3` 2.0 (punya komponen `<Deferred>`), Pinia, Tailwind 4, Vite 6. Build: `npm run build` → `frontend/dist/`.
- DB Django (auth/config/log/session): SQLite `db.sqlite3` (WAL aktif).
- 1 koneksi MS SQL aktif global (bukan per-tipe), switcher di navbar. `core/mssql.get_active_profile()`.
- Opsional: tiap `ServerProfile` bisa punya `report_source` (server replica untuk laporan, disinkron via CDC — lihat bagian "Reporting replica" di bawah). `core/mssql.get_report_source(profile)`.

### Mode serving (PENTING — lintas device)
- **Dev/HMR (lokal saja)**: `.env` `DJANGO_VITE_DEV=1`, jalankan `npm run dev` + runserver, akses `localhost:8000`. Vite hardcode `localhost:5173` → TIDAK bisa dari device lain.
- **Prod-asset (lintas device/Tailscale)**: `.env` `DJANGO_VITE_DEV=0` + `npm run build`, Django serve aset dari origin sendiri (`:8000/static/assets/...`). Akses dari device manapun yang bisa jangkau `:8000`. **Setelah tiap edit frontend wajib `npm run build`.**
- Produksi Windows: `waitress-serve --threads=32 --listen=0.0.0.0:8000 config.wsgi:application` (1 proses → cache per-proses konsisten). Lihat `PRODUCTION.md`.

## Peta menu (28) → sumber data

Route prefix `/admin-panel/`. View di `apps/monitoring/views.py` (kecuali connections di `apps/connections/views.py`). Menu def: `apps/core/menus.py`.

**SEMUA 28 menu sudah REAL** (migrasi Fase 3-7 selesai) — `frontend/mock/*.js` sudah dihapus total, tidak ada lagi import `@/mock` di `frontend/pages`. Laporan penjualan/pembelian pakai `apps/transactions/reports.py` (SQL builder per laporan + pagination server-side + export XLSX via `openpyxl`).
Catatan: route `master/suppliers` dan `master/sync-history` (`apps/monitoring/urls.py`) sudah ada view-nya tapi BELUM terdaftar di `apps/core/menus.py` — halaman ada tapi tak muncul di nav sampai menu key ditambahkan.

## Service backend (reusable)

`apps/transactions/services.py`: `dashboard_summary(profile, day=None)`. Helper `_f`, `_dictify`.

`apps/transactions/reports.py`: SQL builder generik per laporan (`penjualan_detail`, `penjualan_nota`, `penjualan_customer`, `penjualan_user`, `penjualan_periode`, `retur_penjualan`, `pembelian`, `retur_pembelian`, `opname`, `kas`, `shift`, `promo`, `voucher`, `fmi_penjualan`, `fmi_stok`) — tiap fungsi terima dict filter `f`, return `(inner_sql, params)` untuk dibungkus pagination di `apps/core/reporting.py`.

`apps/core/reporting.py`: `parse_report_params(request, sorts, default_sort, max_range_days=MAX_RANGE_DAYS)` (validasi tanggal, default bulan berjalan, tolak rentang > `max_range_days`), `run_paged(cur, inner_sql, params, f)` / `run_all(cur, inner_sql, params, f)` (COUNT + OFFSET/FETCH vs tanpa paging), `xlsx_response(filename, columns, rows)` (openpyxl), `opt(rows, value_key, label_key)` → `[{value,label}]`.

`apps/inventory/services.py` (movement engine, raw tables):
- `_movement_sql` (9-way UNION ALL: t_penjualan/pembelian(+retur), t_mutasi_stok, t_opname_stok, dll).
- `_movement_sums` — agregasi DI SQL (GROUP BY + HAVING buang serba-nol). **JANGAN stream jutaan row ke Python.**
- `_k(kd)` — normalisasi key (strip+upper) untuk collation CI. `_cached(profile,name,build)` TTL 600s. `invalidate_master_cache(profile_id)`.
- Public: `list_divisi`, `search_barang`, `stock_card`, `stock_levels(profile,kd_divisi,date_from,date_to,search,kd_kategori)`, `stok_akhir_per_tanggal(profile,tanggal,kd_divisi)`, `barang_histori(...)`.

`apps/master_data/services.py`: `list_products`, `list_categories`, `list_customers`, `list_barang_edit`, `update_harga`(write), `update_status`(write), `compare_harga_jual`, `sync_harga_jual`(write). Semua cap TOP 500.

## Reporting replica (CDC, opsional)

Laporan berat (`penjualan_detail` dkk, join ke `t_penjualan_detail` 3M+ baris) tadinya SELECT langsung ke server legacy — bersaing lock dengan transaksi kasir live, dan lambat (~1 menit). Solusi opsional: `ServerProfile.report_source` menunjuk ke server SQL Server kedua yang disinkron dari legacy via **Change Data Capture** (bukan transactional replication biasa — `t_penjualan_detail` adalah heap tanpa primary key karena computed column `total` dibuat dengan ANSI_NULLS/QUOTED_IDENTIFIER salah; CDC `fn_cdc_get_all_changes_*` tidak butuh PK, replication butuh).

- `apps/transactions/cdc_sync.py`: `CDC_TABLE_SPECS` (tabel → capture instance + key), `backfill_table()` (copy penuh awal), `sync_table()`/`sync_all()` (incremental by LSN, resumable via `apps/core/models.CdcSyncCursor`). Tabel header (`t_penjualan`, `m_barang`, dst.) di-upsert per baris by key asli; tabel detail tanpa key andal (`t_penjualan_detail`, dst.) disinkron dengan re-fetch seluruh baris current milik parent (`no_transaksi`/`no_retur`) yang berubah — bukan cocokkan baris satu-satu.
- `manage.py sync_cdc [--profile ID] [--backfill]` — jalankan `--backfill` sekali (atau saat rebuild replica), lalu jadwalkan tanpa `--backfill` tiap 1-2 menit (Task Scheduler di Windows; tidak ada Celery/task queue di stack ini).
- `apps/monitoring/views.py` `_report_view`/`_report_export`: baca via `mssql.get_report_source(profile) or profile` — otomatis pakai replica kalau `report_source` diset, fallback ke legacy kalau belum. Jalur WRITE (`update_harga`, `sync_entity`, dst.) TIDAK pernah pakai `report_source` — selalu ke `profile` langsung.
- **Prasyarat di server legacy (kerjaan DBA, bukan kode)**: `EXEC sys.sp_cdc_enable_db;` lalu `sys.sp_cdc_enable_table` per tabel di `CDC_TABLE_SPECS` (nama capture instance default `dbo_<table>`, sesuaikan dict kalau DBA pakai nama custom). Replica butuh skema tabel yang sama, disiapkan manual di server kedua.
- Staleness: laporan dari replica bisa lag ~1-2 menit dari transaksi terbaru (tergantung jadwal `sync_cdc`) — trade-off sadar demi tidak membebani legacy server, bukan bug.

## Perubahan harga harian (snapshot diff-only)

Harga bisa diubah langsung di POS/server tanpa lewat aplikasi ini (`BarangUpdateLog` cuma menangkap perubahan lewat aplikasi). Untuk memantau semua perubahan harga per hari: `manage.py snapshot_harga [--profile ID] [--prune-days N]` membaca `m_barang_satuan` server (reuse `master._harga_map`) dan membandingkannya dengan baseline tersimpan di SQLite.

- Diff-only, bukan snapshot penuh: `apps/core/models.BarangHargaState` menyimpan harga terkini per SKU (di-update di tempat, ukuran tetap ~jumlah SKU × server), `BarangHargaChange` hanya diisi saat harga beda (append-only, tumbuh ∝ jumlah perubahan). Menghindari ledakan baris kalau full-snapshot 54rb produk × hari.
- Idempotent: run kedua di hari sama tanpa perubahan → 0 baris. SKU baru → seed state tanpa log.
- Default target = koneksi aktif (`mssql.get_active_profile()`); `--profile` untuk server lain. `--prune-days` untuk retensi log.
- **Penjadwalan: in-process, tak perlu Task Scheduler.** `apps/core/scheduler.py` `start_scheduler()` dipanggil dari `config/wsgi.py` (hanya ke-load saat serving via runserver/waitress, bukan saat `migrate`/`shell`). Daemon thread cek tiap `HARGA_SNAPSHOT_INTERVAL_SECONDS` (default 30 mnt) dan jalan **sekali per hari kalender** untuk koneksi aktif, dijaga penanda `HargaSnapshotRun` per (profile, tanggal). Server mati seharian → hari itu dilewati (sesuai maksud "saat server berjalan saja"). Env: `HARGA_SNAPSHOT_ENABLED` (default 1), `HARGA_SNAPSHOT_HOUR` (default 0 = kesempatan pertama tiap hari). `manage.py snapshot_harga` tetap ada untuk manual/one-off atau kalau mau pakai Task Scheduler.
- Tampil di halaman **Pergerakan Harga** (`pergerakan_harga_index` → `PergerakanHarga.vue`), default perubahan HARI INI dengan toggle "Semua Riwayat", filter tanggal/kode/koneksi + info "snapshot terakhir". Halaman yang sama punya tab **Saran Harga**: seluruh katalog server terpilih yang harga jual satuan dasarnya beda dari nominal di `keterangan` (`master.list_saran_harga`, padanan server-side dari parser di UpdateBarang.vue), bisa diterapkan per baris/massal (endpoint `harga-bulk`) dan dibuka di modal edit yang sama dengan Update Barang (`BarangEditModal.vue` + endpoint `update-barang/detail`). Edit/terapkan hanya aktif bila baris berasal dari koneksi aktif — endpoint tulis selalu menulis ke koneksi aktif server-side.

## Tabel legacy tersedia (sudah dicek di server aktif)

`m_barang`, `m_barang_satuan`, `m_barang_promo`(+`_detail`), `m_barang_divisi_diskon`, `m_voucher`, `m_kas`, `m_customer`, `m_supplier`, `m_divisi`, `m_kategori`, `m_pegawai`.
`t_penjualan`(+`_detail`,`_retur`,`_retur_detail`), `t_pembelian`(+`_detail`,`_retur`,`_retur_detail`), `t_opname_stok`, `t_mutasi_stok`, `t_mutasi_kas`, `t_penambahan_kas`, `t_pegawai_ganti_shift`(+`_detail`), `t_absensi`, `g_tutup_buku`.
Kolom asli WAJIB dicek via INFORMATION_SCHEMA sebelum tulis SQL (nama kolom legacy tak standar).

## Gotcha / aturan wajib

- **Collation CI**: SQL Server anggap `'LYG005'`=`'lyg005'` & abaikan trailing space; dict Python tidak. Semua join key `kd_*` di Python WAJIB `_k()`.
- **Tanpa view/UDF/SP legacy** (PRD §5.3) — query langsung tabel, parameterized.
- **Agregasi di SQL**, bukan Python (movement bisa jutaan row).
- **Indexing**: auto-ensured per koneksi aktif/registrasi (`apps/transactions/indexes.py`, hook di `get_active_profile` + `connections_save`), bisa dimatikan via env `POS_AUTO_INDEX=0`. Hasil dicatat `ActivityLog`. Tombol "Cek Indexing" manual di halaman Kelola Server (`Admin/Connections/Index.vue`) untuk re-check on-demand + lihat status per index — pelengkap, bukan pengganti auto-trigger. `ensure_indexes()` return `(failed, results)`.
- **.env Windows**: jangan `Set-Content -Encoding utf8` (bikin BOM rusak key pertama & mojibake). Pakai append UTF-8 tanpa BOM.
- **Inertia POST = JSON**: `request.POST` kosong; baca via `apps/core/http.get_data()`.
- **Tutup buku** server aktif lama (mis. Lotim 2024-01-12) → movement besar; sarankan klien tutup buku untuk percepat.
- **Cache TTL bersama** (`core/cache.py`, `_cached`/`invalidate_master_cache`, 600s) dipakai `apps/inventory/services.py` DAN `apps/master_data/services.py` — satu dict, satu invalidasi. JANGAN cache kolom yang berubah tiap transaksi kasir (mis. `m_barang_stok_akhir`) atau query bertingkat search-term (key bisa membengkak).
- **Filter tanggal report/listing**: dorong ke SQL (`WHERE tanggal >= ?`) kalau fungsinya tak perlu histori sebelum `date_from` untuk saldo berjalan (lihat `barang_histori` vs `stock_card` di `apps/inventory/services.py`) — jangan tarik semua baris ke Python lalu buang.
- **Filter/fetch halaman Inventory** (`Stock.vue`, `BarangHistori.vue`): pakai `frontend/composables/useReportFilters.js` + `frontend/components/report/DateRangeFilter.vue`, jangan hand-roll `reactive`+`router.get` lagi. Halaman laporan (`ReportView`) punya pola pagination server-side sendiri di `apps/core/reporting.py` — jangan campur dua pola ini.
- **No `v-html`/dynamic `<component :is>`** dari string backend untuk konten sel laporan — pakai slot `cell-<key>` yang sudah ada di `DataTable.vue`.

## Scalability (Fase 0 SUDAH dikerjakan)

Target 200–500 request. Sudah: `waitress`+`whitenoise` (requirements), env-driven DEBUG/SECRET_KEY/ALLOWED_HOSTS, `GZipMiddleware` (payload 5MB→~500KB), `SESSION_SAVE_EVERY_REQUEST=False` (killer #1 SQLite), SQLite WAL (`connection_created` signal), `conn.timeout=60` di `core/mssql.py`. `pyodbc.pooling=True` sudah ada.
Sisa (di luar scope sekarang): Redis/multi-proses, pagination server-side ReportView, HTTPS/reverse proxy.

## Pola deferred (shell dulu, data menyusul) — SUDAH TERBUKTI

View: bungkus kerja berat dalam fungsi, `props={"key": defer(fn)}`. Frontend: `<Deferred data="key">` + `#fallback` `<LoadingCard>`. Contoh live: `stock_index`+`Stock.vue`, `dashboard`+`Dashboard.vue`, `barang_histori_index`+`BarangHistori.vue`.
`ReportView.vue` OWN `AdminLayout` → untuk 13 halaman ReportView, `<Deferred>` harus di DALAM ReportView (title/filter tetap instan). Lihat implementation_plan.md.

## Progress implementasi

- ✅ Fase 0–6: semua 28 menu real (`frontend/mock/*` sudah dihapus), pagination server-side + export XLSX di laporan, indexing diperluas (~30 index) + audit trail `ActivityLog`, redesign UI ("mecha" theme, token warna `rx-red`/`rx-yellow` di `frontend/css/main.css`).
- ⬜ Fase 7: verifikasi + load test — commit terakhir sebelum sesi ini ("Frontend, backend, masih error mwahaha") mengindikasikan masih ada bug runtime belum diselesaikan setelah redesign UI; belum diverifikasi `npm run build` bersih di kondisi terbaru.
- ⬜ Menu key `supplier`/`sync_history` belum ditambahkan ke `apps/core/menus.py` walau view/route sudah ada.
- 🔶 Fase 8 (opsional, performa — lihat "Reporting replica" di atas): kode sisi app (`report_source`, `cdc_sync.py`, `sync_cdc`, wiring `_report_view`) sudah ada di branch `feature/cdc-reporting-replica`, teruji lewat Django check + smoke test lokal (fungsi CDC SQL Server-nya sendiri tidak bisa diuji tanpa server asli). Belum dikerjakan: enable CDC di server legacy (DBA), siapkan skema di server kedua, `--backfill` awal, dan verifikasi end-to-end (load test, cocokkan angka replica vs legacy).

## Di luar scope

Write master Produk/Pelanggan (stub tetap), Redis, pagination server-side, HTTPS.
