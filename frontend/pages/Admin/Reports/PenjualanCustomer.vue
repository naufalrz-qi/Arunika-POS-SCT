<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { penjualanCustomer } from "@/mock/penjualan";

const columns = [
  { key: "divisi", label: "Divisi" },
  { key: "customer", label: "Customer", sortable: true },
  { key: "kota", label: "Kota", sortable: true },
  { key: "jumlah_nota", label: "Jumlah Nota", align: "right", format: "number", sortable: true },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
];
</script>

<template>
  <ReportView
    title="Penjualan per Customer"
    :columns="columns"
    :rows="penjualanCustomer"
    row-key="customer"
    :search-keys="['customer', 'kota', 'divisi']"
    search-placeholder="customer / kota…"
    export-name="penjualan-per-customer"
    sheet-name="Penjualan per Customer"
  />
</template>
