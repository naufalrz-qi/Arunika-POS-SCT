// Saran harga dari kolom keterangan, mis. "ECER 3.450.000(50%)" / "ECER 300.000".
// Padanan JS dari parse_keterangan_price di apps/master_data/services.py — jaga
// keduanya seragam kalau salah satu berubah.
const KETERANGAN_PRICE_RE = /\d{1,3}(?:\.\d{3})+|\d+/;

export function parseKeteranganPrice(ket) {
  if (!ket) return null;
  const m = String(ket).split("(")[0].match(KETERANGAN_PRICE_RE);
  if (!m) return null;
  const n = parseInt(m[0].replace(/\./g, ""), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

// Satuan dasar = yang jumlah-nya 1 (mis. PCS), fallback ke satuan pertama.
export function baseUnit(satuan) {
  if (!satuan || !satuan.length) return null;
  return satuan.find((u) => u.jumlah === 1) || satuan[0];
}

// item: format list_barang_edit ({ kd_barang, nama, keterangan, satuan: [...] }).
// Return null kalau tak ada saran (keterangan kosong / sudah sesuai).
export function suggestFor(item) {
  if (!item) return null;
  const u = baseUnit(item.satuan);
  if (!u) return null;
  const target = parseKeteranganPrice(item.keterangan);
  if (target == null || target === u.harga_jual) return null;
  return {
    kd_barang: item.kd_barang,
    nama: item.nama,
    kd_satuan: u.kd_satuan,
    satuan: u.satuan || u.kd_satuan,
    harga_lama: u.harga_jual,
    harga_baru: target,
    selisih: target - u.harga_jual,
  };
}
