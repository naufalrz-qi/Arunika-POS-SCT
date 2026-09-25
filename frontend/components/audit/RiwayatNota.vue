<script setup>
// Riwayat satu nota dari DUA sumber, berdampingan:
//
// 1. Dicatat Arunika (pangkal): akun Arunika, alasan yang diketik, isi
//    sebelum/sesudah. Hal-hal yang tak pernah ada di database legacy.
// 2. Log server legacy (tbl_log_transaksi): setiap versi nota, termasuk edit
//    dari aplikasi POS lama yang tak pernah lewat Arunika.
//
// Edit lewat Arunika tercatat di keduanya; peristiwa legacy miliknya diberi
// lencana "via Arunika" (dicocokkan lewat rentang id log di server), supaya
// satu edit tak terbaca sebagai dua.
import { ref, watch } from "vue";
import axios from "axios";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import Spinner from "@/components/ui/Spinner.vue";
import SelisihNota from "@/components/audit/SelisihNota.vue";
import { ACTION_LABELS, LABEL_KOLOM_NOTA } from "@/utils/labels";
import { tanggalJam } from "@/utils/tanggal";

const props = defineProps({
  url: { type: String, required: true },
  no: { type: String, default: "" },
  koneksi: { type: String, default: "" },
  // Naikkan untuk memuat ulang (mis. sesudah nota disimpan).
  muatUlang: { type: Number, default: 0 },
});

const memuat = ref(false);
const galat = ref("");
const data = ref(null);

async function muat() {
  if (!props.no) {
    data.value = null;
    return;
  }
  memuat.value = true;
  galat.value = "";
  try {
    const { data: d } = await axios.get(props.url, {
      params: { no: props.no, koneksi: props.koneksi || undefined },
    });
    data.value = d;
  } catch (e) {
    galat.value = e.response?.data?.error || "Riwayat nota gagal dimuat.";
    data.value = null;
  } finally {
    memuat.value = false;
  }
}
watch(() => [props.no, props.koneksi, props.muatUlang], muat, { immediate: true });

const nf = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 });
const WARNA = { Dibuat: "success", "Dibuat ulang": "warning", Diedit: "brand" };
const adaBarang = (b) => b && ((b.ditambah || []).length || (b.dihapus || []).length || (b.diubah || []).length);
</script>

<template>
  <div class="space-y-4">
    <div v-if="memuat" class="flex items-center gap-2 text-sm text-ink-muted">
      <Spinner /> Memuat riwayat…
    </div>
    <Banner v-if="galat" variant="warning" :message="galat" />

    <template v-if="data && !memuat">
      <section>
        <h4 class="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">Dicatat Arunika</h4>
        <p v-if="!data.arunika.length" class="text-sm text-ink-subtle">
          Belum pernah diedit atau dicoba diedit lewat Arunika.
        </p>
        <ol v-else class="space-y-2">
          <li v-for="a in data.arunika" :key="a.id" class="rounded-lg border border-border-default p-3">
            <div class="flex flex-wrap items-center gap-2 text-sm">
              <Badge :variant="a.aksi === 'edit_nota' ? 'brand' : 'danger'">{{ ACTION_LABELS[a.aksi] || a.aksi }}</Badge>
              <span class="text-ink">{{ tanggalJam(a.waktu) }}</span>
              <span class="text-ink-muted">oleh</span>
              <span class="font-medium text-ink">{{ a.user }}</span>
              <span v-if="a.ip" class="text-xs text-ink-subtle">· {{ a.ip }}</span>
            </div>
            <p v-if="a.alasan" class="mt-1 text-sm text-ink">Alasan: “{{ a.alasan }}”</p>
            <p v-if="a.aksi !== 'edit_nota'" class="mt-1 text-sm text-ink-muted">{{ a.detail }}</p>
            <SelisihNota v-if="a.selisih" class="mt-2" :selisih="a.selisih" :total="a.total" />
          </li>
        </ol>
      </section>

      <section>
        <h4 class="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-subtle">Log server legacy</h4>
        <p v-if="!data.legacy.siap" class="text-sm text-ink-subtle">{{ data.legacy.pesan }}</p>
        <template v-else>
          <Banner
            v-if="data.legacy.barang_cocok === false"
            variant="warning"
            class="mb-2"
            message="Riwayat barang dari log mungkin tidak lengkap (log dipangkas, atau server ini tak mencatat penghapusan baris). Siapa dan kapan tetap benar."
          />
          <ol class="space-y-2">
            <li v-for="(p, i) in data.legacy.peristiwa" :key="i" class="rounded-lg border border-border-default p-3">
              <div class="flex flex-wrap items-center gap-2 text-sm">
                <Badge :variant="WARNA[p.aksi] || 'neutral'">{{ p.aksi }}</Badge>
                <span class="text-ink">{{ tanggalJam(p.waktu) }}</span>
                <span class="text-ink-muted">oleh</span>
                <span class="font-medium text-ink">{{ p.user_nama || p.kd_user }}</span>
                <span class="font-mono text-xs text-ink-subtle">{{ p.kd_user }}</span>
                <Badge v-if="p.via_arunika" variant="neutral">via Arunika · {{ p.via_arunika }}</Badge>
                <Badge v-else-if="p.aksi === 'Diedit'" variant="warning">aplikasi lama</Badge>
              </div>
              <ul v-if="p.perubahan && p.perubahan.length" class="mt-2 space-y-0.5 text-sm">
                <li v-for="(c, j) in p.perubahan" :key="j" class="text-ink-muted">
                  {{ LABEL_KOLOM_NOTA[c.kolom] || c.kolom }}:
                  <span class="text-ink line-through decoration-ink-subtle">{{ c.dari || "(kosong)" }}</span>
                  → <span class="text-ink">{{ c.ke || "(kosong)" }}</span>
                </li>
              </ul>
              <p v-if="p.barang && p.barang.isi" class="mt-2 text-sm text-ink-muted">
                Isi awal: {{ p.barang.isi.length }} barang —
                <span v-for="(b, j) in p.barang.isi" :key="j">
                  <template v-if="j">, </template>{{ b.kd_barang }} × {{ nf.format(b.qty) }}
                </span>
              </p>
              <div v-else-if="adaBarang(p.barang)" class="mt-2 space-y-0.5 text-sm">
                <p v-for="(b, j) in p.barang.ditambah" :key="`t${j}`" class="text-success-fg">
                  + {{ b.kd_barang }} × {{ nf.format(b.qty) }}
                </p>
                <p v-for="(b, j) in p.barang.dihapus" :key="`h${j}`" class="text-danger-fg">
                  − {{ b.kd_barang }} × {{ nf.format(b.qty) }}
                </p>
                <p v-for="(b, j) in p.barang.diubah" :key="`u${j}`" class="text-ink">
                  ~ {{ b.kd_barang }}: qty {{ nf.format(b.qty_dari) }} → {{ nf.format(b.qty) }}
                </p>
              </div>
            </li>
          </ol>
        </template>
      </section>
    </template>
  </div>
</template>
