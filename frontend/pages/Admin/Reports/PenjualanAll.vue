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

const URL = "/admin-panel/laporan/penjualan";

const filterDefs = [
  { key: "no_transaksi", label: "No. Transaksi", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "barang", label: "Barang", type: "text" },
  { key: "kd_barang", label: "Kode Barang", type: "text" },
  { key: "kategori", label: "Kategori", type: "text" },
  { key: "sales", label: "Sales", type: "text" },
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
  { key: "qty", label: "Qty", type: "number_range" },
  { key: "harga", label: "Harga", type: "number_range" },
  { key: "subtotal", label: "Subtotal", type: "number_range" },
  { key: "jth_tempo", label: "Jth. Tempo", type: "date" },
];

const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi", sortable: true },
  { key: "customer", label: "Customer" },
  { key: "kota", label: "Kota" },
  { key: "jth_tempo", label: "Jth. Tempo", format: "date" },
  { key: "status", label: "Status" },
  { key: "keterangan", label: "Ket." },
  { key: "kd_barang", label: "Kode Barang" },
  { key: "barang", label: "Barang" },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "sales", label: "Sales", sortable: true },
  { key: "qty", label: "Qty", align: "right", format: "number" },
  { key: "satuan", label: "Satuan" },
  { key: "harga", label: "Harga", align: "right", format: "rupiah" },
  { key: "dd1", label: "DD1", align: "right", format: "rupiah" },
  { key: "dd2", label: "DD2", align: "right", format: "rupiah" },
  { key: "dd3", label: "DD3", align: "right", format: "rupiah" },
  { key: "dd4", label: "DD4", align: "right", format: "rupiah" },
  { key: "dt1", label: "DT1", align: "right", format: "rupiah" },
  { key: "dt2", label: "DT2", align: "right", format: "rupiah" },
  { key: "dt3", label: "DT3", align: "right", format: "rupiah" },
  { key: "dt4", label: "DT4", align: "right", format: "rupiah" },
  { key: "harga_bersih", label: "Harga Bersih", align: "right", format: "rupiah" },
  { key: "subtotal", label: "Subtotal", align: "right", format: "rupiah", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
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
  <AdminLayout title="Penjualan (Detail)">
    <ReportPage
      title="Penjualan (Detail)"
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
          <Input v-model="form.search" label="Cari" placeholder="no transaksi / barang / customer" />
          <ColumnFilters :filter-defs="filterDefs" :form="form" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
