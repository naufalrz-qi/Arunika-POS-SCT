// Mock datasets for cash (kas harian) and cashier shift management.

export const kasHarian = [
  { tanggal: "2026-06-30", kasir: "Dimas", saldo_awal: 1000000, kas_masuk: 5460000, kas_keluar: 350000, penjualan_tunai: 5110000, saldo_akhir: 6110000, selisih: 0, status: "Seimbang" },
  { tanggal: "2026-06-29", kasir: "Rina", saldo_awal: 1000000, kas_masuk: 3140000, kas_keluar: 120000, penjualan_tunai: 3020000, saldo_akhir: 4020000, selisih: -15000, status: "Selisih Kurang" },
  { tanggal: "2026-06-28", kasir: "Dimas", saldo_awal: 1000000, kas_masuk: 6790000, kas_keluar: 500000, penjualan_tunai: 6290000, saldo_akhir: 7290000, selisih: 5000, status: "Selisih Lebih" },
  { tanggal: "2026-06-27", kasir: "Yusuf", saldo_awal: 1000000, kas_masuk: 11200000, kas_keluar: 800000, penjualan_tunai: 10400000, saldo_akhir: 11400000, selisih: 0, status: "Seimbang" },
];

export const shift = [
  { shift: "Pagi", kasir: "Dimas", mulai: "2026-06-30 08:00", selesai: "2026-06-30 14:00", divisi: "Retail", transaksi: 38, omzet: 3120000, status: "Selesai" },
  { shift: "Siang", kasir: "Rina", mulai: "2026-06-30 14:00", selesai: "2026-06-30 20:00", divisi: "Retail", transaksi: 41, omzet: 2340000, status: "Selesai" },
  { shift: "Pagi", kasir: "Yusuf", mulai: "2026-06-30 08:00", selesai: "-", divisi: "Grosir", transaksi: 12, omzet: 8650000, status: "Berjalan" },
];
