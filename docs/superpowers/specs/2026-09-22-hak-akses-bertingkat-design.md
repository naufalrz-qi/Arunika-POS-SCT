# Hak Akses Bertingkat: Menu dan Koneksi

**Tanggal:** 2026-09-22 · **Branch:** `feat/hak-akses-bertingkat` · **Status:** disetujui, belum ada kode

## 1. Masalah

Dua keluhan dari pemakai, satu akar: aturan akses di aplikasi ini menjawab "siapa boleh
**punya**", padahal yang ditanyakan orang adalah "siapa boleh **memberi**".

1. **Ada menu yang tak bisa dipilah di Kelola Menu.**
   - Tujuh menu ber-`superadmin_only` (Kelola Menu, Kelola Tautan User, Kesehatan Sync,
     Kelola Kode Nota, Transfer ke Arunika, Cadangan & Pemulihan, Pembaruan Database) sama
     sekali tak muncul di sana: `assignable_menus()` membuangnya.
   - Sebagian view-nya juga memanggil `_deny_non_superadmin()`, jadi walaupun centangnya
     ada, halamannya tetap menolak.
   - Tujuh menu ber-`admin_only` (Opname, Koreksi Stok, Nota Tanggal Mundur, empat input
     Kas) dibuang `menus_for()` untuk kasir/supervisor, walaupun dicentang.
2. **Koneksi non-produksi terbuka untuk semua admin.** AMPHOREUS (pusat data milik kita
   sendiri, bukan server POS) dan salinan uji coba muncul di pemilih koneksi setiap admin,
   di samping server toko yang sungguhan.

Ditemukan sambil jalan: `_managed_roles()` memberi **setiap** non-superadmin wewenang atas
kasir, supervisor, *dan* admin. Supervisor yang diberi Manajemen User bisa membuat akun
admin.

## 2. Keputusan (sudah disetujui)

| # | Keputusan |
|---|---|
| K1 | Superadmin boleh memberikan menu apa pun ke peran apa pun. Satu-satunya pengecualian: `always` (Bantuan), yang memang tak bisa dicabut. |
| K2 | Ada 12 menu **teknis** yang hanya superadmin boleh berikan: Koneksi Server, Kesehatan Sync, Riwayat Operasi, Sinkronisasi Harga, Sinkronisasi Master Data, Transfer ke Arunika, Cadangan & Pemulihan, Pembaruan Database, Kelola Kode Nota, Kelola Tautan User, Kelola Menu, Manajemen User. Tak satu pun jadi bawaan peran di bawah superadmin. |
| K3 | Admin yang punya Kelola Menu mengatur kasir, supervisor, **dan sesama admin**, tapi tidak dirinya sendiri. |
| K4 | Admin hanya bisa memberi menu yang **ia pegang sendiri**. Aturan yang sama berlaku untuk izin melihat harga/nominal. |
| K5 | Menu tulis kritis (Opname, Koreksi Stok, Nota Tanggal Mundur, empat input Kas) diberikan ke kasir/supervisor **hanya oleh superadmin**. Admin boleh memberikannya ke sesama admin (kalau ia pegang). |
| K6 | `Lingkungan` mendapat label ketiga, **Internal** (untuk AMPHOREUS). Semua yang bukan Produksi hanya untuk superadmin, kecuali ia memberikan aksesnya. |
| K7 | Izin koneksi non-produksi diberikan **di Kelola Menu, per user**. |
| K8 | Pemilih koneksi di navbar memisahkan grup **Produksi** dan **Uji coba & internal**. |

## 3. Aturan menu

### 3.1 Flag di `apps/core/menus.py`

Kedua flag lama diganti. Nama barunya menyebut **siapa yang memberi**, supaya tak ada lagi
yang membacanya sebagai "siapa yang boleh punya".

| Flag lama | Flag baru | Arti baru |
|---|---|---|
| `superadmin_only` | `teknis` | Hanya superadmin yang memberi. Bukan bawaan peran mana pun. |
| `admin_only` | `tulis_kritis` | Bawaan admin. Ke kasir/supervisor hanya lewat superadmin. |
| — | tetap `always`, `butuh_tautan`, `roles` | Tak berubah. |

