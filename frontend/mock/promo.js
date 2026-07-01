// Mock datasets for promo/discount and voucher management — frontend phase.

export const promo = [
  { kode: "PRM-LEBARAN", nama: "Diskon Lebaran", tipe: "Persen", nilai: 15, min_belanja: 500000, mulai: "2026-06-01", selesai: "2026-06-30", status: "Aktif" },
  { kode: "PRM-GROSIR50", nama: "Potongan Grosir", tipe: "Nominal", nilai: 50000, min_belanja: 2000000, mulai: "2026-06-15", selesai: "2026-07-15", status: "Aktif" },
  { kode: "PRM-NEWBIE", nama: "Promo Pelanggan Baru", tipe: "Persen", nilai: 10, min_belanja: 100000, mulai: "2026-05-01", selesai: "2026-05-31", status: "Berakhir" },
  { kode: "PRM-FLASH", nama: "Flash Sale Akhir Pekan", tipe: "Persen", nilai: 20, min_belanja: 0, mulai: "2026-07-05", selesai: "2026-07-06", status: "Terjadwal" },
];

export const voucher = [
  { kode: "VC-HEMAT25", nama: "Voucher Hemat 25K", nilai: 25000, kuota: 200, terpakai: 142, mulai: "2026-06-01", selesai: "2026-06-30", status: "Aktif" },
  { kode: "VC-ONGKIR", nama: "Gratis Ongkir", nilai: 30000, kuota: 100, terpakai: 100, mulai: "2026-06-10", selesai: "2026-06-20", status: "Habis" },
  { kode: "VC-MEMBER", nama: "Voucher Member", nilai: 50000, kuota: 50, terpakai: 12, mulai: "2026-06-20", selesai: "2026-07-20", status: "Aktif" },
  { kode: "VC-ULTAH", nama: "Voucher Ulang Tahun", nilai: 100000, kuota: 30, terpakai: 0, mulai: "2026-07-01", selesai: "2026-07-31", status: "Terjadwal" },
];
