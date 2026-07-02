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
| `DEBUG` | `1` (true) | Set to `0` in production. |
| `SECRET_KEY` | `django-insecure-...` (dev fallback) | **Must set in production.** Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost,192.168.1.10,100.64.0.1` | Comma-separated IPs. |
| `ENFORCE_TAILSCALE` | `1` (not DEBUG) | Restrict `/admin-panel/*` to Tailscale IPs. |
| `TAILSCALE_CIDR` | `100.64.0.0/10` | Tailscale CGNAT range. |
| `SESSION_IDLE_SECONDS` | `14400` (4h) | Session expiry. |
| `DJANGO_VITE_DEV` | `DEBUG` | Vite dev mode; `0` in prod. |

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
