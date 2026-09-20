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
| `POS_APP_DB_HOST` / `_NAME` | *(wajib)* | Basis data pangkal. Diperiksa saat boot; tanpa keduanya aplikasi menolak start. |
| `POS_APP_DB_PORT` / `_USER` / `_PASSWORD` | `1433` / kosong / kosong | USER kosong = autentikasi Windows. |
| `POS_APP_DB_DRIVER` / `_EXTRA` | Driver 17 / `Encrypt=yes;TrustServerCertificate=yes` | Disamakan dengan jalur pyodbc di `core/mssql.py`. |
| `POS_APP_DB_TEST_NAME` | `test_<NAME>` | Database yang dibuat `manage.py test`. |
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

## Basis data pangkal: MS SQL, dan hanya itu

Basis data pangkal (akun, sesi, `ServerProfile`, `TautanUser`, `ActivityLog`, cursor sync,
snapshot) tinggal di sebuah database MS SQL yang alamatnya ada di `.env` (`POS_APP_DB_*`).
Pemasangan ini memakai `the_nameless` di instans mesin aplikasi.

Alamatnya sengaja dari `.env`, bukan dari `ServerProfile` seperti server bisnis. Alasannya
melingkar: `ServerProfile` justru yang menyimpan cara menyambung ke server-server itu, dan ia
tinggal DI DALAM pangkal — jadi pangkal harus bisa dibaca lebih dulu tanpa profil apa pun.
Karena itu pula pangkal tidak didaftarkan sebagai profil koneksi: setiap pekerjaan yang
menyapu "semua profil" (snapshot stok, sync health, sumber transfer) akan ikut menyentuhnya.

SQLite sudah dihapus seluruhnya, termasuk untuk `manage.py test`. Alasannya bukan
keseragaman: SQLite menganggap dua NULL berbeda di unique constraint dan tidak menegakkan
panjang kolom sama sekali, jadi baris yang mustahil ada di MS SQL hidup bertahun-tahun tanpa
gejala — dan tak satu pun test bisa menangkapnya selama test-nya sendiri jalan di SQLite.
Keduanya benar-benar ditemukan saat pemindahan (satu `ActivityLog.detail` 505 karakter di
kolom 255, dan tiga pasang baris snapshot ber-`profile` NULL).

> **Kalau server pangkal mati, tak ada yang bisa login.** Karena itu ia instans di mesin
> aplikasi sendiri, bukan server jauh lewat Tailscale.

Collation-nya mengikuti `model` instans, di sini `SQL_Latin1_General_CP1_CI_AS` — **tidak peka
huruf besar/kecil**, tak seperti SQLite. Sesudah pindah, `superadmin` dan `SUPERADMIN` adalah
akun yang sama.

### Pindah dari pemasangan SQLite lama (sekali, saat cutover)

`manage.py pindah_pangkal` yang mengerjakannya: ia membaca berkas SQLite READ-ONLY dan menulis
dengan `bulk_create` berbatch. `loaddata` tidak dipakai karena menyimpan satu objek per
`save()` — 778.916 baris `BarangHargaState` lewat jalur itu butuh berjam-jam; perintah ini
memindahkan 810 ribu baris dalam ±3 menit.

Yang dijaga perintah itu dan tidak akan Anda lihat kalau dikerjakan tangan: cap waktu
`auto_now`/`auto_now_add` tidak ditimpa jam migrasi, primary key asli bertahan, urutan foreign
key tak jadi soal (penjagaan constraint dimatikan lalu **divalidasi ulang eksplisit**), dan
benih IDENTITY di-reseed supaya insert pertama tidak menabrak pk lama.

1. Hentikan waitress. Pastikan tak ada proses yang memegang `db.sqlite3`.
2. **Masih dengan kode lama** (yang jalur SQLite-nya belum dihapus):
   `python manage.py backup_db --dir D:\backup\arunika`.
   Berkas `db-YYYYMMDD.sqlite3` itu sekaligus artefak rollback dan sumber salin yang bersih —
   `VACUUM INTO` selalu menghasilkan berkas ter-checkpoint, sementara `db.sqlite3` hidup masih
   punya `-wal` dan tak bisa dibuka read-only. Salin berkas itu **dan `.env`**
   (`POS_FERNET_KEY`!) ke luar mesin.
3. Di SQL Server: `CREATE DATABASE [the_nameless];` tanpa klausa `COLLATE`, lalu
   `ALTER DATABASE [the_nameless] SET RECOVERY SIMPLE;`
4. Isi `POS_APP_DB_*` di `.env`, hapus baris `POS_APP_DB_ENGINE`, dan pastikan `BACKUP_DIR_HUB`
   menunjuk folder yang BERBEDA dari `BACKUP_DIR` (lihat catatan di bagian Cadangan).
5. `python manage.py migrate`, lalu `python manage.py migrate --check` harus diam.
6. Praperiksa dulu, baru pindahkan:

```bash
python manage.py pindah_pangkal --sumber D:\backup\arunika\db-20260918.sqlite3 --periksa-saja
```

