<script setup>
import { computed, reactive } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  products: { type: Object, default: null },
});

const data = computed(() => props.products || {});
const rows = computed(() => data.value.rows || []);
const categories = computed(() => data.value.categories || []);

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function distinctOptions(list, key) {
  const values = new Set(list.map((r) => r[key]).filter((v) => v !== "" && v != null));
  return Array.from(values).map((v) => ({ value: v, label: v }));
}

const categoryOptions = computed(() =>
  categories.value.map((c) => ({ value: c.kd_kategori, label: c.nama })),
);
const satuanOptions = computed(() => distinctOptions(rows.value, "satuan"));
const statusPinjamOptions = computed(() => distinctOptions(rows.value, "status_pinjam"));

const filters = reactive({
  search: "",
  kategori: "",
  status: "",
  status_pinjam: "",
  satuan: "",
});

function resetFilters() {
  filters.search = "";
  filters.kategori = "";
  filters.status = "";
  filters.status_pinjam = "";
  filters.satuan = "";
}

const filtered = computed(() => {
  const q = filters.search.toLowerCase().trim();
  return rows.value.filter((p) => {
    const matchQ =
      !q ||
      p.nama.toLowerCase().includes(q) ||
      p.kd_barang.toLowerCase().includes(q) ||
      (p.pabrik || "").toLowerCase().includes(q);
    const matchKategori = !filters.kategori || p.kd_kategori === filters.kategori;
    const matchStatus = filters.status === "" || (filters.status === "1" ? p.status : !p.status);
    const matchStatusPinjam = !filters.status_pinjam || p.status_pinjam === filters.status_pinjam;
    const matchSatuan = !filters.satuan || p.satuan === filters.satuan;
    return matchQ && matchKategori && matchStatus && matchStatusPinjam && matchSatuan;
  });
});

const columns = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Nama Produk", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "kd_jenis_bahan", label: "Jenis Bahan" },
  { key: "kd_model", label: "Model" },
  { key: "kd_merk", label: "Merk" },
  { key: "kd_warna", label: "Warna" },
  { key: "ukuran", label: "Ukuran" },
  { key: "pabrik", label: "Pabrik" },
  { key: "satuan", label: "Satuan", align: "center" },
  { key: "harga_jual", label: "Harga", sortable: true, align: "right" },
  { key: "stok", label: "Stok", sortable: true, align: "right" },
  { key: "status", label: "Status", align: "center" },
  { key: "status_pinjam", label: "Status Pinjam", align: "center" },
  { key: "keterangan", label: "Keterangan" },
];

const exportColumns = columns.map(({ key, label }) => ({ key, label }));
</script>

<template>
  <AdminLayout title="Master Produk">
    <Card class="mb-4">
      <FilterPanel :form="filters" @submit="() => {}" @reset="resetFilters">
        <FilterSection>
          <Input v-model="filters.search" label="Cari" placeholder="Kode / nama / pabrik…" />
          <Select v-model="filters.kategori" label="Kategori" :options="categoryOptions" placeholder="Semua kategori" />
        </FilterSection>
        <template #lanjutan>
          <FilterSection title="Filter Lanjutan">
            <Select
              v-model="filters.status"
              label="Status"
              :options="[{ value: '1', label: 'Aktif' }, { value: '0', label: 'Nonaktif' }]"
              placeholder="Semua status"
            />
            <Select
              v-model="filters.status_pinjam"
              label="Status Pinjam"
              :options="statusPinjamOptions"
              placeholder="Semua"
            />
            <Select v-model="filters.satuan" label="Satuan" :options="satuanOptions" placeholder="Semua satuan" />
          </FilterSection>
        </template>
      </FilterPanel>
    </Card>

    <Deferred data="products">
      <template #fallback>
        <LoadingCard message="Mengambil data produk…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

      <div class="mb-3 flex items-center justify-between">
        <span class="text-sm text-ink-muted">{{ filtered.length.toLocaleString("id-ID") }} produk</span>
        <ExportButton mode="client" filename="produk" :columns="exportColumns" :rows="filtered" sheet-name="Produk" />
      </div>

      <DataTable :columns="columns" row-key="kd_barang" :rows="filtered" empty-message="Produk tidak ditemukan.">
        <template #cell-harga_jual="{ value }">{{ rupiah(value) }}</template>
        <template #cell-stok="{ value }">
          <span :class="value === 0 ? 'font-medium text-danger-600' : ''">{{ value }}</span>
        </template>
        <template #cell-status="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
      </DataTable>
    </Deferred>
  </AdminLayout>
</template>
