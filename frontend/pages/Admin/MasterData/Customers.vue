<script setup>
import { computed, ref } from "vue";
import { useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import Modal from "@/components/ui/Modal.vue";
import Icon from "@/components/nav/Icon.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import StatusSelect from "@/components/ui/StatusSelect.vue";

const props = defineProps({
  customers: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const search = ref("");
const kotaFilter = ref("");
const statusFilter = ref("");

const kotaOptions = computed(() => {
  const cities = new Set(props.customers.map(c => c.kota).filter(Boolean));
  return Array.from(cities).map(city => ({ value: city, label: city }));
});

const filtered = computed(() => {
  const q = search.value.toLowerCase().trim();
  return props.customers.filter(c => {
    const matchQ = !q || c.nama.toLowerCase().includes(q) || c.kd_customer.toLowerCase().includes(q) || (c.hp || "").includes(q);
    const matchKota = !kotaFilter.value || c.kota === kotaFilter.value;
    const matchStatus = statusFilter.value === "" || (c.status === (statusFilter.value === "1" ? 1 : 0));
    return matchQ && matchKota && matchStatus;
  });
});

const columns = [
  { key: "kd_customer", label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "hp", label: "HP" },
  { key: "alamat", label: "Alamat" },
  { key: "point", label: "Poin", sortable: true, align: "right" },
  { key: "limit_kredit", label: "Limit Kredit", sortable: true, align: "right" },
  { key: "status", label: "Status", align: "center" },
  { key: "actions", label: "", align: "right" },
];

const exportColumns = [
  { key: "kd_customer", label: "Kode" },
  { key: "nama", label: "Nama" },
  { key: "kota", label: "Kota" },
  { key: "hp", label: "HP" },
  { key: "alamat", label: "Alamat" },
  { key: "point", label: "Poin" },
  { key: "limit_kredit", label: "Limit Kredit" },
  { key: "status", label: "Status" },
];

const showForm = ref(false);
const form = useForm({
  kd_customer: "",
  nama: "",
  hp: "",
  email: "",
  alamat: "",
  limit_kredit: 0,
  _editing: false,
});

function openCreate() {
  form.reset();
  form.clearErrors();
  showForm.value = true;
}
function openEdit(c) {
  form.kd_customer = c.kd_customer;
  form.nama = c.nama;
  form.hp = c.hp;
  form.email = c.email;
  form.alamat = c.alamat;
  form.limit_kredit = c.limit_kredit;
  form._editing = true;
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/master/customers/save", { onSuccess: () => (showForm.value = false) });
}
</script>

<template>
  <AdminLayout title="Master Pelanggan">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />
    <Card>
      <template #header>
        <div class="flex items-center justify-between">
          <Button size="sm" @click="openCreate"><Icon name="plus" size="h-4 w-4" /> Tambah Pelanggan</Button>
          <ExportButton mode="client" filename="pelanggan" :columns="exportColumns" :rows="filtered" sheet-name="Pelanggan" />
        </div>
      </template>

      <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="search" placeholder="Cari kode / nama / HP…" />
        </div>
        <div class="sm:w-48">
          <SelectSearch v-model="kotaFilter" :options="kotaOptions" placeholder="Semua kota" label="Kota" />
        </div>
        <div class="sm:w-48">
          <StatusSelect v-model="statusFilter" label="Status" />
        </div>
      </div>

      <DataTable :columns="columns" row-key="kd_customer" :rows="filtered" empty-message="Pelanggan tidak ditemukan.">
        <template #cell-point="{ value }">{{ value.toLocaleString("id-ID") }}</template>
        <template #cell-limit_kredit="{ value }">{{ rupiah(value) }}</template>
        <template #cell-status="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
        <template #cell-actions="{ row }">
          <Button variant="ghost" size="sm" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
        </template>
      </DataTable>
    </Card>

    <Modal :show="showForm" :title="form._editing ? 'Edit Pelanggan' : 'Tambah Pelanggan'" @close="showForm = false">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input v-model="form.kd_customer" label="Kode Pelanggan" :error="form.errors.kd_customer" required />
        <Input v-model="form.nama" label="Nama" :error="form.errors.nama" required />
        <Input v-model="form.hp" label="No. HP" />
        <Input v-model="form.email" label="Email" type="email" />
        <Input v-model="form.alamat" label="Alamat" />
        <Input v-model="form.limit_kredit" label="Limit Kredit" type="number" />
      </div>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
