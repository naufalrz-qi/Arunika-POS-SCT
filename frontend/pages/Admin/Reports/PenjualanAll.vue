<script setup>
import ReportView from "@/components/report/ReportView.vue";
import { penjualanAll } from "@/mock/penjualan";

const columns = [
  { key: "no_transaksi", label: "No. Transaksi", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "divisi", label: "Divisi" },
  { key: "customer", label: "Customer", sortable: true },
  { key: "kota", label: "Kota" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "qty", label: "Qty", align: "right", format: "number", sortable: true },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "harga", label: "Harga", align: "right", format: "rupiah" },
  { key: "diskon", label: "Diskon", align: "right", format: "rupiah" },
  { key: "harga_bersih", label: "Harga Bersih", align: "right", format: "rupiah" },
  { key: "total", label: "Total", align: "right", format: "rupiah", sortable: true },
];
</script>

<template>
  <ReportView
    title="Laporan Penjualan (Detail)"
    :columns="columns"
    :rows="penjualanAll"
    row-key="id"
    :per-page="25"
    :search-keys="['no_transaksi', 'customer', 'barang', 'divisi', 'kota']"
    search-placeholder="no transaksi / customer / barang…"
    export-name="penjualan-detail"
    sheet-name="Penjualan Detail"
  />
</template>
