<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import DataTable from "@/components/ui/DataTable.vue";
import BarChart from "@/components/charts/BarChart.vue";
import { downloadXlsx, stamp } from "@/utils/xlsx";
import { penjualanBulanan, penjualanHarian } from "@/mock/penjualan";

const mode = ref("bulanan"); // bulanan | harian
const modeOptions = [
  { value: "bulanan", label: "Per Bulan" },
  { value: "harian", label: "Per Hari" },
];

const rows = computed(() => (mode.value === "bulanan" ? penjualanBulanan : penjualanHarian));

const chartData = computed(() => rows.value.map((r) => ({ label: r.label, value: r.total_bersih })));

const total = computed(() => rows.value.reduce((s, r) => s + r.total_bersih, 0));

const columns = [
  { key: "periode", label: "Periode", sortable: true },
  { key: "total_bersih", label: "Total Bersih", align: "right", format: "rupiah", sortable: true },
];

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function exportXlsx() {
  downloadXlsx(`penjualan-${mode.value}-${stamp()}.xlsx`, columns, rows.value, "Penjualan Periode");
}
</script>

<template>
  <AdminLayout title="Penjualan per Periode">
    <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
      <div class="sm:w-48">
        <Select v-model="mode" label="Tampilan" :options="modeOptions" />
      </div>
      <div class="sm:ml-auto sm:pb-0.5">
        <Button variant="secondary" @click="exportXlsx">Export Excel</Button>
      </div>
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div class="lg:col-span-2">
        <Card :title="mode === 'bulanan' ? 'Tren Penjualan Bulanan' : 'Tren Penjualan Harian'" subtitle="Total bersih">
          <BarChart :data="chartData" />
        </Card>
      </div>
      <Card title="Ringkasan">
        <p class="text-sm text-ink-muted">Total Penjualan ({{ mode === "bulanan" ? "6 bulan" : "7 hari" }})</p>
        <p class="mt-1 text-2xl font-semibold text-brand-700">{{ rupiah(total) }}</p>
        <p class="mt-4 text-sm text-ink-muted">Rata-rata per {{ mode === "bulanan" ? "bulan" : "hari" }}</p>
        <p class="mt-1 text-lg font-semibold text-ink">{{ rupiah(total / rows.length) }}</p>
      </Card>
    </div>

    <div class="mt-4">
      <DataTable :columns="columns" row-key="periode" :rows="rows" :per-page="31" />
    </div>
  </AdminLayout>
</template>

