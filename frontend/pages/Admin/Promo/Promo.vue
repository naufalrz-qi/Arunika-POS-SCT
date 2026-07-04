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
  { key: "kd_promo", label: "Kode Promo" },
  { key: "divisi", label: "Divisi" },
  { key: "barang", label: "Barang" },
  { key: "harga_promo", label: "Harga Promo", align: "right", format: "rupiah" },
  { key: "tanggal_awal", label: "Tanggal Awal", format: "date" },
  { key: "tanggal_akhir", label: "Tanggal Akhir", format: "date" },
  { key: "status", label: "Status" },
];
</script>

<template>
  <AdminLayout title="Promo & Diskon">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="Promo & Diskon"
        :columns="columns"
        :rows="rows"
        row-key="kd_promo"
        :search-keys="['kd_promo','barang']"
        export-name="promo-diskon"
        sheet-name="Promo"
        :conn-error="data && data.conn_error"
      />
    </Deferred>
  </AdminLayout>
</template>
