# Panduan Pengguna — Arunika POS (Sukses Crown Toys)

Dokumen ini menjelaskan **cara mengerjakan sesuatu**, langkah demi langkah. Boleh dicetak
untuk staf baru.

> **Arti istilah tidak diulang di sini.** Semua definisi (FMI, Opname, Tutup Buku, HPP,
> Replica, dsb.) hidup di satu tempat: menu **Bantuan & Istilah** di dalam aplikasi.
> Kalau ada istilah yang tidak Anda kenali di dokumen ini, buka menu itu. Pembagian ini
> disengaja supaya kedua sumber tidak saling menyimpang.

**Siapa yang memakai panel ini.** Panel admin ini dipakai oleh akun **Admin** dan
**Superadmin**. Akun **Kasir** dan **Supervisor** dipakai di aplikasi kasir, bukan di sini —
kalau login dengan akun tersebut, sistem akan menolak dan memberi tahu alasannya.

---

## 0. Sebelum mulai

1. **Masuk.** Buka alamat aplikasi, isi username dan password.
   - Salah password → muncul peringatan di atas form.
   - Gagal 5 kali → akun terkunci ±15 menit, dihitung sejak percobaan gagal **terakhir**.
   - Akun dinonaktifkan → pesannya berbeda; hubungi superadmin.
2. **Pilih server di navbar.** Aplikasi ini bisa terhubung ke beberapa server (gudang,
   grosir, toko retail). Semua angka yang Anda lihat berasal dari server yang sedang dipilih.
   Saat Anda berganti server, aplikasi langsung mengeceknya dan memberi tahu bila server
   itu tidak merespons.
3. **Titik status di sebelah nama server** menunjukkan hasil pengecekan terakhir, bukan
   kondisi saat ini secara real-time.
4. **Sesi berlaku 4 jam sejak Anda masuk** dan tidak diperpanjang oleh aktivitas. Kalau
   tiba-tiba diminta masuk lagi, itu normal — halaman login akan menjelaskannya.

---

## 1. Rutin harian

| Urutan | Menu | Untuk apa |
|---|---|---|
| 1 | **Stok per Divisi** | Cek cepat stok hari ini. Bisa disaring per divisi atau lihat semua. |
| 2 | **Dashboard** | Ringkasan omzet, transaksi, dan barang terlaris bulan berjalan. |
| 3 | **Penjualan per Nota** | Menelusuri transaksi tertentu. |
| 4 | **Kas Harian** dan **Shift Kasir** | Menutup kas dan mencocokkan shift. |

---

## 2. Stok

- **Stok per Divisi** — cek cepat, **selalu menampilkan hari ini**. Tidak ada pilihan
  tanggal di halaman ini, dan itu disengaja: tanpa tanggal, perhitungannya jauh lebih cepat.
- **Stok Akhir** — kalau Anda butuh saldo **pada tanggal lampau**, pakai menu ini. Ada
  filter tanggalnya.
- **Barang Histori** — kartu stok satu barang: setiap masuk/keluar berikut saldo berjalan.
  Gunakan saat angka stok terasa janggal dan Anda ingin tahu penyebabnya.
- **Opname Stok** — hasil pencocokan stok fisik dengan sistem.
- **Mutasi Stok** — perpindahan stok antar divisi/gudang untuk satu periode.
- **Transaksi Barang** — seluruh transaksi yang menyentuh satu barang.
- **Angka stok merah** = di bawah stok minimum barang tersebut.

> Kalau muncul peringatan bahwa perhitungan memakai *jalur lambat*: angkanya tetap benar,
> hanya lebih lama. Laporkan ke admin aplikasi.

---

## 3. Harga

- **Update Barang** — ubah harga jual dan ketersediaan satu barang. Sistem menolak harga
  yang tidak bulat, dan tidak ada satu pun satuan yang tersimpan bila salah satunya ditolak.
- **Harga Massal** — ubah harga banyak barang sekaligus. Barang yang ditolak tidak
  menggagalkan barang lain.
- **Pergerakan Harga** — riwayat perubahan harga sebuah barang.
- **Riwayat Update Barang** — siapa mengubah apa, kapan, dari berapa ke berapa.

### Nama & keterangan barang: hanya dari server gudang

Harga boleh berbeda per server — itu wajar, tiap cabang punya harganya sendiri. **Nama** barang
tidak: ia muncul di nota, di laporan lama, dan di layar kasir setiap cabang. Kalau tiap server
boleh menamai ulang sendiri, satu kode barang punya beberapa nama dan laporan lintas-cabang
berhenti bisa dibaca.

