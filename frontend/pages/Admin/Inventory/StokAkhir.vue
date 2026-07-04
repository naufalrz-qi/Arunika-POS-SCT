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
  { key: "kd_barang", label: "Kode" },
  { key: "barang", label: "Barang" },
  { key: "kategori", label: "Kategori" },
  { key: "stok_akhir", label: "Stok Akhir", align: "right", format: "number" },
];
</script>

<template>
  <AdminLayout title="Stok Akhir per Tanggal">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="Stok Akhir per Tanggal"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang','barang']"
        export-name="stok-akhir"
        sheet-name="Stok Akhir"
        :conn-error="data && data.conn_error"
      />
    </Deferred>
  </AdminLayout>
</template>
