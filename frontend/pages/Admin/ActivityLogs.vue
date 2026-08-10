<script setup>
import { computed, ref, watch } from "vue";
import { router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import { ACTION_LABELS } from "@/utils/labels";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import DataTable from "@/components/ui/DataTable.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import ExportButton from "@/components/ui/ExportButton.vue";

const props = defineProps({
  logs: { type: Array, default: () => [] },
  action_types: { type: Array, default: () => [] },
  users: { type: Array, default: () => [] },
  // Superadmin melihat jejak semua orang; peran lain hanya jejaknya sendiri
  // (disaring di server, lihat logs_index).
  boleh_semua: { type: Boolean, default: false },
  filters: { type: Object, default: () => ({}) },
});

// Penyaring user adalah round-trip, bukan saringan di layar: yang terkirim cuma
// 300 baris teratas, jadi menyaringnya di sini akan menjawab "tidak ada" untuk
// orang yang jejaknya nyata tapi lebih tua dari baris ke-300.
const userFilter = ref(props.filters.user || "");
watch(userFilter, (v) => {
  router.get("/admin-panel/logs", v ? { user: v } : {},
    { preserveState: true, preserveScroll: true, replace: true });
});

const actionFilter = ref("");
const dateFrom = ref("");
const dateTo = ref("");

const userOptions = computed(() => props.users.map((u) => ({ value: u, label: u })));
const actionOptions = computed(() => props.action_types.map((a) => ({ value: a, label: a })));

const exportColumns = [
  { key: "timestamp", label: "Waktu" },
  { key: "user", label: "User" },
  { key: "action", label: "Aksi" },
  { key: "detail", label: "Detail" },
  { key: "ip_address", label: "IP" },
];

const filtered = computed(() =>
  props.logs.filter((log) => {
    const day = log.timestamp.slice(0, 10);
    if (actionFilter.value && log.action !== actionFilter.value) return false;
    if (dateFrom.value && day < dateFrom.value) return false;
    if (dateTo.value && day > dateTo.value) return false;
    return true;
  }),
);

function resetFilters() {
  userFilter.value = "";
  actionFilter.value = "";
  dateFrom.value = "";
  dateTo.value = "";
}

// Kolom User dibuang untuk yang cuma melihat jejaknya sendiri: satu kolom berisi
// nama yang sama di setiap baris hanya memakan lebar tanpa memberi apa pun.
const columns = computed(() => [
  { key: "timestamp", label: "Waktu", sortable: true },
  ...(props.boleh_semua ? [{ key: "user", label: "User", sortable: true }] : []),
  { key: "action", label: "Aksi", sortable: true },
  { key: "detail", label: "Detail" },
  { key: "ip_address", label: "IP" },
]);

const actionVariant = (a) => {
  if (a === "login_gagal" || a === "login_terkunci") return "danger";
  if (a === "penjualan" || a === "penjualan_order") return "success";
  if (a === "konfigurasi" || a === "koreksi_stok") return "warning";
  return "neutral";
};
</script>

<template>
  <AdminLayout title="Log Aktivitas">
    <!-- Judul dimiliki AdminLayout; di sini cukup aksi kanan-atasnya. -->
    <div class="mb-4 flex items-center justify-end">
      <ExportButton mode="client" filename="aktivitas-log" :columns="exportColumns" :rows="filtered" sheet-name="Log" />
    </div>

    <FilterPanel @submit="() => {}" @reset="resetFilters">
      <FilterSection title="Periode & Pencarian">
        <DateRangeField class="sm:col-span-2" v-model:from="dateFrom" v-model:to="dateTo" />
        <Input v-model="actionFilter" label="Aksi" placeholder="cari aksi…" />
        <SelectSearch v-if="boleh_semua" v-model="userFilter" :options="userOptions" label="User" />
      </FilterSection>
    </FilterPanel>

    <p v-if="!boleh_semua" class="mb-3 text-xs text-ink-subtle">
      Halaman ini menampilkan jejak akun Anda sendiri.
    </p>

    <DataTable :columns="columns" :rows="filtered" :per-page="100" empty-message="Tidak ada log untuk filter ini.">
      <template #cell-action="{ value }">
        <Badge :variant="actionVariant(value)">{{ ACTION_LABELS[value] || value }}</Badge>
      </template>
    </DataTable>
  </AdminLayout>
</template>
