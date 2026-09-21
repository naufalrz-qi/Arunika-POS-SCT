# Design Spec: Kelola Informasi Perusahaan & Penyesuaian Struk/Faktur Nota

**Tanggal:** 2026-08-13  
**Status:** Approved  
**Aplikasi:** Arunika POS (Sukses Crown Toys)

---

## 1. Ringkasan Kebutuhan
Menambahkan menu **Kelola Informasi Perusahaan** di Admin Panel untuk mengelola data identitas profil utama dan alamat/telepon divisi/cabang pada MS SQL Server. Selain itu, menyesuaikan cetakan **Nota/Faktur Penjualan** agar memuat informasi lengkap perusahaan, kasir, member, detail barang dengan nama satuan dan kode barang, jenis pembayaran, subtotal, diskon, total, bayar, serta kembalian.

---

## 2. Perubahan Backend & Database

### 2.1 Backend `apps/master_data/` & `apps/monitoring/`
- **Menu Kelola Informasi Perusahaan (`/admin-panel/master-data/informasi-perusahaan`)**:
  - Mengelola data profil perusahaan pusat (`g_info_profile`): Nama Perusahaan, Alamat, Kota, No. Telp, HP, Email, Website.
  - Mengelola data alamat & telp divisi/cabang (`m_divisi`): `alamat`, `telepon`.
- **API/Service Penjualan (`apps/transactions/penjualan.py`)**:
  - Memperbarui fungsi `baca_nota(profile, no_transaksi)` untuk mengambil data lengkap:
    - Identitas toko dari `m_divisi` (dikombinasikan/fallback ke `g_info_profile`).
    - Nama kasir/pegawai (`m_pegawai.nama`).
    - Nama pelanggan (`m_customer.nama`).
    - Nama jenis pembayaran (`m_jenis_bayar.nama`).
    - Detail barang dengan `kd_barang`, nama barang, nama satuan (`m_satuan.nama`), qty, harga, subtotal.
    - Hitungan keuangan: Subtotal, Diskon Uang, Pajak, Total, Uang Bayar, Kembalian.

---

## 3. Perubahan Frontend (`NotaCetak.vue` & `Faktur.vue`)

### 3.1 Penyesuaian `NotaCetak.vue`
Format cetak monospace (width 40 karakter) disesuaikan dengan struktur berikut:

1. **Header Toko & Perusahaan**:
   - Nama Toko / Perusahaan
   - Alamat & No. Telp
2. **Metadata Transaksi**:
   - No. Transaksi (`No`)
   - Tanggal & Jam (`Tgl`)
   - Nama Kasir (`Kasir`)
   - Nama Pelanggan (`Cus`: Cukup nama customer/member)
   - Jenis Pembayaran (`Bayar`)
3. **Detail Barang**:
   - Kode Barang & Nama Barang: `[kd_barang] nama_barang`
   - Qty, **Nama Satuan**, Harga Satuan, Total Baris: `  2 PCS x 50.000       100.000`
4. **Ringkasan Pembayaran**:
   - Subtotal
   - Diskon (jika ada)
   - Pajak (jika ada)
   - TOTAL
   - Bayar (Nominal Uang Diterima)
   - Kembali (Nominal Kembalian)
5. **Footer**:
   - Catatan / Terima kasih

---

## 4. Keamanan & Batas Pengujian
- **Aturan Koneksi**: Seluruh pengujian query dan update data MS SQL Server HANYA dilakukan pada profil koneksi **`Testing`**. Tidak boleh mengganggu database toko/gudang produksi lainnya.
