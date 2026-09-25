<script setup>
// Jejak Audit — jejak SEMUA akun (menu teknis). Log Aktivitas tetap "jejak
// saya"; layar ini untuk memeriksa siapa mengubah apa, kapan, dari mana, dengan
// isi sebelum/sesudah dan riwayat per nota (termasuk edit dari aplikasi lama).
//
// Penyaring & halaman di SERVER (satu query per halaman), bukan 300 baris
// terpotong yang disaring di peramban — kekeliruan lama Log Aktivitas.
import { computed, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelisihNota from "@/components/audit/SelisihNota.vue";
import RiwayatNota from "@/components/audit/RiwayatNota.vue";
import { ACTION_LABELS, LABEL_KOLOM_NOTA } from "@/utils/labels";
import { tanggalJam } from "@/utils/tanggal";

const props = defineProps({
  jejak: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  users: { type: Array, default: () => [] },
  aksi_list: { type: Array, default: () => [] },
  koneksi_list: { type: Array, default: () => [] },
});

const URL = "/admin-panel/audit";
const j = computed(() => props.jejak || {});

const f = ref({
  dari: props.filters.dari || "",
  sampai: props.filters.sampai || "",
  user: props.filters.user || "",
  aksi: props.filters.aksi || "",
  koneksi: props.filters.koneksi || "",
  no: props.filters.no || "",
});
const opsi = (daftar, label = (x) => x) => daftar.map((x) => ({ value: x, label: label(x) }));
const userOpsi = computed(() => opsi(props.users));
const aksiOpsi = computed(() => opsi(props.aksi_list, (a) => ACTION_LABELS[a] || a));
const koneksiOpsi = computed(() => opsi(props.koneksi_list));

function terapkan(page = 1) {
  const params = Object.fromEntries(Object.entries(f.value).filter(([, v]) => v));
  if (page > 1) params.page = page;
  router.get(URL, params, { preserveState: true, preserveScroll: true, replace: true });
}
function reset() {
  f.value = { dari: "", sampai: "", user: "", aksi: "", koneksi: "", no: "" };
  terapkan();
}

const WARNA = {
  edit_nota: "brand", edit_nota_ditolak: "danger", login_gagal: "danger", login_terkunci: "danger",
  koreksi_stok: "warning", konfigurasi: "warning", menu: "warning", tautan_user: "warning",
};

// --- Detail satu jejak -----------------------------------------------------
const detail = ref(null);
const detailMuat = ref(false);
const detailGalat = ref("");
async function buka(r) {
  detail.value = { baris: r, data: null };
  detailMuat.value = true;
  detailGalat.value = "";
  try {
    const { data } = await axios.get(`${URL}/detail`, { params: { id: r.id } });
    detail.value = data;
  } catch (e) {
    detailGalat.value = e.response?.data?.error || "Detail jejak gagal dimuat.";
  } finally {
    detailMuat.value = false;
  }
}
const isi = computed(() => detail.value?.data || null);
const kepalaSebelum = computed(() => isi.value?.sebelum?.kepala || null);

// --- Keutuhan rantai hash ---------------------------------------------------
const rantai = ref(null);
const rantaiMuat = ref(false);
async function periksa() {
  rantaiMuat.value = true;
  try {
    const { data } = await axios.get(`${URL}/periksa`);
    rantai.value = data;
  } catch (e) {
    rantai.value = { error: e.response?.data?.error || "Pemeriksaan gagal." };
  } finally {
    rantaiMuat.value = false;
  }
}

// --- Riwayat per nota --------------------------------------------------------
const riwayat = ref(null); // { no, koneksi }
</script>

<template>
  <AdminLayout title="Jejak Audit">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-sm text-ink-muted">
        Jejak seluruh akun. Baris sejak fitur ini dirangkai hash, sehingga baris yang diubah atau
        dihapus langsung di database terdeteksi.
      </p>
      <Button variant="secondary" :loading="rantaiMuat" @click="periksa">Periksa keutuhan</Button>
    </div>
    <template v-if="rantai">
      <Banner v-if="rantai.error" variant="warning" :message="rantai.error" class="mb-4" />
      <Banner
        v-else-if="rantai.putus"
        variant="danger"
        class="mb-4"
        :message="`Rantai PUTUS di jejak #${rantai.putus.id}: ${rantai.putus.sebab}. ${rantai.jumlah} baris diperiksa sampai titik itu.`"
      />
      <Banner v-else variant="info" class="mb-4" :message="`Rantai utuh: ${rantai.jumlah} baris jejak terverifikasi.`" />
    </template>

    <FilterPanel @submit="terapkan()" @reset="reset">
      <FilterSection title="Periode & Pencarian">
        <DateRangeField class="sm:col-span-2" v-model:from="f.dari" v-model:to="f.sampai" />
        <Input v-model="f.no" label="Nomor dokumen" placeholder="mis. SC2609" />
        <SelectSearch v-model="f.user" :options="userOpsi" label="User" />
        <SelectSearch v-model="f.aksi" :options="aksiOpsi" label="Aksi" />
        <SelectSearch v-model="f.koneksi" :options="koneksiOpsi" label="Koneksi" />
      </FilterSection>
    </FilterPanel>

    <Deferred data="jejak">
      <template #fallback><LoadingCard message="Mengambil jejak…" /></template>
      <Banner v-if="j.ditolak" variant="danger" :message="j.ditolak" class="mb-4" />
      <Card v-else>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Waktu</th>
                <th class="px-2 py-1 text-left font-medium">User</th>
                <th class="px-2 py-1 text-left font-medium">Aksi</th>
                <th class="px-2 py-1 text-left font-medium">Dokumen</th>
                <th class="px-2 py-1 text-left font-medium">Detail / alasan</th>
                <th class="px-2 py-1 text-left font-medium">IP</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in j.rows" :key="r.id" class="border-b border-border-default align-top">
                <td class="whitespace-nowrap px-2 py-1.5 tabular-nums text-ink-muted">{{ tanggalJam(r.waktu) }}</td>
                <td class="px-2 py-1.5 text-ink">{{ r.user }}</td>
                <td class="whitespace-nowrap px-2 py-1.5">
                  <Badge :variant="WARNA[r.aksi] || 'neutral'">{{ ACTION_LABELS[r.aksi] || r.aksi }}</Badge>
                </td>
                <td class="px-2 py-1.5">
                  <template v-if="r.no_dokumen">
                    <button
                      class="font-mono text-brand-fg hover:underline"
                      title="Lihat riwayat nota ini"
                      @click="riwayat = { no: r.no_dokumen, koneksi: r.koneksi }"
                    >{{ r.no_dokumen }}</button>
                    <p class="text-xs text-ink-subtle">{{ r.koneksi }}</p>
                  </template>
                  <span v-else class="text-xs text-ink-subtle">{{ r.koneksi || "—" }}</span>
                </td>
                <td class="px-2 py-1.5">
                  <p class="text-ink-muted">{{ r.detail }}</p>
                  <p v-if="r.alasan" class="text-ink">“{{ r.alasan }}”</p>
                </td>
                <td class="px-2 py-1.5 font-mono text-xs text-ink-subtle">{{ r.ip }}</td>
                <td class="px-2 py-1.5 text-right">
                  <Button v-if="r.ada_data" size="sm" variant="ghost" @click="buka(r)">Isi</Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!(j.rows || []).length" class="py-6 text-center text-sm text-ink-subtle">
          Tidak ada jejak untuk penyaring ini.
        </p>
        <div class="mt-3 flex items-center justify-between text-sm text-ink-muted">
          <span>{{ j.total || 0 }} jejak · halaman {{ j.page || 1 }} dari {{ j.pages || 1 }}</span>
          <div class="flex gap-2">
            <Button size="sm" variant="secondary" :disabled="(j.page || 1) <= 1" @click="terapkan((j.page || 1) - 1)">Sebelumnya</Button>
            <Button size="sm" variant="secondary" :disabled="(j.page || 1) >= (j.pages || 1)" @click="terapkan((j.page || 1) + 1)">Berikutnya</Button>
          </div>
        </div>
      </Card>
    </Deferred>

    <Modal :show="!!detail" title="Isi jejak" size="lg" @close="detail = null">
      <div v-if="detailMuat" class="flex items-center gap-2 text-sm text-ink-muted"><Spinner /> Memuat…</div>
      <Banner v-else-if="detailGalat" variant="warning" :message="detailGalat" />
      <template v-else-if="detail">
        <p class="text-sm text-ink-muted">
          {{ tanggalJam(detail.baris.waktu) }} · {{ detail.baris.user }} · {{ detail.baris.koneksi }}
          <span v-if="detail.baris.ip">· {{ detail.baris.ip }}</span>
        </p>
        <p v-if="detail.baris.alasan" class="mt-1 text-sm text-ink">Alasan: “{{ detail.baris.alasan }}”</p>
        <template v-if="isi && isi.selisih">
          <h4 class="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-ink-subtle">Perubahan</h4>
          <SelisihNota :selisih="isi.selisih" :total="{ dari: isi.sebelum?.total, ke: isi.sesudah?.total }" />
          <details v-if="kepalaSebelum" class="mt-3 text-sm">
            <summary class="cursor-pointer text-xs text-brand-fg">Isi nota SEBELUM diedit</summary>
            <ul class="mt-1 space-y-0.5 text-ink-muted">
              <li v-for="(v, k) in kepalaSebelum" :key="k">{{ LABEL_KOLOM_NOTA[k] || k }}: <span class="text-ink">{{ v }}</span></li>
            </ul>
            <ul class="mt-2 space-y-0.5 text-ink-muted">
              <li v-for="(b, i) in isi.sebelum.baris" :key="i">
                {{ b.nama || b.kd_barang }} ({{ b.satuan || b.kd_satuan }}) × {{ b.qty }} @ {{ b.harga_jual }}
              </li>
            </ul>
          </details>
          <p v-if="isi.log_id" class="mt-2 text-xs text-ink-subtle">
            Log server legacy #{{ isi.log_id[0] + 1 }}–{{ isi.log_id[1] }} · skema {{ isi.skema }}
          </p>
        </template>
        <pre v-else-if="isi" class="mt-3 max-h-80 overflow-auto rounded bg-surface-2 p-2 text-xs">{{ JSON.stringify(isi, null, 2) }}</pre>
      </template>
    </Modal>

    <Modal :show="!!riwayat" :title="riwayat ? `Riwayat nota ${riwayat.no}` : ''" size="lg" @close="riwayat = null">
      <RiwayatNota v-if="riwayat" :url="`${URL}/riwayat`" :no="riwayat.no" :koneksi="riwayat.koneksi" />
    </Modal>
  </AdminLayout>
</template>
