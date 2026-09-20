<script setup>
import { ref, computed, reactive } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import Select from "@/components/ui/Select.vue";
import Modal from "@/components/ui/Modal.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});
const rows = computed(() => props.data?.rows || []);

// Nama fitur yang manusiawi. Yang tak terdaftar tampil apa adanya, jadi fitur
// baru yang mulai mencatat tidak pernah tampil kosong — hanya kurang rapi.
const FEATURE_LABEL = {
  harga: "Harga",
  m_barang: "Produk",
  m_customer: "Pelanggan",
  m_supplier: "Supplier",
  hub_pull: "Tarik AMPHOREUS",
  feed_sync: "Fan-out Master",
  harga_sync: "Sebar Harga",
  transfer: "Transfer Arunika",
  backup: "Cadangan",
  mode_arunika: "Mode Laporan",
};
const featureOptions = computed(() => [
  { value: "", label: "Semua fitur" },
  ...(props.data?.fitur_tersedia || []).map((f) => ({ value: f, label: FEATURE_LABEL[f] || f })),
]);
const STATUS_OPTIONS = [
  { value: "", label: "Semua status" },
  { value: "ok", label: "Berhasil" },
  { value: "partial", label: "Sebagian" },
  { value: "failed", label: "Gagal" },
  { value: "berjalan", label: "Berjalan" },
];
const HARI_OPTIONS = [
  { value: "1", label: "24 jam terakhir" },
  { value: "7", label: "7 hari" },
  { value: "30", label: "30 hari" },
  { value: "90", label: "90 hari" },
  { value: "365", label: "1 tahun" },
];

const form = reactive({
  feature: props.filters.feature || "",
  status: props.filters.status || "",
  hari: String(props.filters.hari || 30),
});

function terapkan() {
  router.get("/admin-panel/master/sync-history", { ...form }, {
    preserveState: true,
    preserveScroll: true,
  });
}
function reset() {
  form.feature = "";
  form.status = "";
  form.hari = "30";
  terapkan();
}

const columns = [
  { key: "created_at", label: "Waktu", sortable: true, format: "datetime" },
  { key: "user", label: "Pelaku" },
  { key: "feature", label: "Fitur" },
  { key: "src", label: "Sumber" },
  { key: "dst", label: "Tujuan" },
  { key: "mode", label: "Mode" },
  { key: "compared", label: "Diperiksa", align: "right", format: "number" },
  // "Diterapkan", bukan "Baris": satu-satunya label yang benar untuk enam fitur
  // sekaligus — SKU yang disebar, baris feed yang masuk, nota yang ditarik.
  { key: "total_items", label: "Diterapkan", align: "right", format: "number" },
  { key: "durasi_detik", label: "Durasi (dtk)", align: "right", format: "number" },
  { key: "status", label: "Status" },
];
const detail = ref(null);

function statusVariant(v) {
  if (v === "ok") return "success";
  if (v === "failed") return "danger";
  return "warning";
}
</script>

<template>
  <AdminLayout title="Riwayat Operasi">
    <!-- Filter di LUAR <Deferred>: panelnya harus bisa dipakai sebelum datanya
         datang, dan router.get memicu ulang muatan deferred-nya sendiri. -->
    <FilterPanel class="mb-4" @submit="terapkan" @reset="reset">
      <Select v-model="form.feature" label="Fitur" :options="featureOptions" />
      <Select v-model="form.status" label="Status" :options="STATUS_OPTIONS" />
      <Select v-model="form.hari" label="Rentang" :options="HARI_OPTIONS" />
    </FilterPanel>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil riwayat…" /></template>
      <ReportView
        title="Riwayat Operasi"
        :columns="columns"
        :rows="rows"
        row-key="id"
        :search-keys="['user', 'src', 'dst', 'mode']"
        export-name="riwayat-operasi"
        sheet-name="Riwayat Operasi"
        :conn-error="data && data.conn_error"
      >
        <template #cell-feature="{ value }">{{ FEATURE_LABEL[value] || value }}</template>
        <template #cell-status="{ value }">
          <Badge :variant="statusVariant(value)">{{ value }}</Badge>
        </template>
        <template #cell-total_items="{ row, value }">
          <button class="text-brand-fg underline" @click="detail = row">{{ value }}</button>
        </template>
      </ReportView>
    </Deferred>

    <Modal :show="!!detail" title="Rincian Operasi" size="lg" @close="detail = null">
      <p v-if="detail?.detail?.items?.length === 0" class="py-2 text-sm text-ink-muted">
        Tidak ada rincian yang dicatat untuk operasi ini.
      </p>
      <!-- Dua bentuk rincian dalam satu tabel. Sync harga/master mencatat
           perubahan per-item (label/kode/changes); job latar mencatat baris teks
           ({teks}). Membedakannya di sini lebih murah daripada memaksa job latar
           mengarang "kode" yang tak ada artinya. -->
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left">
            <th class="py-1.5 text-[11px] font-semibold text-ink-muted text-left">Item</th>
            <th class="py-1.5 text-[11px] font-semibold text-ink-muted text-left">Kode</th>
            <th class="py-1.5 text-[11px] font-semibold text-ink-muted text-left">Perubahan</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(it, i) in (detail?.detail?.items || [])" :key="i" class="border-t border-border-default">
            <template v-if="it.teks">
              <td class="py-1" colspan="3">{{ it.teks }}</td>
            </template>
            <template v-else>
              <td class="py-1">{{ it.label }}</td>
              <td class="py-1">{{ it.kode }}</td>
              <td class="py-1">
                <div v-for="(c, j) in it.changes" :key="j">
                  {{ c.field }}: <span class="text-ink-muted">{{ c.before ?? "—" }}</span> → <span class="font-semibold text-ink">{{ c.after }}</span>
                </div>
              </td>
            </template>
          </tr>
        </tbody>
      </table>
      <p v-if="detail?.status === 'failed'" class="mt-3 text-sm text-danger-fg">
        {{ detail.error || "Operasi gagal — lihat kolom galat di baris." }}
      </p>
    </Modal>
  </AdminLayout>
</template>
