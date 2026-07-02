<script setup>
import { computed, reactive, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  histori: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const data = computed(() => props.histori || {});

const form = reactive({
  kd_barang: props.filters.kd_barang || "",
  kd_divisi: props.filters.kd_divisi || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
});
const loading = ref(false);

const divisiOptions = computed(() =>
  (data.value.divisi_list || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

function tampilkan() {
  const params = {};
  if (form.kd_barang.trim()) params.kd_barang = form.kd_barang.trim();
  if (form.kd_divisi) params.kd_divisi = form.kd_divisi;
  if (form.date_from) params.date_from = form.date_from;
  if (form.date_to) params.date_to = form.date_to;
  loading.value = true;
  router.get("/admin-panel/inventory/histori", params, {
    preserveState: true,
    preserveScroll: true,
    onFinish: () => (loading.value = false),
  });
}

const typeFilter = ref("");
const rowSearch = ref("");

const typeOptions = computed(() =>
  [...new Set(props.rows.map((r) => r.transaksi))].sort().map((t) => ({ value: t, label: t })),
);

const displayed = computed(() => {
  const term = rowSearch.value.toLowerCase().trim();
  return props.rows.filter((r) => {
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
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />

    <Card class="mb-6">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input v-model="form.kd_barang" label="Kode Barang" placeholder="mis. BRG0001 (opsional)" @keyup.enter="tampilkan" />
        <Select v-model="form.kd_divisi" label="Divisi" :options="divisiOptions" placeholder="Semua Divisi" />
        <Input v-model="form.date_from" label="Dari Tanggal" type="date" />
        <Input v-model="form.date_to" label="Sampai Tanggal" type="date" />
      </div>
      <div class="mt-3 flex justify-end">
        <Button :loading="loading" @click="tampilkan">Tampilkan</Button>
      </div>
    </Card>

    <div v-if="rows.length > 0">
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

      <DataTable :columns="columns" row-key="no_transaksi" :rows="displayed" :per-page="25" empty-message="Tidak ada data histori.">
        <template #cell-transaksi="{ value }"><Badge :variant="transVariant(value)">{{ value }}</Badge></template>
        <template #cell-debet="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-kredit="{ value }">{{ value ? num(value) : "—" }}</template>
        <template #cell-harga="{ value }">{{ value ? rupiah(value) : "—" }}</template>
      </DataTable>
    </div>

    <Card v-else-if="!conn_error">
      <p class="py-8 text-center text-sm text-ink-muted">
        Gunakan filter di atas untuk menampilkan histori barang.<br />
        Minimal isi salah satu filter: kode barang, divisi, atau rentang tanggal.
      </p>
    </Card>
  </AdminLayout>
</template>

