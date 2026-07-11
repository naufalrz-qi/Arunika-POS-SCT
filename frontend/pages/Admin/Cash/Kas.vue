<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/kas/harian";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "tanggal", label: "Tanggal", sortable: true, format: "date" },
  { key: "kas", label: "Kas" },
  { key: "keterangan", label: "Keterangan" },
  { key: "masuk", label: "Masuk", align: "right", format: "rupiah" },
  { key: "keluar", label: "Keluar", align: "right", format: "rupiah" },
  { key: "saldo", label: "Saldo", align: "right", format: "rupiah" },
];

const kasOptions = computed(() => props.report?.options?.kas || []);
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Total Masuk", value: rp.format(s.total_masuk || 0) },
    { label: "Total Keluar", value: rp.format(s.total_keluar || 0) },
    { label: "Saldo Akhir", value: rp.format(s.saldo_akhir || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Kas Harian">
    <ReportPage
      title="Kas Harian"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="_rid"
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
            <SelectSearch v-model="form.kd_kas" :options="kasOptions" label="Kas" />
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
