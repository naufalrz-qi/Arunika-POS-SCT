<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Select from "@/components/ui/Select.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/penjualan-periode";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "periode", label: "Periode", sortable: true },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "total_diskon", label: "Total Diskon", align: "right", format: "rupiah" },
  { key: "total_pajak", label: "Total Pajak", align: "right", format: "rupiah" },
  { key: "total", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const granularitasOptions = [
  { value: 'harian', label: 'Harian' },
  { value: 'bulanan', label: 'Bulanan' }
];
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Periode", value: nf.format(s.jml_periode || 0) },
    { label: "Total Nota", value: nf.format(s.total_nota || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Penjualan per Periode">
    <ReportPage
      title="Penjualan per Periode"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="periode"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      :recent="!!filters.recent"
      @page-change="onPage"
      @sort-change="onSort"
    >
      <template #filters>
        <FilterPanel @submit="apply({ page: 1 })" @reset="reset">
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
          <Select v-model="form.granularitas" :options="granularitasOptions" label="Granularitas" />
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
