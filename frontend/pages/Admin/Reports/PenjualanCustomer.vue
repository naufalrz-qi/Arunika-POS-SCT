<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/penjualan-customer";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "customer", label: "Customer", sortable: true },
  { key: "kota", label: "Kota" },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number", sortable: true },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Customer", value: nf.format(s.jml_customer || 0) },
    { label: "Total Nota", value: nf.format(s.total_nota || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Penjualan per Customer">
    <ReportPage
      title="Penjualan per Customer"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_customer"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      @page-change="onPage"
      @sort-change="onSort"
    >
      <template #filters>
        <FilterPanel @submit="apply({ page: 1 })" @reset="reset">
          <DateRangeField v-model:from="form.date_from" v-model:to="form.date_to" />
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <Input v-model="form.search" label="Cari" placeholder="customer / kota" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
