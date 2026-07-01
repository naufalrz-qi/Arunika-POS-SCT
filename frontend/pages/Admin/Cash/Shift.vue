<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { shift } from "@/mock/kas";

const columns = [
  { key: "shift", label: "Shift", sortable: true },
  { key: "kasir", label: "Kasir", sortable: true },
  { key: "mulai", label: "Mulai" },
  { key: "selesai", label: "Selesai" },
  { key: "divisi", label: "Divisi" },
  { key: "transaksi", label: "Transaksi", align: "right", format: "number", sortable: true },
  { key: "omzet", label: "Omzet", align: "right", format: "rupiah", sortable: true },
  { key: "status", label: "Status", align: "center" },
];
</script>

<template>
  <ReportView
    title="Shift Kasir"
    :columns="columns"
    :rows="shift"
    row-key="kasir"
    :search-keys="['shift', 'kasir', 'divisi', 'status']"
    search-placeholder="shift / kasir / divisi…"
    export-name="shift-kasir"
    sheet-name="Shift Kasir"
  >
    <template #cell-status="{ value }">
      <Badge :variant="value === 'Berjalan' ? 'brand' : 'success'">{{ value }}</Badge>
    </template>
  </ReportView>
</template>
