// Mock datasets for inventory reports (stok per divisi, stok akhir, opname).

export const stokDivisi = [
  { kd_divisi: "DIV01", divisi: "Grosir", kd_barang: "BRG0001", barang: "Lego Classic 11717", kategori: "Building Block", jenis: "Import", stok_akhir: 248, supplier: "PT Lego Distribusi" },
  { kd_divisi: "DIV01", divisi: "Grosir", kd_barang: "BRG0002", barang: "Hot Wheels 5-Pack", kategori: "Diecast", jenis: "Import", stok_akhir: 512, supplier: "PT Mainan Jaya" },
  { kd_divisi: "DIV01", divisi: "Grosir", kd_barang: "BRG0003", barang: "Play-Doh 10 Color", kategori: "Edukasi", jenis: "Import", stok_akhir: 96, supplier: "CV Toys Indonesia" },
  { kd_divisi: "DIV02", divisi: "Retail", kd_barang: "BRG0004", barang: "UNO Card Game", kategori: "Board Game", jenis: "Lokal", stok_akhir: 64, supplier: "CV Sumber Ceria" },
  { kd_divisi: "DIV02", divisi: "Retail", kd_barang: "BRG0005", barang: "Barbie Dreamhouse", kategori: "Figur", jenis: "Import", stok_akhir: 8, supplier: "PT Mainan Jaya" },
  { kd_divisi: "DIV01", divisi: "Grosir", kd_barang: "BRG0006", barang: "RC Car Offroad 1:16", kategori: "Remote Control", jenis: "Import", stok_akhir: 34, supplier: "CV Toys Indonesia" },
  { kd_divisi: "DIV01", divisi: "Grosir", kd_barang: "BRG0007", barang: "Puzzle 1000pcs Disney", kategori: "Puzzle", jenis: "Lokal", stok_akhir: 120, supplier: "CV Sumber Ceria" },
  { kd_divisi: "DIV02", divisi: "Retail", kd_barang: "BRG0008", barang: "Nerf Elite 2.0", kategori: "Blaster", jenis: "Import", stok_akhir: 0, supplier: "PT Mainan Jaya" },
];

export const stokAkhir = [
  { divisi: "Grosir", kd_barang: "BRG0001", barang: "Lego Classic 11717", kategori: "Building Block", merk: "LEGO", model: "11717", warna: "Mix", stok_akhir: 248, harga_average: 142000, harga_jual: 185000, nominal: 35216000, harga_beli_akhir: 145000 },
  { divisi: "Grosir", kd_barang: "BRG0002", barang: "Hot Wheels 5-Pack", kategori: "Diecast", merk: "Mattel", model: "HW5", warna: "Mix", stok_akhir: 512, harga_average: 68000, harga_jual: 95000, nominal: 34816000, harga_beli_akhir: 70000 },
  { divisi: "Grosir", kd_barang: "BRG0003", barang: "Play-Doh 10 Color", kategori: "Edukasi", merk: "Hasbro", model: "PD10", warna: "Mix", stok_akhir: 96, harga_average: 55000, harga_jual: 78000, nominal: 5280000, harga_beli_akhir: 56000 },
  { divisi: "Retail", kd_barang: "BRG0005", barang: "Barbie Dreamhouse", kategori: "Figur", merk: "Mattel", model: "DRH", warna: "Pink", stok_akhir: 8, harga_average: 920000, harga_jual: 1250000, nominal: 7360000, harga_beli_akhir: 940000 },
  { divisi: "Grosir", kd_barang: "BRG0006", barang: "RC Car Offroad 1:16", kategori: "Remote Control", merk: "JJRC", model: "Q60", warna: "Merah", stok_akhir: 34, harga_average: 235000, harga_jual: 320000, nominal: 7990000, harga_beli_akhir: 240000 },
  { divisi: "Grosir", kd_barang: "BRG0007", barang: "Puzzle 1000pcs Disney", kategori: "Puzzle", merk: "Disney", model: "P1000", warna: "Mix", stok_akhir: 120, harga_average: 98000, harga_jual: 145000, nominal: 11760000, harga_beli_akhir: 100000 },
];

export const opname = [
  { no_transaksi: "OPN-2406-01", divisi: "Grosir", barang: "Hot Wheels 5-Pack", satuan: "PCS", tanggal: "2026-06-26", qty: -6, keterangan: "Selisih fisik gudang", petugas: "Yusuf", status: "Hilang" },
  { no_transaksi: "OPN-2406-02", divisi: "Grosir", barang: "Lego Classic 11717", satuan: "PCS", tanggal: "2026-06-26", qty: -2, keterangan: "Box penyok", petugas: "Yusuf", status: "Rusak" },
  { no_transaksi: "OPN-2406-03", divisi: "Retail", barang: "UNO Card Game", satuan: "PCS", tanggal: "2026-06-27", qty: 3, keterangan: "Temuan stok lebih", petugas: "Dimas", status: "Lain-Lain (+)" },
  { no_transaksi: "OPN-2406-04", divisi: "Grosir", barang: "Puzzle 1000pcs Disney", satuan: "PCS", tanggal: "2026-06-28", qty: -1, keterangan: "Sampel display", petugas: "Rina", status: "Lain-Lain (-)" },
];
