# Edit Nota Penjualan & Jejak Audit — rancangan

**Tanggal:** 2026-09-25 · **Branch:** `dev-feature`

## 1. Masalah

- Arunika hanya bisa **membuat** nota. Koreksi nota yang salah input masih lewat aplikasi POS
  lama, dan satu-satunya jejaknya ada di `tbl_log_transaksi`. Jejak itu tanpa alasan, tanpa akun
  Arunika, dan hanya terbaca lewat penelusuran log (`riwayat_log`).
- Log Aktivitas (`ActivityLog`) mencatat "siapa melakukan apa" dalam 255 karakter. Ia tanpa isi
  sebelum/sesudah, tanpa koneksi, tanpa nomor dokumen, dan tanpa perlindungan dari penyuntingan
  langsung di database.

## 2. Keputusan (disepakati pemilik produk)

| # | Pertanyaan | Keputusan |
|---|---|---|
| 1 | Cara mengganti baris barang | **Tiru legacy**: UPDATE kepala, DELETE baris `t_penjualan_detail` nota itu, INSERT ulang. Satu pengecualian sadar atas "tak pernah DELETE". |
| 2 | Siapa boleh edit | **Admin**. Supervisor hanya lewat pemberian superadmin (akses khusus). |
| 3 | Cakupan tahap 1 | **Penjualan saja, tanpa batal nota.** Tanggal tidak bisa diubah. |
| 4 | Audit | **Satu tabel** (`ActivityLog` diperkaya) + **satu halaman** Jejak Audit. |

Alasan dan bukti setiap keputusan ada di `context.md` § Edit Nota Penjualan dan § Jejak Audit.

## 3. Jalur tulis legacy (sekarang)

`apps/transactions/edit_nota.ubah_nota()`, satu transaksi. Urutannya persis aplikasi lama:

1. kunci + baca ulang;
2. cek versi dan penghalang;
3. UPDATE kepala;
4. DELETE TOP (1) × N;
5. INSERT × M;
6. total.

Terbukti di tiruan legacy yang memakai trigger asli dari `docs/skema/`:

- log trigger yang dihasilkan diputar ulang oleh `riwayat_log` menjadi "Dibuat → Diedit" dengan
  perubahan kepala dan barang yang benar;
- `barang_cocok = True`.

## 4. Kontrak untuk penulis Arunika (nanti — BELUM dibangun)

Ketika Arunika menjadi sistem pencatat, edit nota **tidak** meniru legacy. Rancangan skema §8.4
sudah menetapkan aturannya:

1. **Tanpa DELETE.** `penjualan_baris` tidak dihapus. Edit menulis **revisi**: nota menyimpan
   nomor revisi, baris lama ditandai tak berlaku (bukan dihapus), dan baris baru ditambahkan.
2. **`pergerakan_stok` append-only.** Selisih qty dibukukan sebagai BARIS PEMBALIK yang
   menunjuk dokumen asalnya: keluar untuk qty yang bertambah, masuk untuk yang berkurang.
3. **Jejak audit tetap di pangkal, tabel yang sama.** Penulis Arunika mengisi
   `ActivityLog.data` dengan `"skema": "arunika"` dan kosakata `apps/bisnis/models.py`. Layar
   merender per skema, jadi riwayat satu nota bisa berisi versi legacy lalu versi Arunika.
4. **Kunci jejak = `(profile_name, no_dokumen)`.** `bisnis.Penjualan.nomor` menyimpan nomor
   yang sama dengan `t_penjualan.no_transaksi`, jadi jejak dari masa legacy tetap menunjuk nota
   yang sama sesudah migrasi.
5. **Selama masa ganda** (Arunika menulis ke legacy DAN ke skemanya sendiri), `ubah_nota` legacy
   tetap satu-satunya penulis ke server toko. Penulis Arunika membaca hasilnya lewat adapter
   (`arunika_src.*`) atau `muat.py`, bukan menulis ulang ke legacy. Satu tulisan, satu sumber
   kebenaran per masa.

Pemisahan yang sudah disiapkan untuk ini:

- `hitung_selisih`/`selisih`, `versi`, `penghalang`, dan `total` adalah fungsi murni atau
  pembaca;
- hanya blok SQL di `ubah_nota` yang spesifik legacy.

## 5. Jejak Audit

- `ActivityLog` mendapat `profile`, `profile_name`, `jenis_dokumen`, `no_dokumen`, `alasan`,
  `data`, `hash_prev`, dan `hash` (migrasi `core/0019`). Semuanya boleh kosong, dan pemanggil
  lama tak berubah.
- **Rantai hash**: setiap baris baru menyimpan sha256 dari isinya plus hash baris sebelumnya.
  Kepala rantai (`RantaiJejak`) dikunci per penulisan. `manage.py cek_jejak` dan tombol
  "Periksa keutuhan" menunjuk baris pertama yang diubah, dihapus, atau hilang di ekor.
- **Layar**:
  - Log Aktivitas = jejak sendiri.
  - Jejak Audit (teknis) = semua akun, penyaring di SQL, detail sebelum/sesudah, dan riwayat
    per nota yang menggabungkan jejak Arunika dengan log legacy (lencana "via Arunika").

## 6. Di luar cakupan tahap ini

- Batal nota. Legacy tak punya status batal, dan satu-satunya cara di sana adalah DELETE kepala
  yang merambat ke cicilan dan tagihan.
- Edit pembelian, retur, dan order.
- Mengubah tanggal nota.
- Alur ajuan kasir → persetujuan supervisor/admin.
