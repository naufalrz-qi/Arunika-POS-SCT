// Mock datasets for FMI/SMI (fast/slow moving) analytics.
// fmi/smi flags: 1 = termasuk kelompok tsb (Fast Moving / Slow Moving).

export const fmiPenjualan = [
  { periode: "2026-06", divisi: "Grosir", nomor: 1, kode: "BRG0002", barang: "Hot Wheels 5-Pack", qty: 1240, total: 117800000, saldo: 512, fmi: 1, smi: 0 },
  { periode: "2026-06", divisi: "Grosir", nomor: 2, kode: "BRG0001", barang: "Lego Classic 11717", qty: 860, total: 159100000, saldo: 248, fmi: 1, smi: 0 },
  { periode: "2026-06", divisi: "Grosir", nomor: 3, kode: "BRG0007", barang: "Puzzle 1000pcs Disney", qty: 430, total: 60200000, saldo: 120, fmi: 1, smi: 0 },
  { periode: "2026-06", divisi: "Grosir", nomor: 4, kode: "BRG0003", barang: "Play-Doh 10 Color", qty: 310, total: 23250000, saldo: 96, fmi: 0, smi: 0 },
  { periode: "2026-06", divisi: "Retail", nomor: 5, kode: "BRG0004", barang: "UNO Card Game", qty: 180, total: 9900000, saldo: 64, fmi: 0, smi: 0 },
  { periode: "2026-06", divisi: "Grosir", nomor: 6, kode: "BRG0006", barang: "RC Car Offroad 1:16", qty: 42, total: 12600000, saldo: 34, fmi: 0, smi: 1 },
  { periode: "2026-06", divisi: "Retail", nomor: 7, kode: "BRG0005", barang: "Barbie Dreamhouse", qty: 18, total: 22500000, saldo: 8, fmi: 0, smi: 1 },
];

export const fmiStok = [
  { tanggal: "2026-06-30", divisi: "Retail", kode: "BRG0008", barang: "Nerf Elite 2.0", stok: 0, satuan: "PCS", fmi: 1, smi: 0, fmi_kosong: 1, smi_kosong: 0 },
  { tanggal: "2026-06-30", divisi: "Retail", kode: "BRG0005", barang: "Barbie Dreamhouse", stok: 8, satuan: "SET", fmi: 0, smi: 1, fmi_kosong: 0, smi_kosong: 0 },
  { tanggal: "2026-06-30", divisi: "Grosir", kode: "BRG0006", barang: "RC Car Offroad 1:16", stok: 34, satuan: "PCS", fmi: 0, smi: 1, fmi_kosong: 0, smi_kosong: 0 },
  { tanggal: "2026-06-30", divisi: "Grosir", kode: "BRG0002", barang: "Hot Wheels 5-Pack", stok: 512, satuan: "PCS", fmi: 1, smi: 0, fmi_kosong: 0, smi_kosong: 0 },
  { tanggal: "2026-06-30", divisi: "Grosir", kode: "BRG0003", barang: "Play-Doh 10 Color", stok: 96, satuan: "PCS", fmi: 0, smi: 0, fmi_kosong: 0, smi_kosong: 0 },
];
