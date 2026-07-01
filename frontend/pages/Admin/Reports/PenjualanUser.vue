<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { penjualanUser } from "@/mock/penjualan";

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "status", label: "Status", align: "center" },
  { key: "customer", label: "Customer" },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah", sortable: true },
  { key: "user", label: "User", sortable: true },
];
</script>

<template>
  <ReportView
    title="Penjualan per User"
    :columns="columns"
    :rows="penjualanUser"
    row-key="no_transaksi"
    :search-keys="['no_transaksi', 'customer', 'user', 'divisi']"
    search-placeholder="no transaksi / user / customer…"
    export-name="penjualan-per-user"
    sheet-name="Penjualan per User"
  >
    <template #cell-status="{ value }">
      <Badge :variant="value === 'Lunas' ? 'success' : 'warning'">{{ value }}</Badge>
    </template>
  </ReportView>
</template>
