# Implementation Plan — Semua Menu Real + Deferred + Scalable

Baca `context.md` dulu. Target: 17 menu mock → real MS SQL; tiap halaman render shell dulu, data menyusul (`defer`); siap 200–500 request. Kerjakan per fase, build+verifikasi tiap fase, commit tiap fase.

## Aturan eksekusi (wajib)

1. Sebelum tulis SQL tabel baru: cek kolom via INFORMATION_SCHEMA (script bawah). Nama kolom legacy tak standar.
2. Agregasi & filter DI SQL, parameterized (`?`), tanpa view/UDF. Join key `kd_*` di Python → `_k()`.
3. Filter tanggal server-side WAJIB (default bulan berjalan) → payload bounded.
4. Tiap data berat → `defer`. Frontend → `<Deferred>` + `<LoadingCard>`.
5. Setelah edit frontend: `npm run build`. Cek: `.\venv\Scripts\python.exe manage.py check`.
6. Angka konsisten: total penjualan_all 1 hari == omzet dashboard hari itu.

### Cek kolom tabel (jalankan via Bash + venv python)
```python
# scratchpad script; ganti NAMA_TABEL
import os, django; os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
from dotenv import load_dotenv; load_dotenv(r"D:\Project\ArunikaPOSDjango\.env")
django.setup()
from core import mssql
p = mssql.get_active_profile()
with mssql.cursor(p) as cur:
    cur.execute("SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? ORDER BY ORDINAL_POSITION", ["NAMA_TABEL"])
    print([(r[0],r[1]) for r in cur.fetchall()])
```

## ============ PATTERN A — halaman ReportView (13 halaman) ============

Berlaku: penjualan_all, penjualan_nota, penjualan_customer, penjualan_user, retur_penjualan, pembelian, retur_pembelian, stok_divisi, stok_akhir, opname, fmi_penjualan, fmi_stok, promo, voucher, kas, shift (SEMUA kecuali penjualan_periode).

### Langkah 0 (SEKALI): ubah `ReportView.vue` agar defer di dalam AdminLayout
Tambah props + region deferred. `ReportView` sudah render `<AdminLayout :title>`; title+filter tetap instan, hanya toolbar+tabel yang menunggu data.
- Tambah prop: `deferData: { type: String, default: null }`, `loadingMessage: { type: String, default: "Mengambil data…" }`.
- Import `LoadingCard` + `Deferred`.
- Di template, bungkus blok toolbar+`<DataTable>` (baris ~66–90): jika `deferData` di-set → `<Deferred :data="deferData"><template #fallback><LoadingCard :message="loadingMessage"/></template> …toolbar+table… </Deferred>`; else render langsung (backward-compatible untuk halaman non-defer bila ada). Banner `connError` + `#filters` slot tetap DI LUAR Deferred (instan).

### Langkah 1: view (backend `apps/monitoring/views.py`)
Ganti baris `X = _mock_page("Admin/...")` jadi fungsi. Template:
```python
def penjualan_all(request):
    date_from = _parse_date(request.GET.get("date_from")) or _month_start()
    date_to = _parse_date(request.GET.get("date_to")) or dt.datetime.now()
    def load():
        profile = _active()
        rows, conn_error = [], None
        if profile:
            try:
                rows = tx.laporan_penjualan_all(profile, date_from=date_from, date_to=_eod(date_to))
            except pyodbc.Error as exc:
                conn_error = f"Gagal: {exc.args[-1] if exc.args else exc}"
        else:
            conn_error = CONN_ERROR
        return {"rows": rows, "conn_error": conn_error}
    return render(request, "Admin/Reports/PenjualanAll", props={
        "report": defer(load),
        "filters": {"date_from": request.GET.get("date_from",""), "date_to": request.GET.get("date_to","")},
    })
```
Helper `_month_start()` (tambah di views bila belum ada): `dt.datetime.now().replace(day=1,hour=0,minute=0,second=0,microsecond=0)`. Sudah ada: `_active`, `_parse_date`, `_eod`, `CONN_ERROR`, `defer` (import dari inertia).

### Langkah 2: frontend (`frontend/pages/Admin/.../X.vue`)
- HAPUS `import { xxx } from "@/mock/...";`.
- `const props = defineProps({ report: { type: Object, default: null }, filters: { type: Object, default: () => ({}) } });`
- `columns` array TETAP (itu kontrak).
- Template: `<ReportView ... :rows="report?.rows || []" defer-data="report" :conn-error="report?.conn_error" />` (title/columns/search-keys/export-name TETAP).
- Filter tanggal opsional via `#filters` slot (Input type=date + tombol `router.get(path, params, {preserveState:true})`).

### Konsistensi prop key stok_divisi/stok_akhir
View mereka sudah pakai key `data`. Samakan ke `report` (edit view: `"data"`→`"report"`) agar Pattern A seragam, ATAU frontend pakai `defer-data="data"`. Pilih `report` untuk seragam.

## ============ PATTERN B — halaman custom (penjualan_periode) ============
Chart page, bukan ReportView. Ikuti `Dashboard.vue`: page own `<AdminLayout>`, `<Deferred data="report">` DI DALAM, `#fallback` `<LoadingCard>`, `computed` unwrap. View `defer` bundle `{harian, bulanan, conn_error}`.