```bash
python manage.py pindah_pangkal --sumber D:\backup\arunika\db-20260918.sqlite3 --perbaiki
```

`--perbaiki` hanya memotong nilai yang melebihi `max_length`, dan melaporkan tiap
pemotongannya. Ia tidak pernah menghapus baris: kunci unik yang kembar harus dibereskan di
sumbernya (migrasi `core.0017` sudah melakukannya untuk ketiga tabel snapshot).

Perintahnya berhenti dan menolak menyalin kalau targetnya sudah berisi — tak ada mode
lanjut-separuh. Kalau gagal di tengah: `DROP DATABASE`, buat ulang, `migrate`, ulangi.

**Gerbang sebelum menyalakan layanan.** Perintah itu memverifikasi sendiri dan menolak diam:
jumlah baris per model sumber vs target, `check_constraints()` (FK + ISJSON + CHECK >= 0),
benih IDENTITY, `TautanUser` beserta pasangannya, dan bahwa ke-14 password profil bisa
didekripsi dengan `POS_FERNET_KEY` yang aktif. `TautanUser` yang paling mahal: kalau
jumlahnya berkurang, tujuh layar kasir yang menulis akan menolak jalan, dan barisnya tidak
bisa dibuat ulang dari server mana pun.

7. Nyalakan waitress. Login, lalu periksa Kelola Tautan User, ganti koneksi di navbar, Log
   Aktivitas, Riwayat Operasi, dan Kesehatan Sync. Terakhir buka Cadangan & Pemulihan →
   **Cadangkan pangkal** → **Verifikasi** baris yang baru dibuat: itu satu-satunya bukti
   ujung-ke-ujung bahwa cadangan pangkal di jalur MS SQL benar-benar bisa dibaca kembali.
8. Tugas Task Scheduler `backup_db` sekarang menulis berkasnya lewat **akun layanan SQL
   Server**, bukan akun yang menjalankan perintah. Folder tujuannya harus bisa ditulis akun
   itu — kalau tidak, foldernya tinggal kosong dan tak ada yang memberi tahu.

**Rollback** kapan pun sebelum langkah 7 selesai: hentikan waitress, kembalikan `.env` lama,
pakai lagi `db.sqlite3` bersama kode versi sebelumnya. Berkas SQLite tak pernah ditulis
sepanjang proses ini.

## Cadangan (WAJIB — tak ada salinan lain)

Basis data aplikasi adalah satu-satunya tempat akun, hak menu, **tautan user legacy per
koneksi**, audit trail, cursor sync, dan password koneksi terenkripsi disimpan. Data bisnis
aman di MS SQL; yang di sini tidak punya cadangan di mana pun.

```bash
python manage.py backup_db --dir D:\backup\arunika --keep-days 30
```

Jadwalkan harian lewat Windows Task Scheduler. Isinya `BACKUP DATABASE ... WITH INIT,
CHECKSUM`, dan ada satu hal yang mudah menjebak: **berkasnya ditulis di mesin SQL Server,
bukan di mesin yang menjalankan perintah ini**. `--dir` diartikan oleh SQL Server, akun
layanannya yang harus punya izin tulis di sana, dan kalau folder itu tak terjangkau dari mesin
ini, pemangkasan retensi dilewati — perintahnya mengatakan begitu. `COMPRESSION` sengaja tidak
dipakai karena SQL Server Express tidak mendukungnya.

Mesin selain MS SQL **ditolak dengan galat**, bukan dilewati diam-diam — cadangan yang gagal
tanpa suara persis sama buruknya dengan tidak ada cadangan.

> **`BACKUP_DIR_HUB` harus berbeda dari `BACKUP_DIR`.** Sejak cadangan pangkal juga berkas
> `.bak`, keduanya memakai pola nama yang sama (`db-YYYYMMDD.bak`). Dengan folder yang sama —
> dan `BACKUP_DIR_HUB` kosong memang berarti "ikut `BACKUP_DIR`" — layar menampilkan dua baris
> ber-path identik, dan kalau folder itu suatu saat dipetakan sebagai share UNC, pemangkasan
> retensi pangkal akan menghapus cadangan AMPHOREUS.

**`POS_FERNET_KEY` tidak ikut tercadang, dan harus disalin terpisah.** Tanpa kuncinya, ke-14
password koneksi di dalam cadangan tetap terenkripsi selamanya — cadangan yang lengkap tapi
tak bisa dipakai memulihkan apa pun.

### Layar Cadangan & Pemulihan

`/admin-panel/pengaturan/cadangan` (superadmin) menampilkan seluruh berkas cadangan yang
tercatat — termasuk yang dibuat Task Scheduler, bukan hanya yang dipicu dari web — beserta
ukuran, umur, dan hasil verifikasinya. Dua tombol: **Cadangkan pangkal** dan **Cadangkan
AMPHOREUS**.

**AMPHOREUS sekarang ikut dicadangkan**, dan sampai sekarang ia tidak punya cadangan apa pun.
Ia database milik kita sendiri; kalau hilang, pemulihannya berarti menjalankan ulang tarik
arsip berjam-jam untuk sembilan cabang. Foldernya diatur `BACKUP_DIR_HUB` (kosong = ikut
`BACKUP_DIR`) dan **diartikan oleh mesin SQL Server yang menampungnya**.

