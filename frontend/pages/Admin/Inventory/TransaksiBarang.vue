<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/inventory/transaksi";

const JENIS_OPTIONS = [
  { value: "pembelian", label: "Pembelian" },
  { value: "penjualan", label: "Penjualan" },
  { value: "retur_pembelian", label: "Retur Pembelian" },
  { value: "retur_penjualan", label: "Retur Penjualan" },
  { value: "opname_masuk", label: "Opname Masuk" },
  { value: "opname_keluar", label: "Opname Keluar" },
  { value: "mutasi_masuk", label: "Mutasi Masuk" },
  { value: "mutasi_keluar", label: "Mutasi Keluar" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters, []);

// jenis dikelola sebagai array checkbox, disinkron ke form.jenis (CSV) saat submit.
const jenisSel = ref((props.filters.jenis || "").split(",").filter(Boolean));

function submit() {
  form.jenis = jenisSel.value.join(",");
  apply({ page: 1 });
}
function onReset() {
  jenisSel.value = [];
  reset();
}

const columns = [
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "transaksi", label: "Jenis", sortable: true },
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "masuk", label: "Masuk", align: "right", format: "number" },
  { key: "keluar", label: "Keluar", align: "right", format: "number" },
  { key: "satuan", label: "Satuan" },
  { key: "harga", label: "Harga", align: "right", format: "rupiah" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Total Masuk", value: nf.format(s.total_masuk || 0) },
    { label: "Total Keluar", value: nf.format(s.total_keluar || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Transaksi Barang">
    <ReportPage
      title="Transaksi Barang"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="_rid"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      :recent="!!filters.recent"
      @page-change="onPage"
      @sort-change="onSort"
      @per-page-change="onPerPage"
    >
      <template #filters>
        <FilterPanel @submit="submit" @reset="onReset">
          <DateModeField
            label="Tanggal"
            :mode="form.date_mode"
            :from="form.date_from"
            :to="form.date_to"
            :date="form.date"
            @update:mode="form.date_mode = $event"
            @update:from="form.date_from = $event"
            @update:to="form.date_to = $event"
            @update:date="form.date = $event"
          />
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <Input v-model="form.search" label="Cari" placeholder="no transaksi / kode / barang" />
          <div class="sm:col-span-2 lg:col-span-4">
            <span class="mb-1.5 block text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted">
              Jenis Transaksi
            </span>
            <div class="flex flex-wrap gap-x-4 gap-y-2">
              <label
                v-for="opt in JENIS_OPTIONS"
                :key="opt.value"
                class="flex items-center gap-2 text-sm text-ink"
              >
                <input type="checkbox" :value="opt.value" v-model="jenisSel" class="accent-brand-600" />
                {{ opt.label }}
              </label>
            </div>
            <p class="mt-1 text-xs text-ink-subtle">
              Kosongkan = semua jenis. Tanpa tanggal = transaksi setelah tutup buku;
              isi rentang tanggal untuk menembus sebelum tutup buku.
            </p>
          </div>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
