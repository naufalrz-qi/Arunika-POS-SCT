<script setup>
import { computed, reactive } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  data: { type: Object, default: null },
  profiles: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
});

const rows = computed(() => props.data?.rows || []);

const pick = reactive({
  kd_barang: props.filters.kd_barang || "",
  field: props.filters.field || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
  profile: props.filters.profile || "",
});

function tampilkan() {
  router.get("/admin-panel/master/riwayat-update-barang", { ...pick }, { preserveState: true, preserveScroll: true });
}

const fieldOptions = [
  { value: "", label: "Semua" },
  { value: "harga", label: "Harga Jual" },
  { value: "status_barang", label: "Status Barang" },
  { value: "status_divisi", label: "Status Divisi" },
  { value: "status_satuan", label: "Status Satuan" },
];
const fieldLabel = Object.fromEntries(fieldOptions.map((o) => [o.value, o.label]));
const fieldVariant = (f) => (f === "harga" ? "brand" : "neutral");
const statusLabel = { 0: "Non-aktif", 1: "Aktif", 2: "Tidak dijual" };

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

function formatNilai(field, v) {
  if (field === "harga") return rupiah(Number(v) || 0);
  if (field && field.startsWith("status_")) return statusLabel[v] ?? v;
  return v || "—";
}

const columns = [
  { key: "created_at", label: "Waktu", sortable: true },
  { key: "kd_barang", label: "Kode Barang", sortable: true },
  { key: "nama_barang", label: "Nama Barang", sortable: true },
  { key: "field", label: "Jenis Perubahan" },
  { key: "kd_ref", label: "Ref" },
  { key: "nilai_lama", label: "Nilai Lama", align: "right" },
  { key: "nilai_baru", label: "Nilai Baru", align: "right" },
  { key: "username", label: "User" },
  { key: "profile_name", label: "Koneksi" },
];
</script>

<template>
  <AdminLayout title="Riwayat Update Barang">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil riwayat…" /></template>
      <ReportView
        title="Riwayat Update Barang"
        subtitle="Semua perubahan harga dan status dari halaman Update Barang, lintas koneksi."
        :columns="columns"
        :rows="rows"
        row-key="id"
        :search-keys="['kd_barang', 'nama_barang', 'username']"
        export-name="riwayat-update-barang"
        sheet-name="Riwayat Update Barang"
        empty-message="Belum ada riwayat perubahan."
      >
        <template #filters>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Input v-model="pick.kd_barang" label="Kode Barang" placeholder="mis. TOP5026" @keyup.enter="tampilkan" />
            <Select v-model="pick.field" label="Jenis Perubahan" :options="fieldOptions" />
            <Input v-model="pick.date_from" type="date" label="Dari Tanggal" />
            <Input v-model="pick.date_to" type="date" label="Sampai Tanggal" />
            <Select
              v-model="pick.profile"
              label="Koneksi"
              :options="[{ value: '', label: 'Semua' }, ...profiles]"
            />
          </div>
          <div class="mt-3 flex justify-end">
            <Button variant="primary" @click="tampilkan">Tampilkan</Button>
          </div>
        </template>

        <template #cell-field="{ value }">
          <Badge :variant="fieldVariant(value)">{{ fieldLabel[value] || value }}</Badge>
        </template>
        <template #cell-nilai_lama="{ row, value }">
          <span class="text-ink-muted line-through decoration-danger-500/60">{{ formatNilai(row.field, value) }}</span>
        </template>
        <template #cell-nilai_baru="{ row, value }">
          <span class="font-semibold text-ink">{{ formatNilai(row.field, value) }}</span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
