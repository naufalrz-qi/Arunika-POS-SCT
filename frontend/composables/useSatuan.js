import { reactive } from "vue";
import axios from "axios";

/**
 * Ganti satuan sebuah baris keranjang (PCS ↔ LUSIN ↔ DUS), dengan harga yang
 * ikut berganti.
 *
 * 541 barang punya lebih dari satu satuan dan harganya beda per satuan — 1001
 * misalnya PCS 4.800 dan LUSIN 57.600. Karena itu `ganti()` menimpa harga:
 * mempertahankan harga lama berarti menjual selusin seharga satu, dan tak ada
 * apa pun di layar yang akan memberitahu.
 *
 * Daftarnya diambil saat kotak satuan DISENTUH, bukan saat barang ditambahkan:
 * memindai barang tak boleh menambah round-trip (di profil WAN itulah biayanya),
 * sedangkan mengganti satuan memang jarang. Hasilnya di-cache per kd_barang
 * supaya baris kedua barang yang sama tak meminta ulang.
 *
 * @param {string} base prefix layar, mis. "/kasir/penjualan"
 * @param {string} kolomHarga nama field harga di baris ("harga_jual"/"harga")
 */
export function useSatuan(base, kolomHarga = "harga_jual") {
  const cache = reactive({});

  async function muat(b) {
    const kd = b?.kd_barang;
    if (!kd || cache[kd]) return;
    cache[kd] = [];        // penanda "sedang diambil": jangan minta dua kali
    try {
      const { data } = await axios.get(`${base}/satuan`, { params: { kd_barang: kd } });
      cache[kd] = data.rows || [];
    } catch {
      delete cache[kd];    // biar bisa dicoba lagi saat disentuh berikutnya
    }
  }

  const opsi = (b) => cache[b?.kd_barang] || [];

  function ganti(b, kdSatuan) {
    const s = opsi(b).find((x) => x.kd_satuan === kdSatuan);
    if (!s) return;
    b.kd_satuan = s.kd_satuan;
    b.satuan = s.satuan || s.kd_satuan;
    // harga_jual hilang dari respons untuk user yang dicabut hak lihat harga
    // (lihat _tanpa_harga di views_kasir.py) — jangan menimpanya dengan 0.
    if (s.harga_jual !== undefined) b[kolomHarga] = s.harga_jual;
  }

  /** "LUSIN (isi 12)" — kode satuan sendirian tak berarti apa-apa bagi kasir. */
  const label = (s) =>
    `${s.satuan || s.kd_satuan}${s.jumlah > 1 ? ` (isi ${s.jumlah})` : ""}`;

  return { muat, opsi, ganti, label };
}
