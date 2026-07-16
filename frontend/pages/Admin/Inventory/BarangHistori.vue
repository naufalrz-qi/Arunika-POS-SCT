<script setup>
import { computed, ref } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import DateRangeFilter from "@/components/report/DateRangeFilter.vue";
import { useReportFilters } from "@/composables/useReportFilters";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  histori: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const data = computed(() => props.histori || {});

const { filters: form, loading, apply: tampilkan } = useReportFilters("/admin-panel/inventory/histori", {
  kd_barang: props.filters.kd_barang || "",
  kd_divisi: props.filters.kd_divisi || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
});

const divisiOptions = computed(() =>
  (data.value.divisi_list || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

const typeFilter = ref("");
const rowSearch = ref("");

const typeOptions = computed(() =>
  [...new Set((data.value.rows || []).map((r) => r.transaksi))].sort().map((t) => ({ value: t, label: t })),
);

const displayed = computed(() => {
  const term = rowSearch.value.toLowerCase().trim();
  return (data.value.rows || []).filter((r) => {
    const okType = !typeFilter.value || r.transaksi === typeFilter.value;
    const okSearch =
      !term ||
      (r.no_transaksi || "").toLowerCase().includes(term) ||
      (r.barang || "").toLowerCase().includes(term) ||
      (r.kd_barang || "").toLowerCase().includes(term);
    return okType && okSearch;
  });
});

const summary = computed(() => {
  const totalDebet = displayed.value.reduce((s, r) => s + (r.debet || 0), 0);
  const totalKredit = displayed.value.reduce((s, r) => s + (r.kredit || 0), 0);
  // saldo in smallest unit (qty_base already converts each row via satuan factor)
  const saldo = displayed.value.reduce((s, r) => s + (r.qty_base || 0), 0);
  return { totalDebet, totalKredit, saldo: Math.round(saldo * 1000) / 1000, count: displayed.value.length };
});

const num = (n) => (n ?? 0).toLocaleString("id-ID");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function exportXlsx() {
  downloadXlsx(`barang-histori-${stamp()}.xlsx`, columns, displayed.value, "Barang Histori");
}

const transVariant = (t) => {
  if (t.includes("Keluar") || t === "Penjualan" || t === "Retur Pembelian") return "danger";
  if (t === "Stok Awal") return "neutral";
  return "success";
};

const columns = [
  { key: "kd_divisi", label: "Kode Div." },
  { key: "divisi", label: "Divisi", sortable: true },
  { key: "kepala_nota", label: "Kepala Nota" },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "transaksi", label: "Transaksi" },
  { key: "no_transaksi", label: "No. Transaksi" },
  { key: "kd_barang", label: "Kode Barang", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "debet", label: "Debet", align: "right" },
  { key: "kredit", label: "Kredit", align: "right" },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "harga", label: "Harga", align: "right" },
];
</script>

<template>
  <AdminLayout title="Barang Histori">
    <Card class="mb-6">
      <DateRangeFilter
        mode="range"
        :filters="form"
        :divisi-options="divisiOptions"
        :loading="loading"
        :inline-submit="false"
        submit-label="Tampilkan"
        @submit="tampilkan()"
      >
        <template #before>
          <Input v-model="form.kd_barang" label="Kode Barang" placeholder="mis. BRG0001 (opsional)" @keyup.enter="tampilkan()" />
        </template>
      </DateRangeFilter>
    </Card>

    <Deferred data="histori">
      <template #fallback>
        <LoadingCard message="Mengambil data histori…" />
      </template>

    <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

    <div v-if="(data.rows || []).length > 0">
      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card>
          <p class="text-xs text-ink-muted">Total Baris</p>
          <p class="text-lg font-semibold">{{ num(summary.count) }}</p>
        </Card>
        <Card>
          <p class="text-xs text-ink-muted">Total Debet (masuk)</p>
          <p class="text-lg font-semibold text-success-700">{{ num(summary.totalDebet) }}</p>
        </Card>
        <Card>
          <p class="text-xs text-ink-muted">Total Kredit (keluar)</p>
          <p class="text-lg font-semibold text-danger-600">{{ num(summary.totalKredit) }}</p>
        </Card>
        <Card>
          <p class="text-xs text-ink-muted">Saldo (satuan terkecil)</p>
          <p class="text-lg font-semibold text-brand-700">{{ num(summary.saldo) }}</p>
        </Card>
      </div>

      <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:w-56">
          <Select v-model="typeFilter" label="Jenis Transaksi" :options="typeOptions" placeholder="Semua jenis" />
        </div>
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="rowSearch" label="Cari" placeholder="no. transaksi / kode / nama barang…" />
        </div>
        <p class="text-xs text-ink-subtle sm:pb-2">{{ displayed.length.toLocaleString("id-ID") }} baris</p>
        <div class="sm:ml-auto sm:pb-0.5">
          <Button variant="secondary" :disabled="displayed.length === 0" @click="exportXlsx">Export Excel</Button>
        </div>
      </div>

      <DataTable :columns="columns" row-key="no_transaksi" :rows="displayed" :per-page="100" empty-message="Tidak ada data histori.">
        <template #cell-transaksi="{ value }"><Badge :variant="transVariant(value)">{{ value }}</Badge></template>
        <template #cell-debet="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-kredit="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-harga="{ value }">{{ value ? rupiah(value) : "—" }}</template>
      </DataTable>
    </div>

    <Card v-else-if="!data.conn_error">
      <p class="py-8 text-center text-sm text-ink-muted">
        Gunakan filter di atas untuk menampilkan histori barang.<br />
        Minimal isi salah satu filter: kode barang, divisi, atau rentang tanggal.
      </p>
    </Card>
    </Deferred>
  </AdminLayout>
</template>

