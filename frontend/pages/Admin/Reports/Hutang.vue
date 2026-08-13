<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/hutang";

const filterDefs = [
  { key: "no_transaksi", label: "No. Nota", type: "text" },
  { key: "supplier", label: "Supplier", type: "text" },
  { key: "jatuh_tempo", label: "Jatuh Tempo", type: "date" },
  { key: "total_pembelian", label: "Total Pembelian", type: "number_range" },
  { key: "sisa_hutang", label: "Sisa Hutang", type: "number_range" },
  { key: "hari_terlambat", label: "Hari Terlambat", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_transaksi", label: "No. Nota" },
  { key: "tanggal", label: "Tanggal", format: "date" },
  { key: "supplier", label: "Supplier" },
  { key: "jatuh_tempo", label: "Jatuh Tempo", format: "date" },
  { key: "total_pembelian", label: "Total Pembelian", align: "right", format: "rupiah" },
  { key: "total_cicilan", label: "Total Cicilan", align: "right", format: "rupiah" },
  { key: "sisa_hutang", label: "Sisa Hutang", align: "right", format: "rupiah" },
  { key: "hari_terlambat", label: "Hari Terlambat", align: "right", format: "number" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const supplierOptions = computed(() => props.report?.options?.supplier || []);
// Cicilan hutang tak pernah tercatat di server mana pun (t_hutang_cicilan nol
// baris di semuanya), jadi "Sisa Hutang" di sini = total pembelian kredit, bukan
// saldo terverifikasi. Dikatakan hanya kalau memang nol — begitu ada yang mulai
// mencatat, kalimatnya hilang sendiri.
const cicilanKosong = computed(() => {
  const s = props.report?.summary;
  return Boolean(s) && Number(s.jml_nota || 0) > 0 && Number(s.total_cicilan || 0) === 0;
});
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Nota", value: nf.format(s.jml_nota || 0) },
    { label: "Total Pembelian", value: rp.format(s.total_pembelian || 0) },
    { label: "Total Cicilan", value: rp.format(s.total_cicilan || 0) },
    { label: "Sisa Hutang", value: rp.format(s.total_sisa_hutang || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Hutang Supplier">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_transaksi"
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
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateModeField
              class="sm:col-span-2"
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
            <SelectSearch v-model="form.kd_supplier" :options="supplierOptions" label="Supplier" />
            <Input v-model="form.search" label="Cari" placeholder="no nota" />
          </FilterSection>
          <template #lanjutan>
            <FilterSection title="Pencarian Lanjutan">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['text', 'category']" />
            </FilterSection>
            <FilterSection title="Rentang Nilai">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['number_range']" />
            </FilterSection>
            <FilterSection title="Jatuh Tempo">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['date']" />
            </FilterSection>
          </template>
        </FilterPanel>
      </template>
      <template #peringatan>
        <Banner
          v-if="cicilanKosong"
          variant="info"
          message="Pembayaran hutang tidak pernah dicatat di server ini, jadi kolom Cicilan nol dan Sisa Hutang sama dengan total pembelian kredit — angka terhutang menurut nota, bukan saldo yang sudah dicocokkan."
        />
      </template>
    </ReportPage>
  </AdminLayout>
</template>