## ============ Fase 2 — selesaikan stok_divisi & stok_akhir (frontend) ============
View sudah real. Konversi `StokDivisi.vue` + `StokAkhir.vue` via Pattern A (drop mock, `defer-data`, `:rows`, `:conn-error`). Divisi list untuk filter: ada di bundle (`inv.list_divisi`). Verifikasi kolom cocok shape mock lama.

## ============ Fase 3 — 8 laporan penjualan/pembelian ============
Service baru di `apps/transactions/services.py` (pakai `_dictify`/`_f`; join `_k()`). Cek kolom tiap tabel dulu.

| menu | view | service baru | sumber | bentuk | kolom (dari mock page) |
|---|---|---|---|---|---|
| penjualan_all | Reports/PenjualanAll | laporan_penjualan_all | t_penjualan⨝_detail⨝m_customer/m_divisi | detail per baris | no_transaksi,tanggal,divisi,customer,kota,barang,qty,satuan,harga,diskon,harga_bersih,total |
| penjualan_nota | Reports/PenjualanNota | laporan_penjualan_nota | idem | GROUP BY no_transaksi | (lihat mock PenjualanNota) |
| penjualan_customer | Reports/PenjualanCustomer | laporan_penjualan_customer | idem⨝m_customer | GROUP BY customer | (mock) |
| penjualan_user | Reports/PenjualanUser | laporan_penjualan_user | idem (kolom user/kasir header) | GROUP BY user | (mock) |
| retur_penjualan | Reports/ReturPenjualan | laporan_retur_penjualan | t_penjualan_retur⨝_detail | detail periode | (mock) |
| pembelian | Reports/Pembelian | laporan_pembelian | t_pembelian⨝_detail⨝m_supplier | detail periode | (mock) |
| retur_pembelian | Reports/ReturPembelian | laporan_retur_pembelian | t_pembelian_retur⨝_detail | detail periode | (mock) |
| penjualan_periode | Reports/PenjualanPeriode | laporan_penjualan_periode | t_penjualan | agg harian+bulanan (Pattern B) | (mock penjualanBulanan/Harian) |

Verifikasi angka: penjualan_all 1 hari == `dashboard_summary` omzet.

## ============ Fase 4 — Opname ============
Service `apps/inventory/services.py` `laporan_opname(profile, date_from, date_to, kd_divisi)`: `t_opname_stok`(+detail bila ada)⨝m_barang (nama, `_k()`). Frontend `Opname.vue` Pattern A.

## ============ Fase 5 — FMI (analitik) ============
- `fmi_penjualan`: ranking fast-moving dari `t_penjualan_detail` (SUM qty & omzet per barang, periode, GROUP BY + TOP N). Service di `transactions/services.py`.
- `fmi_stok`: turnover — qty terjual periode vs stok akhir (reuse `_movement_sums`) per barang.

## ============ Fase 6 — Promo, Voucher, Kas, Shift ============
Cek kolom dulu (tabel: `m_barang_promo`+`_detail`, `m_barang_divisi_diskon`, `m_voucher`, `m_kas`, `t_mutasi_kas`, `t_penambahan_kas`, `t_pegawai_ganti_shift`+`_detail`, `m_pegawai`).
- promo → m_barang_promo(+detail) + m_barang_divisi_diskon (list promo aktif + range tanggal + harga/diskon).
- voucher → m_voucher (kode, nominal, masa berlaku, status).
- kas → m_kas + t_mutasi_kas + t_penambahan_kas (mutasi periode + saldo).
- shift → t_pegawai_ganti_shift(+detail) + m_pegawai (shift per pegawai/tanggal).
Service di `apps/transactions/services.py` atau modul baru `apps/transactions/reports.py` bila membengkak. Frontend Pattern A.

## ============ Fase 7 — Verifikasi & load test ============
1. `npm run build` + `manage.py check` lulus.
2. Smoke browser (chrome-devtools MCP): klik 28 menu — shell+spinner dulu, data masuk. `manage.py check_stock_agg` lulus. penjualan_all vs dashboard cocok.
3. Load test: script Python (ThreadPoolExecutor, login session, GET campuran dashboard/stok/laporan) 200 lalu 500 concurrent ke **waitress** (bukan runserver). Catat p95 + error rate. Target: 0 error 5xx / `database is locked`.
4. Setelah semua page lepas mock → hapus `frontend/mock/*.js`.

## File utama
- `frontend/components/report/ReportView.vue` (Langkah 0, sekali).
- `apps/monitoring/views.py` (15 view stub → real+defer).
- `apps/transactions/services.py` (+ mungkin `reports.py`) — service laporan.
- `apps/inventory/services.py` (opname; reuse yang ada).
- `frontend/pages/Admin/**` (17 page: drop mock, Pattern A/B), `frontend/components/ui/LoadingCard.vue` (sudah ada).
- Hapus `frontend/mock/*.js` di akhir.

## Commit per fase
`git add -A; git commit -m "Fase N: <ringkas>"` (branch `main` OK; user commit manual bila mau). Co-author trailer sesuai konvensi.
