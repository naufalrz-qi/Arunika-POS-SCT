<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import DataTable from "@/components/ui/DataTable.vue";

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
    <Card title="Filter">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Select v-model="userFilter" label="User" :options="userOptions" placeholder="Semua user" />
        <Select v-model="actionFilter" label="Tipe Aksi" :options="actionOptions" placeholder="Semua aksi" />
        <Input v-model="dateFrom" label="Dari Tanggal" type="date" />
        <Input v-model="dateTo" label="Sampai Tanggal" type="date" />
        <div class="flex items-end">
          <Button variant="secondary" class="w-full" @click="resetFilters">Reset</Button>
        </div>
      </div>
    </Card>

    <div class="mt-6">
      <DataTable :columns="columns" :rows="filtered" :per-page="15" empty-message="Tidak ada log untuk filter ini.">
        <template #cell-action="{ value }">
          <Badge :variant="actionVariant(value)">{{ value }}</Badge>
        </template>
      </DataTable>
    </div>
  </AdminLayout>
</template>
