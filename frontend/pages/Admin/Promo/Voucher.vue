<script setup>
import { computed } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import Input from "@/components/ui/Input.vue";
import { useServerReport } from "@/composables/useServerReport.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/promo/voucher";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "kd_voucher", label: "Kode Voucher" },
  { key: "nama", label: "Nama" },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah" },
  { key: "dipakai", label: "Dipakai", align: "right", format: "number" },
  { key: "nilai_dipakai", label: "Nilai Dipakai", align: "right", format: "rupiah" },
  { key: "status", label: "Status" },
];

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  return [
    { label: "Jumlah Voucher", value: nf.format(s.jml_baris || 0) },
    { label: "Total Nominal", value: rp.format(s.total_nominal || 0) },
    { label: "Total Dipakai", value: nf.format(s.total_dipakai || 0) },
    { label: "Total Nilai Dipakai", value: rp.format(s.total_nilai_dipakai || 0) },
  ];
});
</script>

<template>
  <AdminLayout title="Voucher">
    <ReportPage
      title="Voucher"
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_voucher"
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
        <FilterPanel @submit="apply({ page: 1 })" @reset="reset">
          <Input v-model="form.search" label="Cari" placeholder="kode voucher / nama" />
        </FilterPanel>
      </template>
    </ReportPage>
  </AdminLayout>
</template>
