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
  suppliers: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

const search = ref("");
const kotaFilter = ref("");
const statusFilter = ref("");

const kotaOptions = computed(() => {
  const cities = new Set(props.suppliers.map(s => s.kota).filter(Boolean));
  return Array.from(cities).map(city => ({ value: city, label: city }));
});

const filtered = computed(() => {
  const q = search.value.toLowerCase().trim();
  return props.suppliers.filter(s => {
    const matchQ = !q || s.nama.toLowerCase().includes(q) || s.kd_supplier.toLowerCase().includes(q) || (s.kota || "").toLowerCase().includes(q);
    const matchKota = !kotaFilter.value || s.kota === kotaFilter.value;
    const matchStatus = statusFilter.value === "" || (s.status === (statusFilter.value === "1" ? 1 : 0));
    return matchQ && matchKota && matchStatus;
  });
});

const columns = [
  { key: "kd_supplier", label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "kota", label: "Kota" },
  { key: "kontak", label: "Kontak" },
  { key: "hp", label: "HP" },
  { key: "status", label: "Status", align: "center" },
  { key: "actions", label: "", align: "right" },
];

const exportColumns = [
  { key: "kd_supplier", label: "Kode" },
  { key: "nama", label: "Nama" },
  { key: "kota", label: "Kota" },
  { key: "kontak", label: "Kontak" },
  { key: "hp", label: "HP" },
  { key: "status", label: "Status" },
];

const showForm = ref(false);
const form = useForm({
  kd_supplier: "",
  nama: "",
  kota: "",
  kontak: "",
  hp: "",
  status: 1,
  _editing: false,
});

function openCreate() {
  form.reset();
  form.clearErrors();
  showForm.value = true;
}
function openEdit(s) {
  form.kd_supplier = s.kd_supplier;
  form.nama = s.nama;
  form.kota = s.kota;
  form.kontak = s.kontak;
  form.hp = s.hp;
  form.status = s.status;
  form._editing = true;
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/master/suppliers/save", { onSuccess: () => (showForm.value = false) });
}
</script>

<template>
  <AdminLayout title="Master Supplier">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />
    <Card>
      <template #header>
        <div class="flex items-center justify-between">
          <Button size="sm" @click="openCreate"><Icon name="plus" size="h-4 w-4" /> Tambah Supplier</Button>
          <ExportButton mode="client" filename="supplier" :columns="exportColumns" :rows="filtered" sheet-name="Supplier" />
        </div>
      </template>

      <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="search" placeholder="Cari kode / nama / kota…" />
        </div>
        <div class="sm:w-48">
          <SelectSearch v-model="kotaFilter" :options="kotaOptions" placeholder="Semua kota" label="Kota" />
        </div>
        <div class="sm:w-48">
          <StatusSelect v-model="statusFilter" label="Status" />
        </div>
      </div>

      <DataTable :columns="columns" row-key="kd_supplier" :rows="filtered" empty-message="Supplier tidak ditemukan.">
        <template #cell-status="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
        <template #cell-actions="{ row }">
          <Button variant="ghost" size="sm" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
        </template>
      </DataTable>
    </Card>

    <Modal :show="showForm" :title="form._editing ? 'Edit Supplier' : 'Tambah Supplier'" @close="showForm = false">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input v-model="form.kd_supplier" label="Kode Supplier" :error="form.errors.kd_supplier" required />
        <Input v-model="form.nama" label="Nama" :error="form.errors.nama" required />
        <Input v-model="form.kota" label="Kota" />
        <Input v-model="form.kontak" label="Kontak" />
        <Input v-model="form.hp" label="No. HP" />
        <StatusSelect v-model="form.status" />
      </div>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