Ke-14 server legacy **tidak** dicadangkan dari sini, dan tidak bisa dijadikan sasaran: fungsi
cadangan AMPHOREUS tidak menerima parameter profil sama sekali — sasarannya ditentukan
`HUB_NAME`, bukan input.

**Verifikasi** memeriksa apakah berkasnya benar-benar terbaca kembali dengan
`RESTORE VERIFYONLY ... WITH CHECKSUM`, **di instans yang menulisnya**: cadangan pangkal lewat
koneksi Django sendiri, cadangan AMPHOREUS lewat profil hub. Itu bukan kerapian: berkas `.bak`
hanya terbaca oleh instans yang membuatnya, jadi memverifikasi cadangan pangkal lewat instans
AMPHOREUS akan melaporkan cadangan yang sehat sebagai rusak. `VERIFYONLY` tidak memulihkan apa
pun dan tidak menyentuh database mana pun, tapi ia **butuh izin setingkat `CREATE DATABASE`**
pada instansnya; kalau akunnya tak punya, hasilnya tampil sebagai gagal dengan pesan
pyodbc-nya, bukan diam. Checksum halaman
baru bisa diperiksa karena backup kini ditulis `WITH INIT, CHECKSUM` — tanpa itu
`VERIFYONLY` hanya memeriksa header dan akan bilang "ok" pada berkas yang halamannya rusak.

Tiga keadaan verifikasi, bukan dua: **belum** bukan **gagal**.

## Pemulihan (runbook)

Aplikasi ini **tidak punya tombol restore**, dan itu keputusan sadar: proses yang menjalankan
restore pangkal adalah proses yang sedang memegang koneksi ke database yang ditimpanya, dan
gagal di tengah berarti tak seorang pun bisa login — termasuk untuk membetulkannya.
`apps/core/test_cadangan.TidakAdaJalurRestore` menjaga invarian itu dengan memindai seluruh
kode dan menolak `RESTORE DATABASE` di mana pun kecuali sebagai teks runbook.

Teks lengkapnya ada di **satu tempat**, `apps/core/cadangan.RUNBOOK`, dan tampil di layar
Cadangan & Pemulihan dengan tombol Salin. Ringkasnya:

1. **Kunci dulu, baru database.** `POS_FERNET_KEY` tidak ada di cadangan mana pun.
2. **Pangkal** — hentikan waitress dulu (RESTORE menolak berjalan selama masih ada koneksi),
   `RESTORE ... WITH REPLACE, RECOVERY` di SSMS, lalu `manage.py migrate --check`.
3. **AMPHOREUS** — restore, lalu `manage.py pull_hub --mode segar --hari 30`. Tarik arsip tak
   perlu diulang selama `HubPullState` ikut pulih bersama pangkal — penanda `arsip_sampai` ada
   di sana, bukan di AMPHOREUS.

Sesudah pemulihan apa pun, buka **Kesehatan Sync**: blok Penjadwal harus menunjukkan tick
utama hidup, dan blok Pusat AMPHOREUS harus memuat sembilan cabang. Blok pusat yang hilang
berarti profil `AMPHOREUS` atau `kode_sumber` cabang belum ikut pulih.

## Performance (scaling to 200–500 req/s)

- **GZipMiddleware**: Reports ~5MB → ~500KB (5–8 ms overhead).
- **READ UNCOMMITTED untuk laporan** (`core/mssql.report_cursor`): kueri berat tak mengambil
  shared lock yang memblok kasir menulis.
- **SESSION_SAVE_EVERY_REQUEST = False**: Writes only on session change, not every request.
- **Deferred props**: Heavy data fetched async post-render (spinner shown to user).
- **Master data cache (10 min TTL)**: 54k product rows fetched once per process, reused.

## Troubleshooting

**"Address already in use"** (port 8000):
```bash
Get-NetTCPConnection -LocalPort 8000 -ErrorAction Stop | Where-Object {$_.State -eq 'Listen'} | Foreach-Object {Stop-Process -Id $_.OwningProcess -Force}
```

**"Login failed for user" / "Cannot open database" saat boot**: aplikasi menolak start tanpa
pangkal, dan itu disengaja — tak ada mode darurat yang diam-diam jatuh ke berkas lokal. Periksa
`POS_APP_DB_*` di `.env`, lalu layanan SQL Server-nya. Selama server pangkal mati, tak ada yang
bisa login sama sekali.

**`manage.py test` gagal membuat/menghapus database test**: teardown menjalankan
`ALTER DATABASE test_... SET SINGLE_USER WITH ROLLBACK IMMEDIATE` lalu `DROP DATABASE`. Satu
jendela SSMS yang sedang membuka database itu cukup membuatnya gagal, dan run berikutnya mulai
dari database kotor. Tutup jendelanya, atau pakai `--keepdb` kalau memang sengaja dipertahankan.

**Vite manifest.json not found**:
Ran `npm run build`? Static files collected? Check `frontend/dist/` and `staticfiles/` exist.
