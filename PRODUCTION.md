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
| `ENFORCE_TAILSCALE` | `1` (not DEBUG) | **`0` untuk deploy ini — disengaja.** Baca catatan di bawah sebelum menaikkannya. |
| `TAILSCALE_CIDR` | `100.64.0.0/10` | Tailscale CGNAT range. |
| `SESSION_IDLE_SECONDS` | `14400` (4h) | Session expiry. |
| `DJANGO_VITE_DEV` | `DEBUG` | Vite dev mode; `0` in prod. |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `0` | Set `1` when fronted by HTTPS (else cookies never send over plain-HTTP LAN → login breaks). |
| `SECURE_HSTS_SECONDS` | `0` | Set e.g. `31536000` only under HTTPS. |
| `TRUSTED_PROXIES` | *(kosong)* | **Wajib diisi kalau ada reverse proxy.** Kosong = `X-Forwarded-For` diabaikan. Lihat bagian HTTPS di bawah — proxy tanpa setelan ini MEMBUKA `/admin-panel`. |
| `TRUST_FORWARDED_PROTO` | `0` | `1` supaya `request.is_secure()` benar di belakang proxy TLS. |
| `SECURE_SSL_REDIRECT` | `0` | `1` hanya bila proxy melayani HTTPS **dan** `TRUST_FORWARDED_PROTO=1`, else redirect berputar. |
| `CSRF_TRUSTED_ORIGINS` | *(kosong)* | Wajib begitu HTTPS aktif, berskema penuh. Tanpa ini setiap form gagal "CSRF verification failed". |
| `STOK_SNAPSHOT_ENABLED` / `STOK_SNAPSHOT_HOUR` | `1` / `0` | Snapshot saldo stok untuk SEMUA server (dua lapis: base beku + live). `HOUR=0` = jalan saat server pertama kali hidup tiap hari (server toko cuma nyala jam kerja). |
| `STOK_SNAPSHOT_BASE_MONTHS` | `13` | Window immutable; live rebuild cukup scan sekian bulan terakhir, bukan seluruh histori. |

> **Catatan keamanan operasional:** `seed_dev` (password = username) menolak jalan saat `DEBUG=0`. Di produksi buat user & profil koneksi manual. Snapshot stok/harga jalan sendiri via scheduler in-process untuk **semua** profil selama server hidup (berurutan, per-profil terisolasi). `HOUR=0` supaya jalan di jam kerja (server toko mati saat dini hari). Untuk backfill awal / mesin yang sering mati, jalankan `manage.py snapshot_stok` (semua profil; `--base` untuk paksa base) / `manage.py snapshot_harga` manual atau lewat Windows Task Scheduler.

## Batas jaringan sengaja BUKAN lapisan pertahanan (keputusan 2026-08-09)

`ENFORCE_TAILSCALE=0`, dan itu pilihan sadar — bukan setelan yang lupa dinaikkan.

Aplikasi ini dipakai orang di lokasi: sebagian lewat Tailscale, sebagian dari LAN Gudang lewat
penerus port di SERVER-HIPRO. Tailscale dipakai untuk konektivitas peer-to-peer, bukan sebagai
gerbang. Yang menahan akses adalah **login, RBAC per-menu (ditegakkan di `menus_for()` yang juga
dibaca `admin_network_guard`, jadi URL yang diketik langsung ikut tertutup), gerbang
`butuh_tautan`, dan `hidden_data_keys`** — bukan alamat IP. `/kasir/*` memang tak pernah
dijaga jaringan sejak awal, dengan alasan yang sama.

**Kalau suatu hari ingin dinaikkan ke `1`, perbaiki dulu visibilitas IP-nya.** Selama penerus
port masih `netsh portproxy`, Django melihat alamat SERVER-HIPRO untuk semua orang yang lewat
sana. Alamat itu ada di `100.64.0.0/10`, jadi penjaganya akan:

