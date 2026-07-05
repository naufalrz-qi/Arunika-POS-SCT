<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/pembelian";

const filterDefs = [
  { key: "no_transaksi", label: "No. Transaksi", type: "text" },
  { key: "no_order", label: "No Order", type: "text" },
  { key: "supplier", label: "Supplier", type: "text" },
  { key: "barang", label: "Barang", type: "text" },
  { key: "qty", label: "Qty", type: "number_range" },
  { key: "harga", label: "Harga Beli", type: "number_range" },
  { key: "subtotal", label: "Subtotal", type: "number_range" },
];

const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "no_order", label: "No Order" },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "supplier", label: "Supplier" },
  { key: "note", label: "Note" },
  { key: "barang", label: "Barang" },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "satuan", label: "Satuan" },
  { key: "harga", label: "Harga Beli", align: "right", format: "rupiah" },
  { key: "diskon_item1", label: "Diskon Item 1", align: "right", format: "rupiah" },
  { key: "diskon_item2", label: "Diskon Item 2", align: "right", format: "rupiah" },
  { key: "diskon_item3", label: "Diskon Item 3", align: "right", format: "rupiah" },
  { key: "diskon_item4", label: "Diskon Item 4", align: "right", format: "rupiah" },
  { key: "diskon_total1", label: "Diskon Total 1", align: "right", format: "rupiah" },
  { key: "diskon_total2", label: "Diskon Total 2", align: "right", format: "rupiah" },
  { key: "diskon_total3", label: "Diskon Total 3", align: "right", format: "rupiah" },
  { key: "diskon_total4", label: "Diskon Total 4", align: "right", format: "rupiah" },
  { key: "pajak", label: "Pajak", align: "right", format: "number" },
  { key: "ppnbm", label: "PPnBM", align: "right", format: "number" },
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
          <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
          <SelectSearch v-model="form.kd_supplier" :options="supplierOptions" label="Supplier" />
          <Input v-model="form.search" label="Cari" placeholder="no transaksi / barang / supplier" />
          <ColumnFilters :filter-defs="filterDefs" :form="form" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
