<script setup>
import { computed, reactive } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  suppliers: { type: Object, default: null },
});

const data = computed(() => props.suppliers || {});
const rows = computed(() => data.value.rows || []);

function distinctOptions(list, key) {
  const values = new Set(list.map((r) => r[key]).filter((v) => v !== "" && v != null));
  return Array.from(values).map((v) => ({ value: v, label: v }));
}

const kotaOptions = computed(() => distinctOptions(rows.value, "kd_kota"));
const jenisOptions = computed(() => distinctOptions(rows.value, "jenis"));

const filters = reactive({
  search: "",
  kota: "",
  jenis: "",
  rekening: "",
});

function resetFilters() {
  filters.search = "";
  filters.kota = "";
  filters.jenis = "";
  filters.rekening = "";
}

const filtered = computed(() => {
  const q = filters.search.toLowerCase().trim();
  return rows.value.filter((s) => {
    const matchQ =
      !q ||
      s.nama.toLowerCase().includes(q) ||
      s.kd_supplier.toLowerCase().includes(q) ||
      (s.kontak || "").toLowerCase().includes(q) ||
      (s.hp || "").toLowerCase().includes(q);
    const matchKota = !filters.kota || s.kd_kota === filters.kota;
    const matchJenis = !filters.jenis || s.jenis === filters.jenis;
    const matchRekening = !filters.rekening || (filters.rekening === "1" ? !!s.rekening : !s.rekening);
    return matchQ && matchKota && matchJenis && matchRekening;
  });
});

const columns = [
  { key: "kd_supplier", label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "kd_kota", label: "Kota" },
  { key: "alamat", label: "Alamat" },
  { key: "telepon", label: "Telepon" },
  { key: "fax", label: "Fax" },
  { key: "kontak", label: "Kontak" },
  { key: "hp", label: "HP" },
  { key: "email", label: "Email" },
  { key: "kd_bank", label: "Bank" },
  { key: "rekening", label: "No. Rekening" },
  { key: "jenis", label: "Jenis" },
  { key: "keterangan", label: "Keterangan" },
];

const exportColumns = columns.map(({ key, label }) => ({ key, label }));
</script>

<template>
  <AdminLayout title="Master Supplier">
    <Card class="mb-4">
      <FilterPanel :form="filters" @submit="() => {}" @reset="resetFilters">
        <FilterSection>
          <Input v-model="filters.search" label="Cari" placeholder="Kode / nama / kontak / HP…" />
          <SelectSearch v-model="filters.kota" :options="kotaOptions" label="Kota" placeholder="Semua kota" />
        </FilterSection>
        <template #lanjutan>
          <FilterSection title="Filter Lanjutan">
            <Select v-model="filters.jenis" label="Jenis" :options="jenisOptions" placeholder="Semua jenis" />
            <Select
              v-model="filters.rekening"
              label="Punya Rekening"
              :options="[{ value: '1', label: 'Ya' }, { value: '0', label: 'Tidak' }]"
              placeholder="Semua"
            />
          </FilterSection>
        </template>
      </FilterPanel>
    </Card>

    <Deferred data="suppliers">
      <template #fallback>
        <LoadingCard message="Mengambil data supplier…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

      <div class="mb-3 flex items-center justify-between">
        <span class="text-sm text-ink-muted">{{ filtered.length.toLocaleString("id-ID") }} supplier</span>
        <ExportButton mode="client" filename="supplier" :columns="exportColumns" :rows="filtered" sheet-name="Supplier" />
      </div>

      <DataTable :columns="columns" row-key="kd_supplier" :rows="filtered" empty-message="Supplier tidak ditemukan." />
    </Deferred>
  </AdminLayout>
</template>
