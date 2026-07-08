<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/penjualan-user";

const filterDefs = [
  { key: "no_transaksi", label: "No. Transaksi", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "user", label: "User", type: "text" },
  {
    key: "status",
    label: "Status",
    type: "category",
    options: [
      { value: "Kredit", label: "Kredit" },
      { value: "Tunai", label: "Tunai" },
      { value: "Lunas", label: "Lunas" },
    ],
  },
  { key: "nominal", label: "Nominal", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

// Detail per-transaksi (grain mengikuti view legacy mon_t_penjualan_per_user),
// bukan agregat per user seperti sebelumnya.
const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "status", label: "Status Transaksi" },
  { key: "customer", label: "Customer", sortable: true },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah", sortable: true },
  { key: "user", label: "User", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Nota", value: nf.format(s.jml_nota || 0) },
    { label: "Jumlah User", value: nf.format(s.jml_user || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Penjualan per User">
    <ReportPage
      title="Penjualan per User"
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
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <ColumnFilters :filter-defs="filterDefs" :form="form" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
