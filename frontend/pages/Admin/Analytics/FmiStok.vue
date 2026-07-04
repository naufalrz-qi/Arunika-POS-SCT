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
  { key: "stok", label: "Stok", align: "right", format: "number" },
  { key: "terjual", label: "Terjual", align: "right", format: "number" },
  { key: "rasio", label: "Rasio", align: "right", format: "number" },
  { key: "status", label: "Status" },
];
</script>

<template>
  <AdminLayout title="FMI Stok">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="FMI Stok"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang','barang']"
        export-name="fmi-stok"
        sheet-name="FMI Stok"
        :conn-error="data && data.conn_error"
      >
        <template #cell-status="{ value }">
          <Badge v-if="value === 'Kritis'" variant="danger">Kritis</Badge>
          <Badge v-else-if="value === 'Overstock'" variant="warning">Overstock</Badge>
          <Badge v-else-if="value === 'Sehat'" variant="success">Sehat</Badge>
          <span v-else>{{ value }}</span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