- **meloloskan admin yang menguji dari Tailscale** — persis perilaku yang diharapkan, dan
- **meloloskan seluruh LAN Gudang bersamanya** — tanpa satu pun tanda.

Pengujiannya hijau justru karena yang menguji ada di sisi yang benar. Urutan yang benar: ganti
netsh dengan proxy HTTP (bagian berikutnya) → isi `TRUSTED_PROXIES` → daftarkan subnet LAN di
`ADMIN_EXTRA_CIDRS` → baru naikkan `ENFORCE_TAILSCALE`.

**Konsekuensi yang mengikuti keputusan ini:** karena jaringan tidak menahan apa pun, hak akses
database menjadi lapisan terakhir antara kompromi tingkat-aplikasi dan `DROP TABLE`. Selama
semua `ServerProfile` memakai login `sa`, lapisan itu tidak ada. Lihat `context.md` §"Hak akses"
— `arunika_app` naik dari "sebaiknya" jadi "satu-satunya".

## HTTPS di belakang reverse proxy

Tanpa ini, cookie sesi kasir melintas LAN toko sebagai teks polos — siapa pun di jaringan yang
sama bisa mengambilnya dan menulis nota atas nama kasir itu. `/kasir/*` sengaja tidak dijaga
penjaga Tailscale (kasir toko tidak ada di rentang CGNAT), jadi transport adalah satu-satunya
lapisan yang tersisa di sana.

**Urutannya penting.** Memasang proxy tanpa mengisi `TRUSTED_PROXIES` justru MEMBUKA
`/admin-panel` untuk semua orang: `REMOTE_ADDR` berubah jadi `127.0.0.1`, yang ada di
`ADMIN_IP_ALLOWLIST`, jadi `ENFORCE_TAILSCALE=1` lolos untuk setiap permintaan — tanpa galat,
tanpa jejak.

1. **Kunci waitress ke loopback** supaya proxy tak bisa dilewati:
   ```bash
   waitress-serve --threads=32 --listen=127.0.0.1:8000 config.wsgi:application
   ```
2. **Pasang proxy.** Caddy paling ringkas di Windows dan mengurus sertifikatnya sendiri; ia
   sudah mengirim `X-Forwarded-For` (menambahkan, bukan menimpa) dan `X-Forwarded-Proto`:
   ```
   namamesin.namatailnet.ts.net {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Pakai nginx/IIS? Pastikan keduanya terkirim: `X-Forwarded-For` dan `X-Forwarded-Proto`.
3. **Isi `.env`, semuanya sekaligus** — menyalakan sebagian bikin login patah tanpa pesan
   yang berguna:
   ```
   TRUSTED_PROXIES=127.0.0.1/32
   TRUST_FORWARDED_PROTO=1
   SESSION_COOKIE_SECURE=1
   CSRF_COOKIE_SECURE=1
   SECURE_SSL_REDIRECT=1
   SECURE_HSTS_SECONDS=31536000
   CSRF_TRUSTED_ORIGINS=https://namamesin.namatailnet.ts.net
   ```
4. **Verifikasi** — bukan "halamannya kebuka", tapi tiga hal yang bisa salah diam-diam:
   ```bash
   python manage.py check --deploy
   ```
   lalu, dengan `ENFORCE_TAILSCALE=1`, dari perangkat di LUAR Tailscale:
   ```bash
   curl -sk -o /dev/null -w "%{http_code}\n" -H "X-Forwarded-For: 100.64.0.1" https://namamesin.namatailnet.ts.net/admin-panel/dashboard
   ```
   Harus `403`. Kalau `200`, header palsunya dipercaya — periksa `TRUSTED_PROXIES`.
   Terakhir, buka Log Aktivitas: kolom IP harus berisi alamat perangkat yang sungguhan, bukan
   `127.0.0.1` untuk semua baris.

> `TRUST_FORWARDED_PROTO` sengaja terpisah dari `TRUSTED_PROXIES`. Django menerapkan
> `SECURE_PROXY_SSL_HEADER` tanpa memeriksa siapa pengirimnya, jadi ia hanya aman bila proxy
> benar-benar menimpa `X-Forwarded-Proto` di setiap permintaan.

### `netsh portproxy` bukan reverse proxy

Kalau penerusnya `netsh interface portproxy`, **tak satu pun setelan di atas ada gunanya** —
dan ini bukan hipotesis, ini yang terpasang di SERVER-HIPRO per 2026-08-09:

```
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=80 ^
    connectaddress=server-toys.echidna-carob.ts.net connectport=8000
