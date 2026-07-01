# Arunika POS — Frontend Phase (Admin)

POS multi-server (Django + Inertia.js + Vue 3 + Vite + Pinia + Tailwind v4).
This phase ships the **Admin panel UI with mock data** — no MS SQL connection
and no real auth yet (see `prd.md` and the project plan).

## Prasyarat

- **Python 3.11+** (belum terpasang di mesin ini — install dulu)
- **Node.js 18+** (tersedia: v24)

## Menjalankan (dev)

Buka **dua terminal**.

**Terminal 1 — Vite (frontend HMR):**
```bash
npm install
npm run dev
```

**Terminal 2 — Django:**
```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate          # buat tabel sessions (SQLite)
python manage.py runserver
```

Buka <http://127.0.0.1:8000/login> → tekan **Masuk** (stub) → dashboard Admin.

## Struktur

- `config/` — settings, urls, wsgi
- `apps/core/` — `inertia_share` middleware (auth/menu/flash stub)
- `apps/auth_app/` — login/logout (stub)
- `apps/monitoring/` — dashboard, users, master data, logs + `mock_data.py`
- `apps/connections/` — Connection Manager (mock + Test Connection)
- `frontend/` — Vue pages (`pages/`), `layouts/`, `components/`, `stores/`

## Build produksi (cek frontend)

```bash
npm run build   # menghasilkan frontend/dist/manifest.json
```

## Fase berikutnya

Sambungkan props mock ke service layer MS SQL, auth bcrypt + sesi SQLite,
middleware RBAC + validasi IP Tailscale, lalu halaman Kasir & Supervisor.
