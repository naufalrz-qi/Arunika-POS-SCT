# Laporan Kesiapan Fitur

**Tanggal audit:** 2026-07-27 · **Commit:** `e5e6ab3` · **Branch:** `dev-preprod`

> Ini **potret satu waktu**, bukan dokumen hidup. Jangan dijadikan acuan setelah beberapa
> perubahan besar berikutnya tanpa diaudit ulang.

---

## Ringkasan

- **42 menu**, semuanya punya URL terdaftar, view nyata, dan berkas `.vue` yang ada.
  **Nol tautan mati, nol stub.** `frontend/mock/` sudah dihapus.
- **Nol** penanda `TODO` / `FIXME` / `XXX` / `HACK` / `NotImplementedError` / "coming soon"
  di seluruh repo.
- 19 menu adalah laporan generik yang dibangun dari spesifikasi (`_report_view` /
  `_report_export`), sisanya view khusus.
- Semua halaman yang menyentuh MS SQL kini memakai prop deferred. Dua halaman terakhir
  yang masih memblokir (Sinkronisasi Harga & Master Data) diperbaiki pada audit ini.

## Kategori kesiapan

| Kategori | Jumlah |
|---|---|
| Siap | 39 |
| Siap dengan catatan | 3 |
| Blocker | 0 |

Yang "siap dengan catatan": **Sinkronisasi Harga**, **Sinkronisasi Master Data** (risiko
cache 10 menit, lihat di bawah) dan **Kas Harian** (memakai `mssql.cursor` alih-alih
`report_cursor`).

---

## Matriks menu

Kolom **Stack**: `laporan-server` = spec `_report_view` + `ServerTable` (paginasi/sort/filter
di server) · `laporan-klien` = `ReportView` + `DataTable` (di browser) · `khusus` = view sendiri.
Kolom **Sumber baca**: `replica` = bisa membaca replica laporan bila dikonfigurasi.

| Menu | key | Stack | Sumber baca | Menulis MS SQL | Kesiapan |
|---|---|---|---|---|---|
| Dashboard | `dashboard` | khusus | primary | — | Siap |
| Bantuan & Istilah | `bantuan` | statis | — | — | Siap |
| Penjualan (Detail) | `penjualan_all` | laporan-server | replica | — | Siap |
| Laba per Barang | `penjualan_hpp` | laporan-server | replica | — | Siap |
| Penjualan per Nota | `penjualan_nota` | laporan-server | replica | — | Siap |
| Penjualan per Customer | `penjualan_customer` | laporan-server | replica | — | Siap |
| Penjualan per User | `penjualan_user` | laporan-server | replica | — | Siap |
| Penjualan per Periode | `penjualan_periode` | laporan-server | replica | — | Siap |
| Retur Penjualan | `retur_penjualan` | laporan-server | replica | — | Siap |
| Piutang Pelanggan | `piutang` | laporan-server | replica | — | Siap |
| Pembelian | `pembelian` | laporan-server | replica | — | Siap |
| Pembelian per Supplier | `pembelian_supplier` | laporan-server | replica | — | Siap |
| Pembelian per Periode | `pembelian_periode` | laporan-server | replica | — | Siap |
| Retur Pembelian | `retur_pembelian` | laporan-server | replica | — | Siap |
| Stok Akhir | `stock` | kolumnar-klien | primary | — | Siap |
| Barang Histori | `barang_histori` | laporan-klien | primary | — | Siap |
| Stok per Divisi | `stok_divisi` | kolumnar-klien | primary | — | Siap |
| Mutasi Stok | `stok_akhir` ⚠ | laporan-klien | primary | — | Siap |
| Stok Awal Barang | `stok_awal` | laporan-klien | primary | — | Siap |
| Transaksi Barang | `transaksi_barang` | laporan-server | replica | — | Siap |
| Opname Stok | `opname` | laporan-server | replica | — | Siap |
| FMI Penjualan | `fmi_penjualan` | laporan-server | replica | — | Siap |
| FMI Stok | `fmi_stok` | laporan-server | primary | — | Siap |
| Klasifikasi Pelanggan | `klasifikasi_pelanggan` | laporan-server | replica | — | Siap |
| Promo & Diskon | `promo` | laporan-server | replica | — | Siap |
| Voucher | `voucher` | laporan-server | replica | — | Siap |
| Kas Harian | `kas` | laporan-server | primary | — | Siap dengan catatan |
| Shift Kasir | `shift` | laporan-server | replica | — | Siap |
| Biaya Operasional | `biaya_operasional` | laporan-server | replica | — | Siap |
| Biaya per Kategori | `biaya_kategori` | laporan-server | replica | — | Siap |
| Master Produk | `products` | khusus | primary | — (hanya baca) | Siap |
| Master Pelanggan | `customers` | khusus | primary | — (hanya baca) | Siap |
| Master Supplier | `suppliers` | khusus | primary | — (hanya baca) | Siap |
| Update Barang | `update_barang` | khusus | primary | **Ya** (harga, status, nama & keterangan—khusus gudang) | Siap |
| Riwayat Update Barang | `riwayat_update_barang` | khusus | SQLite | — | Siap |
| Pergerakan Harga | `pergerakan_harga` | khusus | primary | — | Siap |
| Sinkronisasi Harga | `sync_harga` | khusus | 2 server | **Ya** (lintas server) | Siap dengan catatan |
| Sinkronisasi Master Data | `sync_master` | khusus | 2 server | **Ya** (lintas server) | Siap dengan catatan |
| Riwayat Sinkronisasi | `sync_history` | khusus | SQLite | — | Siap |
| Manajemen User | `users` | khusus | SQLite | — | Siap |
| Koneksi Server | `connections` | khusus | SQLite | — | Siap |
| Log Aktivitas | `logs` | khusus | SQLite | — | Siap |
| Kelola Menu | `menus` | khusus | SQLite | — | Siap (superadmin) |

