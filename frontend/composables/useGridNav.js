/**
 * Pindah antar sel isian di dalam tabel dengan panah + Enter, seperti layar
 * aplikasi desktop lama. Tab tetap jalan seperti biasa — ini tambahan, bukan
 * pengganti.
 *
 * Cara pakai: taruh `data-nav` di setiap <input> dalam baris tabel, dan
 * `data-nav-entri` di kotak cari/pindai tempat kursor pulang. Pasang satu
 * handler di pembungkus tabelnya (`@keydown="nav"`); barisnya boleh
 * bertambah/berkurang sesudahnya karena letak sel dihitung ulang tiap tekan,
 * bukan disimpan sebagai koordinat di template.
 *
 * Dua hal yang tampak sepele tapi menentukan layar ini bisa dipakai atau tidak:
 *
 * 1. ←/→ hanya berpindah sel kalau kursor SUDAH di ujung teks. Kalau tidak,
 *    angka "12500" tak bisa disunting sama sekali — setiap panah melompat
 *    keluar. Itu sebabnya sel angka di tabel memakai type="text" +
 *    inputmode="decimal": pada type="number" selectionStart selalu null, jadi
 *    ujung teks tak bisa diketahui dan aturan ini mustahil ditegakkan.
 * 2. ↑/↓ berpindah baris pada KOLOM yang sama. Kasir menyusuri kolom qty ke
 *    bawah; melompat ke kolom lain memaksa tangannya kembali ke tetikus.
 */

const SEL = "[data-nav]";

function sel(el) {
  return el?.closest("tr") ? Array.from(el.closest("tr").querySelectorAll(SEL)) : [];
}

function barisan(wadah) {
  return Array.from(wadah.querySelectorAll("tr")).filter(
    (tr) => tr.querySelector(SEL));
}

function fokus(el) {
  if (!el) return;
  el.focus();
  el.select?.();
}

/** Kursor di ujung teks? Untuk isian yang tak punya kursor, anggap ya. */
function diUjung(el, arah) {
  const n = el.value?.length ?? 0;
  let awal;
  try {
    awal = el.selectionStart;
  } catch {
    return true;  // type=number & kawan-kawan: tak punya kursor yang bisa dibaca
  }
  if (awal === null || awal === undefined) return true;
  const akhir = el.selectionEnd ?? awal;
  return arah < 0 ? awal === 0 && akhir === 0 : awal === n && akhir === n;
}

/**
 * @param {import("vue").Ref<HTMLElement|null>} wadah pembungkus tabel
 * @param {{ keEntri?: () => void, hapusBaris?: (i: number) => void }} opsi
 * @returns {(e: KeyboardEvent) => void} handler untuk @keydown
 */
export function useGridNav(wadah, opsi = {}) {
  return function nav(e) {
    const el = e.target;
    if (!el?.matches?.(SEL) || e.altKey || e.metaKey) return;
    const kotak = sel(el);
    const kolom = kotak.indexOf(el);
    if (kolom < 0) return;

    const baris = barisan(wadah.value || el.closest("table") || document);
    const iBaris = baris.indexOf(el.closest("tr"));

    const keBaris = (arah) => {
      const tujuan = baris[iBaris + arah];
      if (!tujuan) return false;
      const sasaran = Array.from(tujuan.querySelectorAll(SEL));
      fokus(sasaran[Math.min(kolom, sasaran.length - 1)]);
      return true;
    };

    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      // Kotak satuan: ↑↓ memang untuk memilih satuan, seperti dropdown di
      // aplikasi desktop. Pindah barisnya diserahkan ke Tab/Enter/←→.
      if (el.tagName === "SELECT") return;
      const arah = e.key === "ArrowDown" ? 1 : -1;
      e.preventDefault();
      // Turun dari baris terakhir = pulang ke kotak cari. Di situlah barang
      // berikutnya diketik, jadi itu tujuan yang paling sering dituju.
      if (!keBaris(arah) && arah > 0) opsi.keEntri?.();
      return;
    }
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      const arah = e.key === "ArrowLeft" ? -1 : 1;
      if (!diUjung(el, arah)) return;      // masih menyunting angka
      const tujuan = kotak[kolom + arah];
      if (!tujuan) return;                 // ujung baris: biarkan Tab yang urus
      e.preventDefault();
      fokus(tujuan);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      // Enter di sel terakhir sebuah baris = selesai dengan baris itu.
      if (kolom + 1 < kotak.length) fokus(kotak[kolom + 1]);
      else opsi.keEntri?.();
      return;
    }
    if (e.key === "Delete" && e.ctrlKey && iBaris >= 0) {
      e.preventDefault();
      opsi.hapusBaris?.(iBaris);
      opsi.keEntri?.();
    }
  };
}
