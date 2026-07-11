<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
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
});

const userFilter = ref("");
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
    if (userFilter.value && log.user !== userFilter.value) return false;
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

const columns = [
  { key: "timestamp", label: "Waktu", sortable: true },
  { key: "user", label: "User", sortable: true },
  { key: "action", label: "Aksi", sortable: true },
  { key: "detail", label: "Detail" },
  { key: "ip_address", label: "IP" },
];

const actionVariant = (a) => {
  if (a === "login_gagal" || a === "batal") return "danger";
  if (a === "transaksi" || a === "tutup_buku") return "success";
  if (a === "konfigurasi") return "warning";
  return "neutral";
};
</script>

<template>
  <AdminLayout title="Log Aktivitas">
    <div class="mb-4 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-ink">Log Aktivitas</h1>
      <ExportButton mode="client" filename="aktivitas-log" :columns="exportColumns" :rows="filtered" sheet-name="Log" />
    </div>

    <FilterPanel @submit="() => {}" @reset="resetFilters">
      <FilterSection title="Periode & Pencarian">
        <DateRangeField class="sm:col-span-2" v-model:from="dateFrom" v-model:to="dateTo" />
        <Input v-model="actionFilter" label="Aksi" placeholder="cari aksi…" />
        <SelectSearch v-model="userFilter" :options="userOptions" label="User" />
      </FilterSection>
    </FilterPanel>

    <DataTable :columns="columns" :rows="filtered" :per-page="15" empty-message="Tidak ada log untuk filter ini.">
      <template #cell-action="{ value }">
        <Badge :variant="actionVariant(value)">{{ value }}</Badge>
      </template>
    </DataTable>
  </AdminLayout>
</template>