⚠ **Jebakan penamaan:** key `stok_akhir` menunjuk halaman **Mutasi Stok**, sedangkan halaman
**Stok Akhir** ber-key `stock`. Hati-hati saat memberikan hak menu per key.

---

## Model hak akses

RBAC di sini **3 tingkat, bukan per-menu-per-peran**:

| Peran | Yang dilihat |
|---|---|
| `superadmin` | Semua menu, selalu |
| `admin` | Menu yang bisa diberikan, disaring `allowed_menu_keys`. **Daftar kosong = SEMUA diberikan** |
| `kasir` / `supervisor` | Tidak ada — ditolak saat login dan oleh penjaga jaringan admin |

Menu ber-flag `always` (saat ini: Bantuan & Istilah) tidak bisa dicabut dan tidak muncul di
Kelola Menu.

**Izin nilai uang (`User.hidden_data_keys`)** adalah sumbu terpisah: menu boleh dibuka, tapi
kolom rupiahnya dicabut di server. Cakupannya masih SEBAGIAN — daftar halaman yang benar-benar
menyaring:

| Halaman | Kunci yang berlaku | Jalur yang disaring |
|---|---|---|
| Dashboard | `nominal` | payload dashboard |
| Stok Akhir | `harga_jual`, `harga_beli`, `nominal` | halaman + export XLSX |
| Barang Histori | `harga_jual`, `harga_beli`, `nominal` | halaman |
| Klasifikasi Pelanggan | `nominal` | halaman, panel detail, **kedua sheet** export |

Halaman lain (FMI Stok, Mutasi Stok, Master Produk, laporan penjualan/pembelian) **masih
menampilkan uang ke siapa pun yang boleh membukanya** — untuk membatasi seseorang, menu-menu itu
harus dicabut, bukan sekadar mencabut kunci nilainya.

Menambah kolom uang baru ke halaman yang sudah menyaring: daftarkan nama field-nya di
`_FIELDS_BY_DATA_KEY` (`apps/monitoring/views.py`) **dan** pastikan setiap rute yang menyajikan
data itu ikut menyaring. Kelalaian ini sudah terjadi dua kali — sekali pada export Stok Akhir,
sekali pada sheet "Barang Favorit" di Klasifikasi Pelanggan (field-nya bernama `nilai`, bukan
`total_belanja`, jadi ia lolos dari daftar spec sementara sheet pertama tersaring). Keduanya tak
menimbulkan gejala apa pun di layar.

