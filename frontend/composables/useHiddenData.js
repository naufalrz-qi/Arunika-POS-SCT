import { computed } from "vue";
import { usePage } from "@inertiajs/vue3";

/**
 * Kunci nilai uang yang disembunyikan dari user ini.
 *
 * KOSMETIK. Yang benar-benar menahan datanya ada di server — field-nya tak
 * pernah dikirim (lihat _hidden_fields di apps/monitoring/views.py). Guna
 * composable ini cuma supaya tabel tidak menampilkan kolom yang seluruh selnya
 * berisi "-", dan kartu ringkasan tidak memamerkan Rp 0 yang menyesatkan.
 *
 * Jangan pernah menambahkan penyaringan baru DI SINI saja: menyembunyikan
 * kolom di Vue tak menahan apa pun, datanya tetap terbaca di tab Network.
 */
export function useHiddenData() {
  const page = usePage();
  // Dibaca di dalam computed: Inertia mengganti objek props tiap kunjungan,
  // jadi salinan yang diambil saat setup akan basi setelah ganti halaman.
  const hidden = computed(() => new Set(page.props.auth_user?.hidden_data_keys || []));

  const bisaLihat = (key) => !hidden.value.has(key);

  /** Buang kolom yang kuncinya dipetakan ke izin yang dicabut.
   *  `peta` = { namaKolom: kunciIzin }. Kolom yang tak disebut selalu lolos. */
  const saringKolom = (columns, peta) =>
    columns.filter((c) => !peta[c.key] || bisaLihat(peta[c.key]));

  return { hidden, bisaLihat, saringKolom };
}
