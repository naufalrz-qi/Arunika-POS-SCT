# Production Deployment (Windows)

## Setup

1. **Install Python venv + dependencies:**
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   npm install
   ```

2. **Build frontend:**
   ```bash
   npm run build
   ```

3. **Collect static files:**
   ```bash
   .\venv\Scripts\python.exe manage.py collectstatic --noinput
   ```

## Run (single-process multi-threaded)

```bash
npm run build  # rebuild frontend dist if needed
.\venv\Scripts\python.exe manage.py collectstatic --noinput
.\venv\Scripts\waitress-serve --threads=32 --listen=0.0.0.0:8000 config.wsgi:application
```

Adjust `--threads=32` per machine CPU cores (rule of thumb: 2–4× cores).

## Environment Variables (prod)

Set these in the shell or `.env` before running:

| Var | Default | Note |
|-----|---------|------|
| `DEBUG` | `0` (false) | Secure default. Set `1` only for dev. |
| `SECRET_KEY` | `django-insecure-...` (dev fallback) | **Must set in production.** With `DEBUG=0` the app REFUSES TO BOOT while the dev key is in place. Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated IPs; add LAN/Tailscale hosts. |
| `ENFORCE_TAILSCALE` | `1` (not DEBUG) | **WAJIB `1` di produksi** — membatasi `/admin-panel/*` ke range Tailscale. Jangan set `0` di server produksi. |
| `TAILSCALE_CIDR` | `100.64.0.0/10` | Tailscale CGNAT range. |
| `SESSION_IDLE_SECONDS` | `14400` (4h) | Session expiry. |
| `DJANGO_VITE_DEV` | `DEBUG` | Vite dev mode; `0` in prod. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `0` | Set `1` when fronted by HTTPS (else cookies never send over plain-HTTP LAN → login breaks). |
| `SECURE_HSTS_SECONDS` | `0` | Set e.g. `31536000` only under HTTPS. |
| `STOK_SNAPSHOT_ENABLED` / `STOK_SNAPSHOT_HOUR` | `1` / `0` | Snapshot saldo stok untuk SEMUA server (dua lapis: base beku + live). `HOUR=0` = jalan saat server pertama kali hidup tiap hari (server toko cuma nyala jam kerja). |
| `STOK_SNAPSHOT_BASE_MONTHS` | `13` | Window immutable; live rebuild cukup scan sekian bulan terakhir, bukan seluruh histori. |

> **Catatan keamanan operasional:** `seed_dev` (password = username) menolak jalan saat `DEBUG=0`. Di produksi buat user & profil koneksi manual. Snapshot stok/harga jalan sendiri via scheduler in-process untuk **semua** profil selama server hidup (berurutan, per-profil terisolasi). `HOUR=0` supaya jalan di jam kerja (server toko mati saat dini hari). Untuk backfill awal / mesin yang sering mati, jalankan `manage.py snapshot_stok` (semua profil; `--base` untuk paksa base) / `manage.py snapshot_harga` manual atau lewat Windows Task Scheduler.

## Performance (scaling to 200–500 req/s)

- **GZipMiddleware**: Reports ~5MB → ~500KB (5–8 ms overhead).
- **SQLite WAL**: Readers don't block writers; concurrent SELECTs work.
- **SESSION_SAVE_EVERY_REQUEST = False**: Writes only on session change, not every request.
- **Deferred props**: Heavy data fetched async post-render (spinner shown to user).
- **Master data cache (10 min TTL)**: 54k product rows fetched once per process, reused.

## Troubleshooting

**"Address already in use"** (port 8000):
```bash
Get-NetTCPConnection -LocalPort 8000 -ErrorAction Stop | Where-Object {$_.State -eq 'Listen'} | Foreach-Object {Stop-Process -Id $_.OwningProcess -Force}
```

**SQLite "database is locked"**:
Rare (WAL + SESSION_SAVE_EVERY_REQUEST=False mitigate); if it happens, restart the service or delete `db.sqlite3-wal` and `db.sqlite3-shm` and rebuild the DB.

**Vite manifest.json not found**:
Ran `npm run build`? Static files collected? Check `frontend/dist/` and `staticfiles/` exist.