`teknis` = ketujuh menu yang dulu `superadmin_only`, ditambah lima yang dulu bukan:
`connections`, `users`, `sync_history`, `sync_harga`, `sync_master`. Kelimanya kini keluar
dari bawaan admin (K2). Totalnya 12.

### 3.2 `menus_for(user)`: murni hak yang diberikan

- **Superadmin:** `ALL_MENUS`, seperti sekarang.
- **Selain superadmin:** menu `always`, ditambah setiap menu yang kuncinya ada di
  `allowed_menu_keys` (atau di `default_keys_for(role)` kalau daftar itu kosong).
- **Tidak ada lagi saringan per peran.** Menu yang dicentang superadmin untuk kasir benar-benar
  berlaku.
- **Gerbang `butuh_tautan` tetap ada.** Aturannya tak berubah, dan superadmin pun ikut
  digerbangi.

`default_keys_for(role)`:

- **Admin:** menu yang bisa diberikan, di luar section kasir, **tanpa `teknis`**. Menu
  `tulis_kritis` tetap termasuk.
- **Superadmin:** tak dipakai.
- **Kasir/supervisor:** tak berubah (menu yang menyebut perannya di `roles`).

### 3.3 Satu fungsi aturan pemberian

```python
def boleh_beri(pemberi, peran_target: str, menu: dict) -> bool
```

- Mengembalikan `False` untuk menu `always`.
- Mengembalikan `True` kalau pemberi superadmin.
- Selain itu, `True` hanya kalau **semua** syarat ini terpenuhi:
  - pemberi punya menu `menus` (dibaca dengan `menus_for(pemberi, abaikan_tautan=True)`);
  - menunya bukan `teknis`;
  - menunya bukan `tulis_kritis`, **atau** targetnya berperan admin;
  - kunci menu itu ada di menu milik pemberi (juga dibaca dengan `abaikan_tautan=True`).

`abaikan_tautan=True` disengaja. Gerbang tautan bergantung pada koneksi yang sedang aktif,
sedangkan wewenang memberi tidak. Admin yang kebetulan belum tertaut di koneksi aktifnya
tetap boleh memberi menu kasir yang ia pegang.

Fungsi ini dipakai di tiga tempat, dan tak ada salinan kedua dari aturannya:
- layar Kelola Menu, untuk menentukan centang mana yang aktif;
- `menus_save`, untuk penegakan di server;
- test.

### 3.4 Siapa mengelola siapa (Kelola Menu **dan** Manajemen User)

Satu urutan peran: `kasir < supervisor < admin < superadmin`.

- **Superadmin** mengelola semua user. Aturan "superadmin aktif terakhir" tetap berlaku.
- **Selain superadmin** mengelola user yang **perannya setara atau di bawahnya**, dan bukan
  dirinya sendiri. Ia juga hanya boleh memberi peran yang setara atau di bawahnya.

`_managed_roles()` diganti fungsi berbasis urutan ini. Dengan begitu celah "supervisor
membuat admin" tertutup, dan Kelola Menu serta Manajemen User memakai aturan yang sama.

### 3.5 Menyimpan dari akun admin: yang di luar wewenang dipertahankan

Menyimpan berarti menulis ulang seluruh `allowed_menu_keys`. Karena itu `menus_save` yang
dijalankan admin tidak boleh menghapus apa yang tak bisa ia lihat. Rumusnya:

```
efektif  = allowed_menu_keys target, atau default_keys_for(role target) kalau kosong
wewenang = {k | boleh_beri(admin, role target, k)}
baru     = (efektif − wewenang) ∪ (dicentang ∩ wewenang)
```

Izin nilai uang memakai rumus yang sama: kunci yang **tersembunyi dari admin itu sendiri**
tak bisa ia ubah untuk orang lain, dan nilainya di target dipertahankan.

Superadmin menyimpan seperti sekarang: yang dicentang disaring ke `assignable_menus()`.

### 3.6 View teknis: pengecekan menu, bukan pengecekan peran

`_deny_non_superadmin(request)` diganti `_wajib_menu(request, key)`, yang menolak kalau
`key` tidak ada di `menus_for(request.user)`. Tujuannya tetap sama, sebagai pengecekan lapis
kedua kalau flag di `menus.py` suatu saat hilang. Bedanya, pengecekan ini menghormati menu
yang diberikan superadmin.

