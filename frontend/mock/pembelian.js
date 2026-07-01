// Mock datasets for purchase (pembelian) reports — frontend phase only.

export const pembelian = [
  { no_transaksi: "PO-2406-0010", no_order: "ORD-3321", tanggal: "2026-06-22", supplier: "PT Mainan Jaya", divisi: "Grosir", pembayaran: "Tempo 30 hari", jatuh_tempo: "2026-07-22", bank: "BCA", no_rekening: "1230045678", cabang: "Bandung", total_pembelian: 45200000 },
  { no_transaksi: "PO-2406-0011", no_order: "ORD-3322", tanggal: "2026-06-23", supplier: "CV Toys Indonesia", divisi: "Grosir", pembayaran: "Tunai", jatuh_tempo: "-", bank: "-", no_rekening: "-", cabang: "Jakarta", total_pembelian: 18750000 },
  { no_transaksi: "PO-2406-0012", no_order: "ORD-3325", tanggal: "2026-06-25", supplier: "PT Lego Distribusi", divisi: "Grosir", pembayaran: "Tempo 14 hari", jatuh_tempo: "2026-07-09", bank: "Mandiri", no_rekening: "1440998822", cabang: "Surabaya", total_pembelian: 62800000 },
  { no_transaksi: "PO-2406-0013", no_order: "ORD-3329", tanggal: "2026-06-27", supplier: "CV Sumber Ceria", divisi: "Retail", pembayaran: "Tunai", jatuh_tempo: "-", bank: "-", no_rekening: "-", cabang: "Jakarta", total_pembelian: 9600000 },
  { no_transaksi: "PO-2406-0014", no_order: "ORD-3331", tanggal: "2026-06-29", supplier: "PT Mainan Jaya", divisi: "Grosir", pembayaran: "Tempo 30 hari", jatuh_tempo: "2026-07-29", bank: "BCA", no_rekening: "1230045678", cabang: "Bandung", total_pembelian: 33450000 },
];

export const returPembelian = [
  { no_retur: "RB-2406-001", tanggal: "2026-06-24", supplier: "PT Mainan Jaya", divisi: "Grosir", pembayaran: "Tempo 30 hari", bank: "BCA", no_rekening: "1230045678", barang: "Hot Wheels 5-Pack", qty: 12, satuan: "PCS", keterangan: "Kemasan rusak" },
  { no_retur: "RB-2406-002", tanggal: "2026-06-26", supplier: "PT Lego Distribusi", divisi: "Grosir", pembayaran: "Tempo 14 hari", bank: "Mandiri", no_rekening: "1440998822", barang: "Lego Classic 11717", qty: 3, satuan: "PCS", keterangan: "Salah varian" },
  { no_retur: "RB-2406-003", tanggal: "2026-06-28", supplier: "CV Toys Indonesia", divisi: "Grosir", pembayaran: "Tunai", bank: "-", no_rekening: "-", barang: "Puzzle 1000pcs Disney", qty: 5, satuan: "PCS", keterangan: "Cacat produksi" },
];
