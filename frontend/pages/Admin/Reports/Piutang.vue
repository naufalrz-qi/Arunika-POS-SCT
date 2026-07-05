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

const URL = "/admin-panel/laporan/piutang";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Nota", sortable: true },
  { key: "tanggal", label: "Tanggal", format: "date" },
  { key: "customer", label: "Customer", sortable: true },
  { key: "jatuh_tempo", label: "Jatuh Tempo", sortable: true, format: "date" },
  { key: "total_penjualan", label: "Total Penjualan", align: "right", format: "rupiah" },
  { key: "total_cicilan", label: "Total Cicilan", align: "right", format: "rupiah" },
  { key: "sisa_piutang", label: "Sisa Piutang", align: "right", format: "rupiah", sortable: true },
  { key: "hari_terlambat", label: "Hari Terlambat", align: "right", format: "number" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const customerOptions = computed(() => props.report?.options?.customer || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Nota", value: nf.format(s.jml_nota || 0) },
    { label: "Total Penjualan", value: rp.format(s.total_penjualan || 0) },
    { label: "Total Cicilan", value: rp.format(s.total_cicilan || 0) },
    { label: "Sisa Piutang", value: rp.format(s.total_sisa_piutang || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Piutang Pelanggan">
    <ReportPage
      title="Piutang Pelanggan"
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
          <Input v-model="form.search" label="Cari" placeholder="no nota" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