View Koreksi Stok (`_tolak_bukan_pengelola`) mendapat perubahan yang sama.

Yang **tetap** berdasarkan peran, karena tak terikat menu:
- `log_untuk()`: melihat jejak semua orang hanya untuk superadmin;
- status server di Dashboard: superadmin.

Penanda `migrasi_tertunda` tampil bagi siapa pun yang memegang menu `migrasi`.

### 3.7 Konsekuensi yang perlu diketahui

- **Menu kasir.** Penjualan, Retur, Pembelian, dll. bukan bawaan admin. Karena itu admin baru
  bisa memberikannya ke kasir kalau superadmin sudah memberikan menu yang sama ke admin itu.
  Ini akibat langsung K4, bukan bug.
- **Menu teknis yang diberikan ke admin** ikut membawa isi layarnya. Contoh: Koneksi Server
  menampilkan dan menyunting semua profil, termasuk yang non-produksi. Itu keputusan
  superadmin saat memberi.
- **Tidak ada admin produksi yang kehilangan akses saat deploy.** Per 2026-09-22 ke-11 admin
  di `TheScepter` sudah punya `allowed_menu_keys` eksplisit. Perubahan bawaan (§3.2) hanya
  mengenai akun admin baru, dan kunci teknis yang sudah ada di daftar mereka tetap berlaku.

## 4. Akses koneksi

### 4.1 Model

- **`Lingkungan.INTERNAL = "internal", "Internal"`.**
  - Migrasi `connections` menandai profil bernama `settings.HUB_NAME` (AMPHOREUS) sebagai
    `internal`. Balikannya mengembalikannya ke `produksi`.
  - Pemeriksaan yang ada (`muat.py`, `salin_legacy.py`, `transfer.py`) membandingkan
    `== UJI` secara eksplisit, jadi label baru tidak mengubah perilakunya. AMPHOREUS juga tak
    bisa jadi tujuan transfer, dan memang seharusnya begitu.
  - Docstring `Lingkungan` diperbarui: label ini sekarang **memang** menggerakkan izin.
- **`User.koneksi_khusus = ManyToManyField(ServerProfile, blank=True, related_name="pengguna_khusus")`.**
  Berisi profil non-produksi yang boleh dipilih user ini. Isinya hanya berarti untuk profil
  non-produksi, dan hanya untuk akun yang tak terkunci (admin).

### 4.2 Satu fungsi aturan (`apps/connections/akses.py`)

```python
def koneksi_boleh(user) -> QuerySet[ServerProfile]
def boleh_pakai(user, profile) -> bool
```

- **Superadmin:** semua profil.
- **Terkunci (kasir/supervisor):** hanya `user.server_profile`, apa pun label lingkungannya.
  Yang menentukan server itu adalah Manajemen User (§4.4).
- **Admin:** semua profil Produksi, ditambah `koneksi_khusus`.

### 4.3 Penegakan

1. **`inertia_share`.** Untuk akun yang tak terkunci, pilihan di sesi divalidasi dengan
   `boleh_pakai`. Kalau tidak berhak, kuncinya dibuang dari sesi, dan request memakai
   profil `is_default` kalau boleh, selain itu profil pertama yang diizinkan.
   Validasinya satu kueri per request, dan hasilnya diingat untuk request itu.
2. **`connections_set_default`.** Menolak profil yang tak diizinkan, dengan pesan yang
   jujur. Penolakan ini berlaku walaupun rutenya dikecualikan dari pengecekan menu.
3. **Prop bersama `connections`.** Hanya berisi `koneksi_boleh(user)`.

Job latar belakang (scheduler, `hub_pull`, sync, snapshot) tidak punya user dan tidak lewat
aturan ini. Mereka tetap memakai `is_default` atau profilnya sendiri, seperti sekarang.

### 4.4 Manajemen User: server untuk akun terkunci

