// Mock datasets for the sales (penjualan) reports — frontend phase only.
// Shapes mirror the SQL views in .viewandfucntion.

export const penjualanAll = [
  { id: 1, no_transaksi: "SO-2406-0001", tanggal: "2026-06-28", divisi: "Grosir", customer: "Toko Ceria", kota: "Bandung", barang: "Lego Classic 11717", qty: 12, satuan: "PCS", harga: 185000, diskon: 5000, harga_bersih: 180000, total: 2160000 },
  { id: 2, no_transaksi: "SO-2406-0001", tanggal: "2026-06-28", divisi: "Grosir", customer: "Toko Ceria", kota: "Bandung", barang: "Hot Wheels 5-Pack", qty: 24, satuan: "PCS", harga: 95000, diskon: 0, harga_bersih: 95000, total: 2280000 },
  { id: 3, no_transaksi: "SO-2406-0002", tanggal: "2026-06-28", divisi: "Retail", customer: "Umum", kota: "Jakarta", barang: "Barbie Dreamhouse", qty: 2, satuan: "SET", harga: 1250000, diskon: 50000, harga_bersih: 1200000, total: 2400000 },
  { id: 4, no_transaksi: "SO-2406-0003", tanggal: "2026-06-29", divisi: "Grosir", customer: "Mainan Sentosa", kota: "Surabaya", barang: "Play-Doh 10 Color", qty: 36, satuan: "PCS", harga: 78000, diskon: 3000, harga_bersih: 75000, total: 2700000 },
  { id: 5, no_transaksi: "SO-2406-0004", tanggal: "2026-06-29", divisi: "Retail", customer: "Umum", kota: "Jakarta", barang: "UNO Card Game", qty: 8, satuan: "PCS", harga: 55000, diskon: 0, harga_bersih: 55000, total: 440000 },
  { id: 6, no_transaksi: "SO-2406-0005", tanggal: "2026-06-30", divisi: "Grosir", customer: "Toko Bahagia", kota: "Semarang", barang: "RC Car Offroad 1:16", qty: 6, satuan: "PCS", harga: 320000, diskon: 20000, harga_bersih: 300000, total: 1800000 },
  { id: 7, no_transaksi: "SO-2406-0006", tanggal: "2026-06-30", divisi: "Grosir", customer: "Mainan Sentosa", kota: "Surabaya", barang: "Puzzle 1000pcs Disney", qty: 18, satuan: "PCS", harga: 145000, diskon: 5000, harga_bersih: 140000, total: 2520000 },
  { id: 8, no_transaksi: "SO-2406-0007", tanggal: "2026-06-30", divisi: "Retail", customer: "Umum", kota: "Jakarta", barang: "Nerf Elite 2.0", qty: 4, satuan: "PCS", harga: 285000, diskon: 0, harga_bersih: 285000, total: 1140000 },
];

export const penjualanNota = [
  { no_nota: "SO-2406-0001", tanggal: "2026-06-28", customer: "Toko Ceria", kota: "Bandung", divisi: "Grosir", total_kotor: 4500000, potongan: 60000, voucher: 0, pajak: 0, total_bersih: 4440000, petugas: "Rina" },
  { no_nota: "SO-2406-0002", tanggal: "2026-06-28", customer: "Umum", kota: "Jakarta", divisi: "Retail", total_kotor: 2500000, potongan: 100000, voucher: 50000, pajak: 0, total_bersih: 2350000, petugas: "Dimas" },
  { no_nota: "SO-2406-0003", tanggal: "2026-06-29", customer: "Mainan Sentosa", kota: "Surabaya", divisi: "Grosir", total_kotor: 2808000, potongan: 108000, voucher: 0, pajak: 0, total_bersih: 2700000, petugas: "Rina" },
  { no_nota: "SO-2406-0004", tanggal: "2026-06-29", customer: "Umum", kota: "Jakarta", divisi: "Retail", total_kotor: 440000, potongan: 0, voucher: 0, pajak: 0, total_bersih: 440000, petugas: "Dimas" },
  { no_nota: "SO-2406-0005", tanggal: "2026-06-30", customer: "Toko Bahagia", kota: "Semarang", divisi: "Grosir", total_kotor: 1920000, potongan: 120000, voucher: 0, pajak: 0, total_bersih: 1800000, petugas: "Yusuf" },
  { no_nota: "SO-2406-0006", tanggal: "2026-06-30", customer: "Mainan Sentosa", kota: "Surabaya", divisi: "Grosir", total_kotor: 2610000, potongan: 90000, voucher: 0, pajak: 0, total_bersih: 2520000, petugas: "Rina" },
  { no_nota: "SO-2406-0007", tanggal: "2026-06-30", customer: "Umum", kota: "Jakarta", divisi: "Retail", total_kotor: 1140000, potongan: 0, voucher: 0, pajak: 0, total_bersih: 1140000, petugas: "Dimas" },
];

