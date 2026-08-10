// Peta slug/kode internal -> label yang dibaca pengguna.
//
// Slug ini bocor ke layar di beberapa tempat (role mentah "superadmin" di menu
// user, aksi "login_terkunci" di Log Aktivitas, db_type yang ditulis "Retail"
// di satu halaman dan "Toko Retail" di halaman lain). Satu berkas supaya tak
// ada lagi versi yang berbeda-beda per halaman.

export const ROLE_LABELS = {
  kasir: "Kasir",
  supervisor: "Supervisor",
  admin: "Admin",
  superadmin: "Superadmin",
};

// Nilai ActivityLog.action. Daftarnya = semua slug yang dipakai log_activity().
//
// Peta ini sempat basi setahun: ia masih memuat `transaksi`/`tutup_buku`/`batal`
// yang tak dipancarkan kode mana pun, dan TIDAK memuat tujuh slug yang benar-
// benar ditulis. Slug yang tak terpetakan tampil apa adanya (lihat labelOf),
// jadi kegagalannya tak pernah terlihat sebagai galat — cuma sebagai kata
// `koreksi_stok` di kolom yang seharusnya berbahasa Indonesia. Kotak notif di
// navbar merender label yang sama, jadi sekarang ia muncul dua kali.
//
// Cara mengecek ulang daftarnya:
//   grep -rn 'log_activity(request, ' apps/ --include=*.py
export const ACTION_LABELS = {
  login: "Masuk",
  logout: "Keluar",
  login_gagal: "Gagal masuk",
  login_terkunci: "Akun terkunci",
  user: "Manajemen user",
  barang: "Ubah barang",
  sync_harga: "Sinkronisasi harga",
  sync_master: "Sinkronisasi master",
  menu: "Ubah hak menu",
  export: "Export data",
  profil: "Ubah profil",
  konfigurasi: "Konfigurasi server",
  kode_nota: "Ubah kode nota",
  tautan_user: "Tautan user legacy",
  koreksi_stok: "Koreksi stok",
  penjualan: "Nota penjualan",
  penjualan_order: "Penjualan order",
  // Slug dinamis: `jenis` di views_kasir._transaksi_save (kunci transaksi.SPEC)
  // dan `entitas` di views.master_crud_save (kunci master_crud._MASTER).
  penjualan_retur: "Retur penjualan",
  pembelian: "Pembelian",
  pembelian_retur: "Retur pembelian",
  pelanggan: "Kelola pelanggan",
  supplier: "Kelola supplier",
  // Ditulis thread indexing, tanpa request — username-nya "system".
  index: "Pembangunan index",
};

export const DB_TYPE_LABELS = {
  gudang: "Gudang",
  grosir: "Grosir",
  retail: "Toko Retail",
};

/** Label untuk sebuah slug, atau slug-nya sendiri kalau belum dipetakan. */
export const labelOf = (map, key) => map[key] || key || "—";
