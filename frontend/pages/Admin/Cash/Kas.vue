<script setup>
import ReportView from "@/components/report/ReportView.vue";
import Badge from "@/components/ui/Badge.vue";
import { kasHarian } from "@/mock/kas";

const columns = [
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "kasir", label: "Kasir", sortable: true },
  { key: "saldo_awal", label: "Saldo Awal", align: "right", format: "rupiah" },
  { key: "kas_masuk", label: "Kas Masuk", align: "right", format: "rupiah" },
  { key: "kas_keluar", label: "Kas Keluar", align: "right", format: "rupiah" },
  { key: "penjualan_tunai", label: "Penjualan Tunai", align: "right", format: "rupiah" },
  { key: "saldo_akhir", label: "Saldo Akhir", align: "right", format: "rupiah", sortable: true },
  { key: "selisih", label: "Selisih", align: "right" },
  { key: "status", label: "Status", align: "center" },
];

const statusVariant = (s) => (s === "Seimbang" ? "success" : "warning");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);
</script>

<template>
  <ReportView
    title="Kas Harian"
    :columns="columns"
    :rows="kasHarian"
    row-key="tanggal"
    :search-keys="['tanggal', 'kasir', 'status']"
    search-placeholder="tanggal / kasir…"
    export-name="kas-harian"
    sheet-name="Kas Harian"
  >
    <template #cell-selisih="{ value }">
      <span :class="value === 0 ? 'text-ink-muted' : value < 0 ? 'font-semibold text-danger-600' : 'font-semibold text-success-700'">
        {{ rupiah(value) }}
      </span>
    </template>
    <template #cell-status="{ value }">
      <Badge :variant="statusVariant(value)">{{ value }}</Badge>
    </template>
  </ReportView>
</template>

