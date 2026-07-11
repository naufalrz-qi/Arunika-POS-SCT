<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/fmi-stok";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "kd_barang", label: "Kode" },
  { key: "barang", label: "Barang" },
  { key: "kategori", label: "Kategori" },
  { key: "qty_stok", label: "Stok", align: "right", format: "number" },
  { key: "terjual", label: "Terjual", align: "right", format: "number" },
  { key: "rasio", label: "Rasio", align: "right", format: "number" },
  { key: "status", label: "Status" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Barang", value: nf.format(s.jml_barang || 0) },
    { label: "Total Stok", value: nf.format(s.total_qty || 0) },
    { label: "Total Nilai Stok", value: rp.format(s.total_nilai || 0) },
    { label: "Total Terjual", value: nf.format(s.total_terjual || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="FMI Stok">
    <ReportPage
      title="FMI Stok"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_barang"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      @page-change="onPage"
      @sort-change="onSort"
      @per-page-change="onPerPage"
    >
      <template #filters>
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="kode / nama barang" />
          </FilterSection>
        </FilterPanel>
      </template>
      <template #cell-status="{ value }">
        <Badge v-if="value === 'Kritis'" variant="danger">Kritis</Badge>
        <Badge v-else-if="value === 'Overstock'" variant="warning">Overstock</Badge>
        <Badge v-else-if="value === 'Sehat'" variant="success">Sehat</Badge>
        <span v-else>{{ value }}</span>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