---

## Keputusan tertunda

**Kasir & supervisor tidak bisa memakai panel ini sama sekali.** Mereka berhasil terautentikasi
lalu langsung dikeluarkan (`apps/auth_app/views.py`, `apps/core/menus.py`). Belum diputuskan
apakah supervisor semestinya mendapat akses baca (dashboard + laporan). Perilakunya **tidak
diubah** pada audit ini; hanya pesannya yang dibuat jujur.

---

## Diperbaiki pada audit ini

| Temuan | Status |
|---|---|
| Stok per Divisi tak pernah memakai rekap stok harian → re-agregasi seluruh histori tiap load | **Selesai.** 2,43 s → 0,18 s (cache hangat), 1,66 s (dingin) |
| `POS_FERNET_KEY` rusak/dirotasi → 500 di hampir semua halaman data | **Selesai.** Dibungkus sekali di `core/mssql.py` |
| Teks driver ODBC bahasa Inggris bocor ke ~30 banner Indonesia | **Selesai.** `mssql.friendly_error()` |
| Dua halaman sinkronisasi memblokir first paint | **Selesai.** Jadi prop deferred |
| `spec["inner"]` / `apply_column_filters` di luar try → 500 karena bentuk filter | **Selesai** |
| Indexing `[0]` tanpa penjaga di 3 tempat | **Selesai.** `reporting.one_row()` |
| Halaman 404/500/CSRF berbahasa Inggris bawaan Django | **Selesai.** Template Indonesia |
| Peringatan rentang 92 hari dirender sebagai kegagalan koneksi | **Selesai.** Kanal `notice` terpisah |
| Halaman login menulis "autentikasi belum aktif" padahal aktif | **Selesai.** Dihapus |
| Sesi berakhir → redirect diam-diam tanpa penjelasan | **Selesai** |
| Akun nonaktif dikabari "username atau password salah" | **Selesai** |
| Nama tabel MS SQL & slug mentah (role, aksi, tipe DB) tampil ke pengguna | **Selesai.** `frontend/utils/labels.js` + label dari backend |
| Ganti koneksi selalu flash "berhasil" walau server mati; `last_status` tak pernah diperbarui | **Selesai** |
| 3 test basi terhadap `views.py` | **Selesai.** Ditulis ulang dengan aktor yang benar |
| FMI tak pernah dijabarkan di mana pun; nol materi pengguna akhir | **Selesai.** Menu Bantuan + `PANDUAN-PENGGUNA.md` |

---

## Performa pada profil jauh (WAN)

Diukur 2026-07-27 di **ANDARIA** (SERVER-LOTIM, lewat Tailscale antar-kota) vs
**RTL PUSAT** (LAN). Latensi **783 ms vs 26 ms** — 30× lipat. Ini pengali yang
membuat halaman terasa 40 detik di satu profil dan 1–5 detik di profil lain.

| Yang diukur | ANDARIA | RTL PUSAT |
|---|---|---|
| `_barang_meta` (dicache) | **21,77 s** | 1,17 s |
| `_barang_universe` (dulu tak dicache) | 2,96 s | 0,13 s |
| `_movement_sums` | 1,83 s | 0,12 s |
| Stok per Divisi, cache hangat | **4,73 → 1,95 s** | 0,45 s |
| Stok Akhir, cache hangat | 2,14 s | — |
| Laporan Penjualan (COUNT + halaman + ringkasan + options) | **0,92 s** | — |
| Dashboard | **1,10 s** | — |

**Yang terbukti BUKAN penyebab** (ketiganya hipotesis wajar yang gugur saat diukur):
snapshot ANDARIA ada dan segar; index lengkap tanpa kegagalan; katalognya justru
lebih kecil dari RTL PUSAT. Laporan dan Dashboard juga ternyata cepat — sempat
diduga lambat, pengukuran membantahnya, jadi tak ada perubahan di sana.

**Sisa masalah, terukur:**

