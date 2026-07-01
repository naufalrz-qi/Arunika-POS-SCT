<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { pembelian } from "@/mock/pembelian";

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "no_order", label: "No. Order" },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "supplier", label: "Supplier", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "pembayaran", label: "Pembayaran" },
  { key: "jatuh_tempo", label: "Jatuh Tempo" },
  { key: "bank", label: "Bank" },
  { key: "no_rekening", label: "No. Rekening" },
  { key: "cabang", label: "Cabang" },
  { key: "total_pembelian", label: "Total Pembelian", align: "right", format: "rupiah", sortable: true },
];
</script>

<template>
  <ReportView
    title="Laporan Pembelian"
    :columns="columns"
    :rows="pembelian"
    row-key="no_transaksi"
    :search-keys="['no_transaksi', 'no_order', 'supplier', 'divisi', 'cabang']"
    search-placeholder="no transaksi / supplier / cabang…"
    export-name="pembelian"
    sheet-name="Pembelian"
  />
</template>
