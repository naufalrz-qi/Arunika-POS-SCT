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

const URL = "/admin-panel/laporan/retur-penjualan";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_retur", label: "No. Retur", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "customer", label: "Customer" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "nilai", label: "Nilai", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const customerOptions = computed(() => props.report?.options?.customer || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Retur", value: nf.format(s.jml_retur || 0) },
    { label: "Total Qty", value: nf.format(s.total_qty || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Retur Penjualan">
    <ReportPage
      title="Retur Penjualan"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="no_retur"
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
          <SelectSearch v-model="form.kd_customer" :options="customerOptions" label="Customer" />
          <Input v-model="form.search" label="Cari" placeholder="no retur / barang / customer" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
