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

const URL = "/admin-panel/laporan/penjualan-nota";

const filterDefs = [
  { key: "no_transaksi", label: "No. Nota", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "total_bersih", label: "Total Bersih", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

const columns = [
  { key: "no_transaksi", label: "No. Nota", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "customer", label: "Customer" },
  { key: "kota", label: "Kota" },
  { key: "total_kotor", label: "Total Kotor", align: "right", format: "rupiah" },
  { key: "potongan", label: "Potongan", align: "right", format: "rupiah" },
  { key: "voucher", label: "Voucher", align: "right", format: "rupiah" },
  { key: "total_setelah_voucher", label: "Total Setelah Voucher", align: "right", format: "rupiah" },
  { key: "pajak", label: "Pajak", align: "right", format: "rupiah" },
  { key: "pajak2", label: "Pajak 2", align: "right", format: "rupiah" },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
  { key: "petugas", label: "Petugas" },
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
          <SelectSearch v-model="form.kd_customer" :options="customerOptions" label="Customer" />
          <Input v-model="form.search" label="Cari" placeholder="no nota / customer" />
          <ColumnFilters :filter-defs="filterDefs" :form="form" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
