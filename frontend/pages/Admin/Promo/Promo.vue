<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/promo/diskon";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "kd_promo", label: "Kode Promo" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang" },
  { key: "harga_promo", label: "Harga Promo", align: "right", format: "rupiah" },
  { key: "tanggal_awal", label: "Tanggal Awal", format: "date" },
  { key: "tanggal_akhir", label: "Tanggal Akhir", format: "date" },
  { key: "status", label: "Status" },
];

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  return [
    { label: "Jumlah Baris", value: nf.format(s.jml_baris || 0) },
    { label: "Jumlah Barang", value: nf.format(s.jml_barang || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Promo & Diskon">
    <ReportPage
      title="Promo & Diskon"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_promo"
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
            <Input v-model="form.search" label="Cari" placeholder="kode promo / barang" />
          </FilterSection>
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
