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

const URL = "/admin-panel/laporan/penjualan-nota";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Nota", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "customer", label: "Customer" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "potongan", label: "Potongan", align: "right", format: "rupiah" },
  { key: "pajak", label: "Pajak", align: "right", format: "rupiah" },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const customerOptions = computed(() => props.report?.options?.customer || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Total Kotor", value: rp.format(s.total_kotor || 0) },
    { label: "Total Potongan", value: rp.format(s.total_potongan || 0) },
    { label: "Total Pajak", value: rp.format(s.total_pajak || 0) },
    { label: "Total Bersih", value: rp.format(s.total_bersih || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Penjualan per Nota">
    <ReportPage
      title="Penjualan per Nota"
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
      @page-change="onPage"
      @sort-change="onSort"
    >
      <template #filters>
        <FilterPanel @submit="apply({ page: 1 })" @reset="reset">
          <DateRangeField v-model:from="form.date_from" v-model:to="form.date_to" />
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <SelectSearch v-model="form.kd_customer" :options="customerOptions" label="Customer" />
          <Input v-model="form.search" label="Cari" placeholder="no nota / customer" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
