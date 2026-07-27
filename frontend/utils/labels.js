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
  transaksi: "Transaksi",
  tutup_buku: "Tutup buku",
  batal: "Pembatalan",
};

export const DB_TYPE_LABELS = {
  gudang: "Gudang",
  grosir: "Grosir",
  retail: "Toko Retail",
};

/** Label untuk sebuah slug, atau slug-nya sendiri kalau belum dipetakan. */
export const labelOf = (map, key) => map[key] || key || "—";
