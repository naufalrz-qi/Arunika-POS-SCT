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

const URL = "/admin-panel/laporan/pembelian";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "supplier", label: "Supplier" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "harga_beli", label: "Harga Beli", align: "right", format: "rupiah" },
  { key: "subtotal", label: "Subtotal", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const supplierOptions = computed(() => props.report?.options?.supplier || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Total Qty", value: nf.format(s.total_qty || 0) },
    { label: "Total Nilai", value: rp.format(s.total_nilai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Pembelian">
    <ReportPage
      title="Pembelian"
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
          <SelectSearch v-model="form.kd_supplier" :options="supplierOptions" label="Supplier" />
          <Input v-model="form.search" label="Cari" placeholder="no transaksi / barang / supplier" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