export const penjualanCustomer = [
  { divisi: "Grosir", customer: "Toko Ceria", kota: "Bandung", jumlah_nota: 14, total_bersih: 41250000 },
  { divisi: "Grosir", customer: "Mainan Sentosa", kota: "Surabaya", jumlah_nota: 22, total_bersih: 63400000 },
  { divisi: "Grosir", customer: "Toko Bahagia", kota: "Semarang", jumlah_nota: 9, total_bersih: 18900000 },
  { divisi: "Retail", customer: "Umum", kota: "Jakarta", jumlah_nota: 156, total_bersih: 28750000 },
  { divisi: "Grosir", customer: "Kids World", kota: "Medan", jumlah_nota: 7, total_bersih: 15200000 },
  { divisi: "Grosir", customer: "Istana Mainan", kota: "Yogyakarta", jumlah_nota: 11, total_bersih: 24600000 },
];

export const penjualanUser = [
  { no_transaksi: "SO-2406-0001", tanggal: "2026-06-28", divisi: "Grosir", status: "Lunas", customer: "Toko Ceria", nominal: 4440000, user: "Rina" },
  { no_transaksi: "SO-2406-0002", tanggal: "2026-06-28", divisi: "Retail", status: "Lunas", customer: "Umum", nominal: 2350000, user: "Dimas" },
  { no_transaksi: "SO-2406-0003", tanggal: "2026-06-29", divisi: "Grosir", status: "Tempo", customer: "Mainan Sentosa", nominal: 2700000, user: "Rina" },
  { no_transaksi: "SO-2406-0005", tanggal: "2026-06-30", divisi: "Grosir", status: "Lunas", customer: "Toko Bahagia", nominal: 1800000, user: "Yusuf" },
  { no_transaksi: "SO-2406-0006", tanggal: "2026-06-30", divisi: "Grosir", status: "Tempo", customer: "Mainan Sentosa", nominal: 2520000, user: "Rina" },
  { no_transaksi: "SO-2406-0007", tanggal: "2026-06-30", divisi: "Retail", status: "Lunas", customer: "Umum", nominal: 1140000, user: "Dimas" },
];

export const penjualanBulanan = [
  { periode: "2026-01", label: "Jan", total_bersih: 182500000 },
  { periode: "2026-02", label: "Feb", total_bersih: 168900000 },
  { periode: "2026-03", label: "Mar", total_bersih: 205300000 },
  { periode: "2026-04", label: "Apr", total_bersih: 197800000 },
  { periode: "2026-05", label: "Mei", total_bersih: 224100000 },
  { periode: "2026-06", label: "Jun", total_bersih: 241600000 },
];

export const penjualanHarian = [
  { periode: "2026-06-24", label: "24", total_bersih: 8200000 },
  { periode: "2026-06-25", label: "25", total_bersih: 9450000 },
  { periode: "2026-06-26", label: "26", total_bersih: 7600000 },
  { periode: "2026-06-27", label: "27", total_bersih: 11200000 },
  { periode: "2026-06-28", label: "28", total_bersih: 6790000 },
  { periode: "2026-06-29", label: "29", total_bersih: 3140000 },
  { periode: "2026-06-30", label: "30", total_bersih: 5460000 },
];

export const returPenjualan = [
  { no_retur: "RJ-2406-001", tanggal_retur: "2026-06-29", no_bukti: "SO-2406-0001", divisi: "Grosir", barang: "Lego Classic 11717", satuan: "PCS", jenis_bayar: "Tunai", bank: "-", qty: 2, total: 360000, customer: "Toko Ceria", sales: "Rina" },
  { no_retur: "RJ-2406-002", tanggal_retur: "2026-06-30", no_bukti: "SO-2406-0003", divisi: "Grosir", barang: "Play-Doh 10 Color", satuan: "PCS", jenis_bayar: "Transfer", bank: "BCA", qty: 4, total: 300000, customer: "Mainan Sentosa", sales: "Rina" },
  { no_retur: "RJ-2406-003", tanggal_retur: "2026-06-30", no_bukti: "SO-2406-0007", divisi: "Retail", barang: "Nerf Elite 2.0", satuan: "PCS", jenis_bayar: "Tunai", bank: "-", qty: 1, total: 285000, customer: "Umum", sales: "Dimas" },
];
