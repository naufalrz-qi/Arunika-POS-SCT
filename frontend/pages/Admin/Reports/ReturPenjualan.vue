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

const URL = "/admin-panel/laporan/retur-penjualan";

const filterDefs = [
  { key: "no_retur", label: "No. Retur", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "barang", label: "Barang", type: "text" },
  { key: "sales", label: "Sales", type: "text" },
  { key: "qty", label: "Qty", type: "number_range" },
  { key: "nilai", label: "Nilai", type: "number_range" },
];

const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_retur", label: "No. Retur", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "no_bukti", label: "No. Bukti" },
  { key: "divisi", label: "Divisi" },
  { key: "keterangan_divisi", label: "Keterangan Divisi" },
  { key: "kepala_nota", label: "Kepala Nota" },
  { key: "customer", label: "Customer" },
  { key: "barang", label: "Barang" },
  { key: "satuan", label: "Satuan" },
  { key: "jenis_bayar", label: "Jenis Bayar" },
  { key: "no_rekening", label: "No. Rekening" },
  { key: "bank", label: "Bank" },
  { key: "harga_jual", label: "Harga Jual", align: "right", format: "rupiah" },
  { key: "sales", label: "Sales" },
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
          <SelectSearch v-model="form.kd_customer" :options="customerOptions" label="Customer" />
          <Input v-model="form.search" label="Cari" placeholder="no retur / barang / customer" />
          <ColumnFilters :filter-defs="filterDefs" :form="form" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
