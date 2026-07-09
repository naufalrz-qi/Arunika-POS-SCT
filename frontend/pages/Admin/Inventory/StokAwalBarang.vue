<script setup>
import { computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Button from "@/components/ui/Button.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import { useReportFilters } from "@/composables/useReportFilters";

const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const rows = computed(() => props.data?.rows || []);

const { filters: form, loading, apply, reset } = useReportFilters(
  "/admin-panel/inventory/stok-awal",
  { tanggal: props.filters.tanggal || "", tahun: props.filters.tahun || "" },
);

const columns = [
  { key: "kd_barang", label: "Kode" },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  { key: "stok_awal", label: "Stok Awal", align: "right", format: "number" },
];
</script>

<template>
  <AdminLayout title="Stok Awal Barang">
    <Card class="mb-6">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Input v-model="form.tanggal" label="Per Tanggal" type="date" @keyup.enter="apply()" />
        <Input v-model="form.tahun" label="Per Tahun" placeholder="mis. 2025" @keyup.enter="apply()" />
        <Button :loading="loading" @click="apply()">Tampilkan</Button>
        <Button variant="secondary" @click="reset()">Reset</Button>
      </div>
      <p class="mt-2 text-xs text-ink-subtle">
        Kosongkan filter untuk stok awal dasar. Isi tanggal atau tahun untuk saldo
        awal per periode (tanggal diprioritaskan bila keduanya diisi).
      </p>
    </Card>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil data…" /></template>
      <ReportView
        title="Stok Awal Barang"
        :columns="columns"
        :rows="rows"
        row-key="kd_barang"
        :search-keys="['kd_barang', 'barang', 'kategori']"
        export-name="stok-awal-barang"
        sheet-name="Stok Awal"
        :conn-error="data && data.conn_error"
      />
    </Deferred>
  </AdminLayout>
</template>
