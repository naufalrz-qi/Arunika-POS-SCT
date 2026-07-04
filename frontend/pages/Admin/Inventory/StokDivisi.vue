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
  { key: "nama", label: "Barang" },
  { key: "divisi", label: "Divisi" },
  { key: "stok_akhir", label: "Stok", align: "right", format: "number" },
];
</script>

<template>
  <AdminLayout title="Stok per Divisi">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="Stok per Divisi"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang','nama']"
        export-name="stok-divisi"
        sheet-name="Stok Divisi"
        :conn-error="data && data.conn_error"
      >
        <template #cell-stok_akhir="{ row }">
          <Badge v-if="row.stok_min !== undefined && row.stok_akhir < row.stok_min" variant="danger">{{ row.stok_akhir }}</Badge>
          <span v-else>{{ new Intl.NumberFormat('id-ID').format(row.stok_akhir || 0) }}</span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