```

`portproxy` meneruskan **TCP mentah**. Ia tidak membaca HTTP, jadi:

- **tidak ada `X-Forwarded-For`** — `TRUSTED_PROXIES` tak punya apa pun untuk dibaca;
- **tidak bisa TLS** — jadi `SESSION_COOKIE_SECURE` dkk. tak akan pernah bisa dinyalakan;
- **IP asli hilang untuk semua orang.** Django melihat alamat mesin penerus. Karena mesin itu
  ada di Tailscale, `ENFORCE_TAILSCALE=1` justru **meloloskan siapa pun yang lewat sana** —
  penjaga yang terlihat menyala tapi tak menjaga apa-apa.

Dua akibat yang sudah terasa tanpa menunggu urusan keamanan: kolom IP di Log Aktivitas seragam
untuk semua orang, dan kunci throttle login menyatu.

**Gantinya Caddy di mesin yang sama**, satu berkas `Caddyfile`:

```
:80 {
    reverse_proxy server-toys.echidna-carob.ts.net:8000
}
```

Caddy mengirim `X-Forwarded-For` + `X-Forwarded-Proto` sendiri. Sesudah itu barulah
`TRUSTED_PROXIES` (IP Tailscale mesin penerus, `/32`) dan `ADMIN_EXTRA_CIDRS` (subnet LAN yang
memang diizinkan) punya arti. Untuk HTTPS, tambahkan nama yang punya sertifikat — `tailscale
cert` untuk nama tailnet mesin itu, atau CA internal untuk nama LAN-nya.

## Cadangan (WAJIB — tak ada salinan lain)

`db.sqlite3` adalah satu-satunya tempat akun, hak menu, **tautan user legacy per koneksi**,
audit trail, cursor sync, dan password koneksi terenkripsi disimpan. Data bisnis aman di MS
SQL; yang di sini tidak punya cadangan di mana pun. Tautan user khususnya adalah pekerjaan
manual belasan baris per orang yang tak bisa direkonstruksi dari server mana pun.

```bash
python manage.py backup_db --dir D:\backup\arunika --keep-days 30
```

Jadwalkan harian lewat Windows Task Scheduler. Perintah ini memakai `VACUUM INTO`, bukan
menyalin berkasnya — pada mode WAL, menyalin `db.sqlite3` saat server hidup menghasilkan
salinan yang kehilangan transaksi yang belum ter-checkpoint.

**`POS_FERNET_KEY` tidak ikut tercadang, dan harus disalin terpisah.** Tanpa kuncinya, ke-14
password koneksi di dalam cadangan tetap terenkripsi selamanya — cadangan yang lengkap tapi
tak bisa dipakai memulihkan apa pun.

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
Rare (WAL + SESSION_SAVE_EVERY_REQUEST=False mitigate). Restart layanannya. **Jangan menghapus
`db.sqlite3-wal` / `db.sqlite3-shm`** — pada mode WAL kedua berkas itu memuat transaksi yang
sudah ter-commit tapi belum ter-checkpoint, jadi menghapusnya membuang data yang sudah
tersimpan (akun, tautan user, log) tanpa satu pun peringatan. Kalau memang perlu memaksa
checkpoint: `python manage.py dbshell` lalu `PRAGMA wal_checkpoint(TRUNCATE);`.

**Vite manifest.json not found**:
Ran `npm run build`? Static files collected? Check `frontend/dist/` and `staticfiles/` exist.
