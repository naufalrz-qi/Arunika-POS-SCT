<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/biaya-operasional";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "no_transaksi", label: "No. Transaksi" },
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "divisi", label: "Divisi" },
  { key: "biaya", label: "Biaya", sortable: true },
  { key: "kategori", label: "Kategori" },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah", sortable: true },
  { key: "keterangan", label: "Keterangan" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const kategoriOptions = computed(() => props.report?.options?.kategori || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Total Nominal", value: rp.format(s.total_nominal || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Biaya Operasional">
    <ReportPage
      title="Biaya Operasional"
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
      @per-page-change="onPerPage"
    >
      <template #filters>
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <SelectSearch v-model="form.kategori" :options="kategoriOptions" label="Kategori" />
            <Input v-model="form.search" label="Cari" placeholder="nama biaya / keterangan" />
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
