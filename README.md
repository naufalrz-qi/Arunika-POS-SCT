# Arunika POS — Sukses Crown Toys

POS multi-server. **Django + Inertia.js + Vue 3 + Vite + Pinia + Tailwind v4**, data dari **MS SQL Server legacy** (grosir/gudang/retail). Admin panel: dashboard, monitoring stok, laporan penjualan/pembelian, master data, koneksi multi-server.

Dokumen lain: `PRODUCTION.md` (deploy Windows), `context.md` + `implementation_plan.md` (status & rencana lanjutan).

## Prasyarat

- **Python 3.11+**
- **Node.js 18+**
- **ODBC Driver 17 for SQL Server** ([download Microsoft](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server))
- Akses ke MS SQL Server (data toko)

## Setup (sekali)

```bash
# 1. Python venv + dependencies
python -m venv venv
.\venv\Scripts\activate            # Windows (PowerShell/CMD)
pip install -r requirements.txt

# 2. Frontend dependencies
npm install

# 3. Konfigurasi environment
copy .env.example .env             # lalu isi .env (lihat di bawah)
python manage.py generate_key      # → salin output ke POS_FERNET_KEY di .env

# 4. DB lokal (SQLite: auth, sesi, log, profil koneksi)
python manage.py migrate
python manage.py seed_dev          # opsional: user admin + koneksi grosir dev
```

### Isi `.env` (minimum)

Lihat `.env.example` untuk semua opsi + dokumentasi. Yang wajib:

```ini
POS_FERNET_KEY=<hasil generate_key>
POS_DB_GROSIR_HOST=<host MS SQL>
POS_DB_GROSIR_PORT=1433
POS_DB_GROSIR_NAME=<nama database>
POS_DB_GROSIR_USER=sa
POS_DB_GROSIR_PASSWORD=<password>
ALLOWED_HOSTS=127.0.0.1,localhost   # + IP LAN / hostname Tailscale bila akses lintas device
```

> Windows: JANGAN edit `.env` pakai `Set-Content -Encoding utf8` (bikin BOM yang merusak key pertama). Edit manual di editor.

## Menjalankan

Dua mode. Pilih sesuai kebutuhan.

### Mode A — Dev / hot-reload (akses lokal saja)

Edit frontend langsung ke-refresh. **Hanya bisa dari mesin ini (`localhost`)**, tidak dari device lain.

`.env`: `DJANGO_VITE_DEV=1`. Buka **dua terminal**:

```bash
# Terminal 1 — Vite HMR
npm run dev

# Terminal 2 — Django
.\venv\Scripts\activate
python manage.py runserver
```

Buka <http://127.0.0.1:8000>.

### Mode B — Akses lintas device (LAN / Tailscale)

Django serve aset hasil build dari origin-nya sendiri. Bisa diakses device lain via IP/hostname. **Tidak ada hot-reload** — rebuild tiap ubah frontend.

`.env`: `DJANGO_VITE_DEV=0`. Pastikan `ALLOWED_HOSTS` memuat IP/hostname yang dipakai.

```bash
npm run build                              # WAJIB tiap kali frontend berubah
.\venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000    # dengar di semua interface
```

Akses dari device lain: `http://<ip-atau-hostname>:8000` (mis. `http://phrolova.echidna-carob.ts.net:8000`).

### Produksi (Windows, banyak request)

Pakai **waitress** (bukan runserver). Detail di `PRODUCTION.md`:

```bash
npm run build
python manage.py collectstatic --noinput
python manage.py runserver              # sekali, untuk migrate bila perlu
waitress-serve --threads=32 --listen=0.0.0.0:8000 config.wsgi:application
```

## Perintah `manage.py`

| Perintah | Fungsi |
|---|---|
| `generate_key` | Generate `POS_FERNET_KEY` (enkripsi password koneksi) |
| `seed_dev` | Seed user admin + profil koneksi grosir dev |
| `ensure_indexes` | Buat index report/stok di MS SQL (idempoten; juga auto per koneksi) |
| `check_stock_agg` | Self-check: agregasi stok SQL vs Python (koneksi aktif) |

## Struktur

- `config/` — settings, urls, wsgi
- `core/mssql.py` — koneksi MS SQL (pool, timeout, profil aktif)
- `apps/core/` — middleware (`inertia_share`, auth, network guard), menu, http helper
- `apps/auth_app/` — login/logout (bcrypt + sesi SQLite)
- `apps/monitoring/` — view semua menu admin
- `apps/inventory/` — service stok (movement engine, cache)
- `apps/transactions/` — service dashboard/laporan + auto-index
- `apps/master_data/` — produk, pelanggan, update harga, sync
- `apps/connections/` — Connection Manager (profil MS SQL + test)
- `frontend/` — Vue `pages/`, `layouts/`, `components/`, `stores/`, `composables/`

## Troubleshooting

- **UI tak muncul dari device lain / `ERR_CONNECTION_REFUSED localhost:5173`** → pakai Mode B (`DJANGO_VITE_DEV=0` + `npm run build`). Mode dev hardcode `localhost:5173`.
- **`Blocked request ... not allowed`** → tambah host ke `ALLOWED_HOSTS` di `.env`.
- **Data koneksi kosong / kolom kosong** → cek koneksi aktif di navbar; koneksi pertama kali lambat (build index background + cache master 10 mnt).
- **Port 8000 dipakai** → `Get-NetTCPConnection -LocalPort 8000 | Stop-Process` (lihat `PRODUCTION.md`).