Karena itu kolom **Nama Barang** dan **Keterangan** di *Edit Barang*:

- **terkunci** kalau koneksi aktif bukan server gudang (dengan keterangan alasannya di layar);
- **bisa diubah** kalau koneksi aktif adalah server gudang.

Saat menyimpan, muncul **ringkasan "sebelum → sesudah"** untuk diperiksa dulu. Setelah tersimpan,
perubahannya tercatat di **Riwayat Update Barang** dan di tombol Riwayat pada kartu barang —
lengkap dengan siapa yang mengubahnya.

Cabang lain menerima nama baru itu lewat **Sinkronisasi Master Data**, bukan otomatis.

### Kalau server sumber modal mati

Mengisi **Sumber Modal** pada koneksi tidak wajib. Yang terjadi kalau server sumber modal
(gudang) mati:

| Tetap berjalan | Hilang sementara |
|---|---|
| Mencari barang di Update Barang | Kolom **Modal** dan **Margin** pada kartu barang |
| Mengubah harga jual | — |
| Mengubah status ketersediaan | — |
| Semua menu lain | — |

Aplikasi memberi tahu lewat pemberitahuan biru di atas daftar barang. Khusus toko retail:
harga tetap tersimpan, tetapi **margin tidak dihitung ulang** — nilai margin lama dibiarkan apa
adanya, dan itu disebutkan saat menyimpan. Setelah gudang hidup lagi, simpan ulang harga barang
tersebut kalau marginnya perlu diperbarui.

### ⚠ Sinkronisasi antar-server

**Sinkronisasi Harga** dan **Sinkronisasi Master Data** menulis ke **server lain** dan
**tidak bisa dibatalkan**.

1. Pilih server sumber dan server tujuan, klik **Bandingkan**. Perbandingan butuh waktu —
   halaman tetap bisa dipakai selagi menunggu.
2. Periksa daftar perbedaan. Centang **hanya** yang benar-benar ingin ditimpa.
3. **Muat ulang halaman sebelum menyinkronkan.** Perbandingan dihitung dari data yang
   disimpan sementara hingga 10 menit; kalau server tujuan berubah dalam rentang itu, yang
   Anda timpa bisa berbeda dari yang tampil.
4. Klik **Sinkronkan Terpilih**, lalu konfirmasi.
5. Cek hasilnya di **Riwayat Sinkronisasi**.

Sinkronisasi Master Data menimpa **seluruh baris**, bukan hanya kolom yang berbeda —
kecuali tanggal daftar barang dan poin pelanggan, yang sengaja dikecualikan.

---

## 4. Laporan & export Excel

- Semua laporan punya filter tanggal. **Rentang maksimal 92 hari** — kalau lebih, sistem
  memangkasnya dan menampilkan **banner biru**. Itu pemberitahuan, bukan kegagalan.
  Pengecualiannya **Klasifikasi Pelanggan**, yang memang butuh riwayat panjang (lihat §4b).
- Tombol **Export** mengunduh berkas Excel berisi data sesuai filter yang sedang aktif.
- Laporan besar bisa memakai salinan data khusus, sehingga angkanya bisa telat 1–2 menit
  dari transaksi yang baru saja terjadi.

Laporan yang tersedia: Penjualan (Detail, per Nota, per Customer, per User, per Periode),
Laba per Barang, Retur Penjualan, Piutang Pelanggan, Pembelian (dan per Supplier, per
Periode), Retur Pembelian, Biaya Operasional, Biaya per Kategori, FMI Penjualan, FMI Stok,
Klasifikasi Pelanggan, Promo & Diskon, Voucher.

---

## 4b. Menghubungi kembali pelanggan (Klasifikasi Pelanggan)

Menu **Analitik → Klasifikasi Pelanggan** menyusun daftar siapa yang perlu dihubungi, lengkap
dengan nomor HP-nya. Tiap pelanggan diberi satu **segmen**:

