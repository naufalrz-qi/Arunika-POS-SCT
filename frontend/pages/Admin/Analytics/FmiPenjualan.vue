<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({
  data: { type: Object, default: null },
});
const rows = computed(() => props.data?.rows || []);
const columns = [
  { key: "kd_barang", label: "Kode" },
  { key: "barang", label: "Barang" },
  { key: "kategori", label: "Kategori" },
  { key: "qty_terjual", label: "Qty Terjual", align: "right", format: "number" },
  { key: "nilai", label: "Nilai", align: "right", format: "rupiah" },
  { key: "kelas", label: "Kelas" },
];
</script>

<template>
  <AdminLayout title="FMI Penjualan">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="FMI Penjualan"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang','barang']"
        export-name="fmi-penjualan"
        sheet-name="FMI Penjualan"
        :conn-error="data && data.conn_error"
      >
        <template #cell-kelas="{ value }">
          <Badge v-if="value === 'Fast'" variant="success">Fast</Badge>
          <Badge v-else-if="value === 'Medium'" variant="warning">Medium</Badge>
          <Badge v-else-if="value === 'Slow'" variant="danger">Slow</Badge>
          <span v-else>{{ value }}</span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
