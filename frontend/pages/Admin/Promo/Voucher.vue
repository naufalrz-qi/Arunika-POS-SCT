<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  data: { type: Object, default: null },
});
const rows = computed(() => props.data?.rows || []);
const columns = [
  { key: "kd_voucher", label: "Kode Voucher" },
  { key: "nama", label: "Nama" },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah" },
  { key: "dipakai", label: "Dipakai", align: "right", format: "number" },
  { key: "nilai_dipakai", label: "Nilai Dipakai", align: "right", format: "rupiah" },
  { key: "status", label: "Status" },
];
</script>

<template>
  <AdminLayout title="Voucher">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="Voucher"
        :columns="columns"
        :rows="rows"
        row-key="kd_voucher"
        :search-keys="['kd_voucher','nama']"
        export-name="voucher"
        sheet-name="Voucher"
        :conn-error="data && data.conn_error"
      />
    </Deferred>
  </AdminLayout>
</template>