| Segmen | Artinya | Biasanya untuk |
|---|---|---|
| **Baru** | Belanja pertamanya belum lama (bawaan: 90 hari terakhir) | Disambut, ditawari jadi langganan |
| **Aktif** | Masih datang belakangan ini | Dibiarkan, sudah baik |
| **Setia** | Masih datang DAN sudah banyak notanya (bawaan: minimal 5) | Diberi perhatian khusus |
| **Mulai Jarang** | Sudah agak lama tak datang (bawaan: lebih dari 90 hari) | Diingatkan sebelum benar-benar pergi |
| **Hilang** | Sudah lama sekali tak datang (bawaan: lebih dari 180 hari) | Ditawari promo untuk kembali |

Halaman terbuka **terurut dari yang paling perlu dihubungi** (Hilang di atas), dengan jendela
riwayat **2 tahun** — bukan 92 hari seperti laporan lain, karena "belum belanja setahun" butuh
riwayat panjang untuk bisa terlihat.

**Yang bisa dilakukan:**

- **Klik nama pelanggan** → muncul kontak, **barang yang biasa ia beli**, dan nota terakhirnya.
  Barang favorit ini bahan pembuka percakapan yang paling berguna.
- **Ubah batasan segmen** di *Filter lanjutan → Aturan Segmen*. Toko grosir dan toko retail
  punya ritme belanja berbeda, jadi angka bawaan tidak harus dipakai. Angka yang sedang berlaku
  selalu terlihat di kotaknya.
- **Saring satu segmen saja** di *Filter lanjutan → Segmen*, misalnya hanya "Hilang".
- **Export Excel** menghasilkan **dua lembar**: `Klasifikasi` (daftar pelanggan + kontak) dan
  `Barang Favorit` (barang teratas tiap pelanggan). Jadi daftar telepon bisa dikerjakan tanpa
  membuka aplikasi lagi per orang.

**Kenapa UMUM, ECERAN, dan OBRAL tidak muncul di sini:** ketiganya bukan nama orang, hanya
penampung transaksi untuk pembeli yang identitasnya tidak dicatat — tidak ada siapa pun yang bisa
dihubungi. Akun marketplace (Shopee/Tokopedia/TikTok) juga dikecualikan karena itu kanal jualan.
Angka penjualan mereka tetap lengkap di laporan **Penjualan per Customer**.

---

## 4c. Edit nota penjualan

Menu **Penjualan → Edit Nota Penjualan**. Bawaan untuk admin; supervisor atau kasir hanya bisa
membukanya kalau superadmin memberikannya secara khusus. Akun Anda juga harus sudah ditautkan
ke user legacy di koneksi yang sedang dipilih (Kelola Tautan User).

1. Ketik nomor nota, tekan **Buka nota**.
2. Ubah yang perlu diubah: pelanggan, jenis bayar, kas, voucher, no. bukti, keterangan, jatuh
   tempo, diskon (Rp), pajak, dan baris barang (qty, harga, diskon, satuan, pegawai). Barang
   bisa ditambah lewat kotak di bawah tabel atau dihapus dengan tombol **Hapus**.
3. Periksa **Pratinjau perubahan** di kanan (apa yang berubah, total lama → baru).
4. Tulis **alasan edit** (minimal 10 huruf), tekan **Simpan perubahan…**, lalu pastikan sekali
   lagi di jendela konfirmasi.

**Yang tidak bisa diubah:** tanggal nota (di aplikasi lama mengubah tanggal ikut mengganti
nomor nota), divisi, dan status. Nota juga tidak bisa dikosongkan atau dibatalkan dari sini.

**Nota yang ditolak untuk diedit** (alasannya tampil sebagai banner merah):

- bertanggal sebelum tutup buku terakhir, atau lebih tua dari batas snapshot stok (±13 bulan);
- sudah punya cicilan piutang atau sudah masuk tagihan;
- nomor dari server lain (salinan sinkronisasi) — edit di server asalnya;
- sudah diubah orang lain (atau lewat aplikasi lama) sejak Anda membukanya — buka ulang notanya.

Setiap edit tercatat di **Jejak Audit**: siapa, kapan, dari mana, alasannya, dan isi nota
sebelum serta sesudahnya. Di server legacy, edit tercatat persis seperti edit dari aplikasi lama.
Bagian **Riwayat nota ini** di bawah layar menampilkan semua versi nota, termasuk edit yang
dilakukan lewat aplikasi lama.

Catatan stok: kalau nota yang diedit bertanggal sebelum hari ini, **Stok Akhir** untuk tanggal
lampau baru menyesuaikan sesudah rekap stok malam berikutnya — sama seperti edit dari aplikasi lama.

---

## 5. Administrasi (Superadmin)