1. **Cache dingin ~31 detik**, didominasi `_barang_meta` 21,8 detik. Bukan masalah
   kode melainkan umur cache: dengan TTL 600 detik, pengguna server jauh menanggung
   ongkos itu tiap 10 menit. **Setel `POS_MASTER_TTL=3600` di server produksi** —
   aman karena setiap penulisan master memanggil `invalidate_master_cache()`.
2. **Barang Histori selalu di jalur lambat secara struktur.** Ia mengirim
   `date_from`, yang otomatis membatalkan snapshot; di ANDARIA berarti memindai
   ulang ~2,5 tahun `t_penjualan_detail` sejak tutup buku 2024-01-12. Tutup buku
   tak boleh diubah (keputusan pemilik), jadi perbaikannya harus teknis:
   **snapshot v2 dengan jangkar mundur** (saldo periodik per bulan) supaya query
   tanggal lampau berangkat dari jangkar terdekat. `pos_stok_snapshot_base` sudah
   setengah jalan ke sana. Pekerjaan besar, menyentuh mesin stok — kerjakan
   terpisah dengan `check_stock_agg` sebagai penjaga.

## Diketahui, sengaja TIDAK diperbaiki

- **Risiko tulis sinkronisasi lintas server.** Perbandingan dihitung dari cache 10 menit,
  lalu menimpa **baris penuh** di server tujuan dalam satu transaksi. Kalau server tujuan
  berubah dalam rentang itu, yang ditimpa bisa berbeda dari yang dilihat operator. Sudah
  diperingatkan di halaman Bantuan dan `PANDUAN-PENGGUNA.md`; belum ada penguncian teknis.
- **Kas Harian** memakai `mssql.cursor` alih-alih `report_cursor`, jadi tidak ikut
  `READ UNCOMMITTED` maupun fallback replica.
- **Divergensi empty-state** antara `DataTable` (`pagedRows.length`) dan `ServerTable`
  (`rows.length`).
- **Keterbatasan index** pada `t_penjualan_detail` / `t_pembelian_detail`: kolom terhitung
  merujuk UDF yang dibuat dengan SET options salah, sehingga `CREATE INDEX` bisa gagal
  (error 1935). Kegagalannya dicatat lalu dilewati — memang begitu yang diharapkan.
- **Replica CDC belum diaktifkan** di server legacy (tugas DBA). Dengan `report_source`
  kosong, semua laporan membaca server utama langsung.
- **Harmonisasi istilah Customer ↔ Pelanggan** di ~10 halaman: key kolom terikat alias SQL,
  risiko regresinya nyata untuk perbaikan kosmetik. Gantinya kedua kata didefinisikan
  sekali di halaman Bantuan.
- **Audit aksesibilitas / aria-label**: workstream tersendiri.
- **Konstanta mati** `ADMIN_DEFAULT_MENUS` di `apps/auth_app/models.py` — tak dirujuk siapa pun.

---

## Cakupan pengujian

51 test, 7 berkas, semuanya lolos. Tanpa CI, tanpa test runner JavaScript.

**Belum diuji sama sekali:**

- 19 view laporan spec-driven
- `apps/transactions/reports.py` (>1000 baris — permukaan SQL terbesar di repo)
- `apps/core/reporting.py` (paginasi, filter, sort)
- Seluruh lapisan CDC (`apps/transactions/cdc_sync.py`) — tak bisa diuji tanpa server nyata
- `sync_harga_jual`, `sync_entity` — justru jalur tulis paling berisiko
- App `connections`, `apps/core/scheduler.py`
- Semua komponen Vue

**Celah terbesar yang diakui proyek sendiri** (`context.md` Fase 7): verifikasi menyeluruh
dan uji beban belum pernah dilakukan.

---

## Verifikasi yang dijalankan pada audit ini

```bash
python manage.py check_stock_agg
```

Hasil: `OK: 54657 key identik (146505 movement)` dan
`Snapshot OK: 14465 key identik (snapshot+delta == penuh)`.

```bash
python manage.py test
```

Hasil: `Ran 51 tests — OK`.

```bash
npm run build
```

Hasil: sukses.
