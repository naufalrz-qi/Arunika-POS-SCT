<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Badge from "@/components/ui/Badge.vue";
import { useReportFilters } from "@/composables/useReportFilters";

const props = defineProps({
  // Bundle deferred {rows, divisi_list, snapshot, conn_error} — datang setelah mount.
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const rows = computed(() => props.data?.rows ?? []);
const snapshot = computed(() => props.data?.snapshot ?? null);

// Sengaja TANPA filter tanggal: halaman ini selalu "stok hari ini". Tanggal
// lampau apa pun mematikan jalur ringkasan stok harian di backend dan bikin
// halaman lambat lagi — untuk itu ada menu "Stok Akhir".
const { filters: pull, loading: pulling, apply: tarikData } = useReportFilters(
  "/admin-panel/inventory/stok-divisi",
  { kd_divisi: props.filters.kd_divisi || "" },
);

const divisiOptions = computed(() => [
  { value: "", label: "Semua Divisi" },
  ...(props.data?.divisi_list ?? []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
]);

const columns = [
  { key: "kd_barang", label: "Kode" },
  { key: "nama", label: "Barang" },
  { key: "divisi", label: "Divisi" },
  { key: "stok_akhir", label: "Stok", align: "right", format: "number" },
];
</script>

<template>
  <AdminLayout title="Stok per Divisi">
    <!-- Filter di luar <Deferred> supaya langsung tampil sebelum data datang. -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="min-w-[14rem]">
          <label class="mb-1 block text-sm font-medium">Divisi</label>
          <Select v-model="pull.kd_divisi" :options="divisiOptions" />
        </div>
        <Button :disabled="pulling" @click="tarikData">
          {{ pulling ? "Memuat…" : "Tampilkan" }}
        </Button>
      </div>
      <p class="mt-2 text-sm text-neutral-500">
        Menampilkan saldo stok saat ini. Untuk stok pada tanggal lampau, gunakan menu
        <strong>Stok Akhir</strong>.
      </p>
    </Card>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil stok…" /></template>

      <Banner
        v-if="snapshot && !snapshot.fresh"
        variant="warning"
        message="Perhitungan stok sedang memakai jalur lambat karena ringkasan stok harian belum siap. Angka tetap benar, hanya lebih lambat. Hubungi admin aplikasi."
        class="mb-4"
      />

      <ReportView
        title="Stok per Divisi"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang', 'nama']"
        export-name="stok-divisi"
        sheet-name="Stok Divisi"
        empty-message="Tidak ada barang dengan stok atau pergerakan di divisi ini."
        :conn-error="data && data.conn_error"
      >
        <template #cell-stok_akhir="{ row }">
          <Badge v-if="row.stok_min !== undefined && row.stok_akhir < row.stok_min" variant="danger">{{ row.stok_akhir }}</Badge>
          <span v-else>{{ new Intl.NumberFormat('id-ID').format(row.stok_akhir || 0) }}</span>
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