- **Manajemen User** — buat/ubah akun dan perannya. Superadmin terakhir tidak bisa
  diturunkan perannya atau dihapus.
- **Kelola Menu** — tentukan menu apa saja yang boleh dibuka tiap admin. Menu **Bantuan &
  Istilah** selalu tersedia dan tidak bisa dicabut.
- **Koneksi Server** — daftar server beserta tombol Test.
- **Log Aktivitas** — jejak tindakan akun Anda sendiri (superadmin melihat semua).
- **Jejak Audit** — jejak SEMUA akun: penyaring tanggal/user/aksi/koneksi/nomor dokumen,
  tombol **Isi** untuk melihat isi nota sebelum dan sesudah diedit, dan klik nomor dokumen untuk
  riwayat lengkap nota itu (termasuk edit dari aplikasi lama). Tombol **Periksa keutuhan**
  memastikan tak ada jejak yang diubah atau dihapus langsung di database. Menu teknis — hanya
  superadmin yang bisa memberikannya.

---

## 6. Kalau bermasalah

| Yang Anda lihat | Artinya | Yang harus dilakukan |
|---|---|---|
| Banner **kuning** | Ada yang gagal — server tak terhubung atau data tak terbaca | Coba pilih koneksi lain di navbar; kalau tetap, hubungi admin |
| Banner **biru** | Pemberitahuan biasa, data tetap benar | Lanjutkan |
| Diminta masuk lagi tiba-tiba | Sesi 4 jam berakhir | Masuk kembali, ulangi perubahan terakhir |
| Halaman berputar lama lalu kuning | Server yang dipilih tidak merespons | Pilih koneksi lain |
| "Perhitungan memakai jalur lambat" | Rekap stok harian belum siap | Angka tetap benar; laporkan ke admin |
| "Menu ini tidak diberikan untuk akun Anda" | Hak menu belum diberikan | Minta ke superadmin |
| "Filter yang dipilih tidak bisa diproses" | Kombinasi filter tak valid | Kembalikan filter ke bawaan |
| Halaman kosong bertuliskan "Tidak ada data untuk filter yang dipilih" | Filternya terlalu sempit | Longgarkan filter atau ubah rentang tanggal |

---

## Lampiran A — Daftar menu

**Ringkasan:** Dashboard · Bantuan & Istilah

**Penjualan:** Penjualan (Detail) · Laba per Barang · Penjualan per Nota · Penjualan per
Customer · Penjualan per User · Penjualan per Periode · Retur Penjualan · Piutang Pelanggan ·
Edit Nota Penjualan

**Pembelian:** Pembelian · Pembelian per Supplier · Pembelian per Periode · Retur Pembelian

**Stok:** Stok Akhir · Barang Histori · Stok per Divisi · Mutasi Stok · Stok Awal Barang ·
Transaksi Barang · Opname Stok

**Analitik:** FMI Penjualan · FMI Stok · Klasifikasi Pelanggan

**Promo:** Promo & Diskon · Voucher

**Kas & Biaya:** Kas Harian · Shift Kasir · Biaya Operasional · Biaya per Kategori

**Master Data:** Master Produk · Master Pelanggan · Master Supplier *(ketiganya hanya baca)*

**Harga:** Update Barang · Riwayat Update Barang · Pergerakan Harga

**Sinkronisasi:** Sinkronisasi Harga · Sinkronisasi Master Data · Riwayat Sinkronisasi

**Administrasi:** Manajemen User · Koneksi Server · Log Aktivitas · Jejak Audit · Kelola Menu *(bisa diberikan superadmin kepada admin; admin hanya bisa memberi menu non-teknis yang ia pegang sendiri)*

---

## Lampiran B — Untuk admin aplikasi / IT

Perintah berikut dijalankan di server aplikasi, **bukan** oleh pengguna toko.

```bash
python manage.py snapshot_stok
```

```bash
python manage.py ensure_indexes
```

```bash
python manage.py check_stock_agg
```

```bash
python manage.py sync_cdc
```

- `snapshot_stok` — membangun rekap stok harian. Kalau pengguna melaporkan peringatan
  "jalur lambat", jalankan ini. Normalnya otomatis tiap malam.
- `ensure_indexes` — memasang index laporan di server MS SQL (aman diulang).
- `check_stock_agg` — memverifikasi perhitungan stok terhadap agregasi penuh.
- `sync_cdc` — menyinkronkan replica laporan (hanya bila replica dikonfigurasi).
