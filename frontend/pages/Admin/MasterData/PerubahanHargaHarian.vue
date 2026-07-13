<script setup>
import { computed, reactive } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  data: { type: Object, default: null },
  profiles: { type: Array, default: () => [] },
  filters: { type: Object, default: () => ({}) },
  last_run: { type: Object, default: null },
});

const rows = computed(() => props.data?.rows || []);

const pick = reactive({
  kd_barang: props.filters.kd_barang || "",
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
  profile: props.filters.profile || "",
});

function tampilkan() {
  router.get("/admin-panel/master/perubahan-harga-harian", { ...pick }, { preserveState: true, preserveScroll: true });
}

const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const columns = [
  { key: "detected_at", label: "Terdeteksi", sortable: true },
  { key: "kd_barang", label: "Kode Barang", sortable: true },
  { key: "nama_barang", label: "Nama Barang", sortable: true },
  { key: "kd_satuan", label: "Satuan" },
  { key: "harga_lama", label: "Harga Lama", align: "right" },
  { key: "harga_baru", label: "Harga Baru", align: "right" },
  { key: "selisih", label: "Selisih", align: "right" },
  { key: "profile_name", label: "Koneksi" },
];
</script>

<template>
  <AdminLayout title="Perubahan Harga Harian">
    <p v-if="last_run" class="mb-3 text-xs text-ink-subtle">
      Snapshot terakhir: <span class="font-semibold text-ink-muted">{{ last_run.ran_at }}</span>
      · {{ last_run.profile_name }} · {{ last_run.changes }} perubahan dari {{ last_run.total }} SKU
    </p>
    <p v-else class="mb-3 text-xs text-ink-subtle">
      Belum ada snapshot. Jalankan otomatis saat server hidup, atau manual: <code class="rounded bg-surface-3 px-1">manage.py snapshot_harga</code>.
    </p>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil perubahan harga…" /></template>
      <ReportView
        title="Perubahan Harga Harian"
        subtitle="Perubahan harga yang terdeteksi snapshot harian, termasuk yang diubah langsung di POS."
        :columns="columns"
        :rows="rows"
        row-key="id"
        :search-keys="['kd_barang', 'nama_barang', 'profile_name']"
        export-name="perubahan-harga-harian"
        sheet-name="Perubahan Harga Harian"
        empty-message="Belum ada perubahan harga terdeteksi."
      >
        <template #filters>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Input v-model="pick.kd_barang" label="Kode Barang" placeholder="mis. TOP5026" @keyup.enter="tampilkan" />
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

        <template #cell-harga_lama="{ value }">
          <span class="text-ink-muted line-through decoration-danger-500/60">{{ rupiah(value) }}</span>
        </template>
        <template #cell-harga_baru="{ value }">
          <span class="font-semibold text-ink">{{ rupiah(value) }}</span>
        </template>
        <template #cell-selisih="{ value }">
          <span :class="value < 0 ? 'text-danger-600' : 'text-success-700'">
            {{ value > 0 ? "+" : "" }}{{ rupiah(value) }}
          </span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