- Selain superadmin, dropdown server hanya menampilkan profil Produksi.
- Validasinya juga di server (`users_save`). Nilai non-produksi hanya diterima dari
  superadmin, **atau kalau nilainya tidak berubah dari yang sudah tersimpan**. Pengecualian
  ini perlu supaya admin masih bisa menyunting nama kasir yang oleh superadmin dikunci ke
  server uji.

## 5. Layar

- **Kelola Menu** (`frontend/pages/Admin/Menus/Index.vue`):
  - Bisa dibuka siapa pun yang memegang menu `menus`.
  - Daftar user mengikuti §3.4.
  - Semua menu yang bisa diberikan ditampilkan. Yang tak boleh diubah pemakai layar tampil
    terkunci, dengan alasannya ("khusus superadmin" / "tidak Anda pegang"). Server mengirim
    peta `boleh_beri` per peran target, jadi layar tak menghitung aturannya sendiri.
  - Bagian baru **Akses koneksi non-produksi** (centang profil non-produksi) hanya tampil bagi
    superadmin, dan hanya untuk target berperan admin.
- **ConnectionMenu** (navbar): dua grup, **Produksi** dan **Uji coba & internal**. Grup kedua
  hanya muncul kalau ada isinya. Penanda `uji` yang sudah ada diperluas ke semua yang bukan
  Produksi.
- **Koneksi Server:** pilihan lingkungan otomatis bertambah Internal, karena dibaca dari
  `Lingkungan.choices`.
- **Manajemen User:** dropdown server tersaring (§4.4). Pilihan peran tersaring menurut §3.4.

## 6. Test

Berkas baru `apps/core/test_hak_akses.py`, plus penyesuaian test yang memakai flag lama.

- **Matriks `boleh_beri`:**
  - pemberi superadmin/admin/supervisor;
  - target kasir/admin;
  - menu biasa, teknis, tulis_kritis, always;
  - menu yang dipegang dan tidak dipegang.
- **HTTP `menus_save` dari akun admin:**
  - menu teknis yang dikirim diabaikan;
  - menu di luar wewenang milik target tetap bertahan;
  - `tulis_kritis` ke kasir ditolak, ke admin diterima;
  - izin uang yang tersembunyi dari admin tak berubah di target;
  - menyunting diri sendiri ditolak.
- **HTTP `menus_save` dari superadmin:** `koreksi_stok` ke kasir berlaku, dan
  `/admin-panel/inventory/koreksi-stok` terbuka baginya.
- **View teknis yang diberikan ke admin:** `/admin-panel/pengaturan/cadangan` terbuka (200).
  Tanpa pemberian, ditolak.
- **Urutan peran:** supervisor dengan Manajemen User tak bisa membuat admin. Admin tak bisa
  menyunting superadmin.
- **Koneksi:**
  - pilihan sesi ke profil `internal` tanpa izin jatuh ke default;
  - `set-default` ke profil `uji` tanpa izin ditolak;
  - setelah diberi `koneksi_khusus` diterima;
  - prop `connections` tersaring;
  - `users_save` menolak non-produksi dari admin, kecuali nilainya tak berubah.
- **Migrasi `connections`:** menandai profil `HUB_NAME` sebagai `internal`.

Verifikasi akhir:
- `manage.py test` penuh, dibandingkan dengan patokan sebelum perubahan;
- `npm run build`;
- uji manual di browser lewat dev server: Kelola Menu sebagai superadmin dan sebagai admin,
  lalu pemilih koneksi.

## 7. Dokumen yang ikut diperbarui

- **CLAUDE.md:**
  - paragraf "Single active connection", yang sudah basi (koneksi per sesi sejak lama);
  - paragraf RBAC di "Routing", yang menjelaskan flag lama.
- **context.md:** dua penyebutan `superadmin_only`/`admin_only`.
- **Docstring:** `Lingkungan`, `assignable_menus`, `default_keys_for`, `menus_for`.

## 8. Di luar cakupan

- Hak per aksi di dalam satu layar (mis. boleh melihat Koneksi Server tapi tidak
  menyunting). Menu tetap satuan izinnya.
- Mengubah siapa yang menjalankan job latar belakang.
- Deploy ke produksi. Itu langkah terpisah setelah branch ini disetujui:
  `git pull` + `npm run build` + `migrate` + restart `APP_SCTPOS`.
