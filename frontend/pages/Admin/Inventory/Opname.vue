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

const URL = "/admin-panel/inventory/opname";
const { form, apply, onPage, onSort, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Opname", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang" },
  { key: "qty_sistem", label: "Qty Sistem", align: "right", format: "number" },
  { key: "qty_fisik", label: "Qty Fisik", align: "right", format: "number" },
  { key: "selisih", label: "Selisih", align: "right", format: "number", sortable: true },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  return [
    { label: "Jumlah Opname", value: nf.format(s.jml_opname || 0) },
    { label: "Total Selisih", value: nf.format(s.total_selisih || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Opname Stok">
    <ReportPage
      title="Opname Stok"
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
          <Input v-model="form.search" label="Cari" placeholder="no opname / barang / divisi" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
