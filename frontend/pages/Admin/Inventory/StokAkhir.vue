<script setup>
import { computed } from "vue";
import ReportView from "@/components/report/ReportView.vue";
import Card from "@/components/ui/Card.vue";
import { stokAkhir } from "@/mock/inventory";

const columns = [
  { key: "divisi", label: "Divisi" },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "merk", label: "Merk" },
  { key: "model", label: "Model" },
  { key: "warna", label: "Warna" },
  { key: "stok_akhir", label: "Stok", align: "right", format: "number", sortable: true },
  { key: "harga_average", label: "Harga Avg", align: "right", format: "rupiah" },
  { key: "harga_jual", label: "Harga Jual", align: "right", format: "rupiah" },
  { key: "harga_beli_akhir", label: "Harga Beli Akhir", align: "right", format: "rupiah" },
  { key: "nominal", label: "Nilai Persediaan", align: "right", format: "rupiah", sortable: true },
];

const totalNilai = computed(() => stokAkhir.reduce((s, r) => s + (r.nominal || 0), 0));
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);
</script>

<template>
  <ReportView
    title="Stok Akhir per Tanggal"
    :columns="columns"
    :rows="stokAkhir"
    row-key="kd_barang"
    :per-page="25"
    :search-keys="['kd_barang', 'barang', 'kategori', 'merk']"
    search-placeholder="kode / barang / merk…"
    export-name="stok-akhir"
    sheet-name="Stok Akhir"
  >
    <template #summary>
      <Card>
        <div class="flex items-center justify-between">
          <p class="text-sm text-ink-muted">Total Nilai Persediaan</p>
          <p class="text-xl font-semibold text-brand-700">{{ rupiah(totalNilai) }}</p>
        </div>
      </Card>
    </template>
  </ReportView>
</template>

