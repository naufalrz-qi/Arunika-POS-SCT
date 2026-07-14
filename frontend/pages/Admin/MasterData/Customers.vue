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
import SelectSearch from "@/components/ui/SelectSearch.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  customers: { type: Object, default: null },
});

const data = computed(() => props.customers || {});
const rows = computed(() => data.value.rows || []);

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function distinctOptions(list, key) {
  const values = new Set(list.map((r) => r[key]).filter((v) => v !== "" && v != null));
  return Array.from(values).map((v) => ({ value: v, label: v }));
}

const kotaOptions = computed(() => distinctOptions(rows.value, "kd_kota"));
const parentOptions = computed(() => distinctOptions(rows.value, "parent"));

const filters = reactive({
  search: "",
  kota: "",
  status: "",
  parent: "",
  npwp: "",
  disc_min: "",
  disc_max: "",
});

function resetFilters() {
  filters.search = "";
  filters.kota = "";
  filters.status = "";
  filters.parent = "";
  filters.npwp = "";
  filters.disc_min = "";
  filters.disc_max = "";
}

const filtered = computed(() => {
  const q = filters.search.toLowerCase().trim();
  return rows.value.filter((c) => {
    const matchQ =
      !q ||
      c.nama.toLowerCase().includes(q) ||
      c.kd_customer.toLowerCase().includes(q) ||
      (c.hp || "").includes(q);
    const matchKota = !filters.kota || c.kd_kota === filters.kota;
    const matchStatus = filters.status === "" || (filters.status === "1" ? c.status : !c.status);
    const matchParent = !filters.parent || c.parent === filters.parent;
    const matchNpwp = !filters.npwp || (filters.npwp === "1" ? !!c.npwp_no : !c.npwp_no);
    const matchDiscMin = filters.disc_min === "" || c.disc >= Number(filters.disc_min);
    const matchDiscMax = filters.disc_max === "" || c.disc <= Number(filters.disc_max);
    return matchQ && matchKota && matchStatus && matchParent && matchNpwp && matchDiscMin && matchDiscMax;
  });
});

const columns = [
  { key: "kd_customer", label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "kd_kota", label: "Kota" },
  { key: "alamat", label: "Alamat" },
  { key: "telepon", label: "Telepon" },
  { key: "fax", label: "Fax" },
  { key: "kontak", label: "Kontak" },
  { key: "hp", label: "HP" },
  { key: "email", label: "Email" },
  { key: "point", label: "Poin", sortable: true, align: "right" },
  { key: "limit_kredit", label: "Limit Kredit", sortable: true, align: "right" },
  { key: "disc", label: "Diskon (%)", align: "right" },
  { key: "status", label: "Status", align: "center" },
  { key: "parent", label: "Parent" },
  { key: "npwp_no", label: "No. NPWP" },
  { key: "nppkp_no", label: "No. NPPKP" },
  { key: "npwp_nama", label: "Nama NPWP" },
  { key: "npwp_alamat", label: "Alamat NPWP" },
  { key: "keterangan", label: "Keterangan" },
];

const exportColumns = columns.map(({ key, label }) => ({ key, label }));
</script>

<template>
  <AdminLayout title="Master Pelanggan">
    <Card class="mb-4">
      <FilterPanel :form="filters" @submit="() => {}" @reset="resetFilters">
        <FilterSection>
          <Input v-model="filters.search" label="Cari" placeholder="Kode / nama / HP…" />
          <SelectSearch v-model="filters.kota" :options="kotaOptions" label="Kota" placeholder="Semua kota" />
        </FilterSection>
        <template #lanjutan>
          <FilterSection title="Filter Lanjutan">
            <Select
              v-model="filters.status"
              label="Status"
              :options="[{ value: '1', label: 'Aktif' }, { value: '0', label: 'Nonaktif' }]"
              placeholder="Semua status"
            />
            <SelectSearch v-model="filters.parent" :options="parentOptions" label="Parent" placeholder="Semua" />
            <Select
              v-model="filters.npwp"
              label="Punya NPWP"
              :options="[{ value: '1', label: 'Ya' }, { value: '0', label: 'Tidak' }]"
              placeholder="Semua"
            />
            <Input v-model="filters.disc_min" label="Diskon Min (%)" type="number" />
            <Input v-model="filters.disc_max" label="Diskon Maks (%)" type="number" />
          </FilterSection>
        </template>
      </FilterPanel>
    </Card>

    <Deferred data="customers">
      <template #fallback>
        <LoadingCard message="Mengambil data pelanggan…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

      <div class="mb-3 flex items-center justify-between">
        <span class="text-sm text-ink-muted">{{ filtered.length.toLocaleString("id-ID") }} pelanggan</span>
        <ExportButton mode="client" filename="pelanggan" :columns="exportColumns" :rows="filtered" sheet-name="Pelanggan" />
      </div>

      <DataTable :columns="columns" row-key="kd_customer" :rows="filtered" empty-message="Pelanggan tidak ditemukan.">
        <template #cell-point="{ value }">{{ value.toLocaleString("id-ID") }}</template>
        <template #cell-limit_kredit="{ value }">{{ rupiah(value) }}</template>
        <template #cell-status="{ value }">
          <Badge :variant="value ? 'success' : 'danger'">{{ value ? "Aktif" : "Nonaktif" }}</Badge>
        </template>
      </DataTable>
    </Deferred>
  </AdminLayout>
</template>
