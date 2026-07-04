<script setup>
import { computed, ref } from "vue";
import { useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import Modal from "@/components/ui/Modal.vue";
import Icon from "@/components/nav/Icon.vue";
import ExportButton from "@/components/ui/ExportButton.vue";

const props = defineProps({
  products: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  conn_error: { type: String, default: null },
});

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const search = ref("");
const categoryFilter = ref("");

const categoryOptions = computed(() =>
  props.categories.map((c) => ({ value: c.kd_kategori, label: c.nama })),
);

const filtered = computed(() => {
  const q = search.value.toLowerCase().trim();
  return props.products.filter((p) => {
    const matchQ = !q || p.nama.toLowerCase().includes(q) || p.kd_barang.toLowerCase().includes(q);
    const matchCat = !categoryFilter.value || p.kd_kategori === categoryFilter.value;
    return matchQ && matchCat;
  });
});

const columns = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Nama Produk", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "harga_jual", label: "Harga", sortable: true, align: "right" },
  { key: "stok", label: "Stok", sortable: true, align: "right" },
  { key: "status", label: "Status", align: "center" },
  { key: "actions", label: "", align: "right" },
];

const exportColumns = [
  { key: "kd_barang", label: "Kode" },
  { key: "nama", label: "Nama Produk" },
  { key: "kategori", label: "Kategori" },
  { key: "satuan", label: "Satuan" },
  { key: "harga_jual", label: "Harga" },
  { key: "stok", label: "Stok" },
  { key: "status", label: "Status" },
];

const showForm = ref(false);
const form = useForm({
  kd_barang: "",
  nama: "",
  kd_kategori: "",
  satuan: "PCS",
  harga_jual: 0,
  stok: 0,
  _editing: false,
});

function openCreate() {
  form.reset();
  form.clearErrors();
  showForm.value = true;
}
function openEdit(p) {
  form.kd_barang = p.kd_barang;
  form.nama = p.nama;
  form.kd_kategori = p.kd_kategori;
  form.satuan = p.satuan;
  form.harga_jual = p.harga_jual;
  form.stok = p.stok;
  form._editing = true;
  showForm.value = true;
}
function save() {
  form.post("/admin-panel/master/products/save", { onSuccess: () => (showForm.value = false) });
}
</script>

<template>
  <AdminLayout title="Master Produk">
    <Banner v-if="conn_error" variant="warning" :message="conn_error" />
    <Card>
      <template #header>
        <div class="flex items-center justify-between">
          <Button size="sm" @click="openCreate"><Icon name="plus" size="h-4 w-4" /> Tambah Produk</Button>
          <ExportButton mode="client" filename="produk" :columns="exportColumns" :rows="filtered" sheet-name="Produk" />
        </div>
      </template>

      <div class="mb-4 flex flex-col gap-3 sm:flex-row">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="search" placeholder="Cari kode / nama produk…" />
        </div>
        <div class="sm:w-56">
          <Select v-model="categoryFilter" :options="categoryOptions" placeholder="Semua kategori" />
        </div>
      </div>

      <DataTable :columns="columns" row-key="kd_barang" :rows="filtered" empty-message="Produk tidak ditemukan.">
        <template #cell-harga_jual="{ value }">{{ rupiah(value) }}</template>
        <template #cell-stok="{ value }">
          <span :class="value === 0 ? 'font-medium text-danger-600' : ''">{{ value }}</span>
        </template>
        <template #cell-status="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
        <template #cell-actions="{ row }">
          <Button variant="ghost" size="sm" @click="openEdit(row)"><Icon name="pencil" size="h-4 w-4" /></Button>
        </template>
      </DataTable>
    </Card>

    <Modal :show="showForm" :title="form._editing ? 'Edit Produk' : 'Tambah Produk'" @close="showForm = false">
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input v-model="form.kd_barang" label="Kode Barang" :error="form.errors.kd_barang" required />
        <Input v-model="form.nama" label="Nama Produk" :error="form.errors.nama" required />
        <Select v-model="form.kd_kategori" label="Kategori" :options="categoryOptions" placeholder="Pilih kategori" />
        <Input v-model="form.satuan" label="Satuan" />
        <Input v-model="form.harga_jual" label="Harga Jual" type="number" :error="form.errors.harga_jual" />
        <Input v-model="form.stok" label="Stok" type="number" />
      </div>
      <template #footer>
        <Button variant="secondary" @click="showForm = false">Batal</Button>
        <Button :loading="form.processing" @click="save">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
