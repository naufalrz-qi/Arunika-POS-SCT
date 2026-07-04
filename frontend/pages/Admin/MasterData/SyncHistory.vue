<script setup>
import { ref, computed } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Modal from "@/components/ui/Modal.vue";
import Badge from "@/components/ui/Badge.vue";

const props = defineProps({ data: { type: Object, default: null } });
const rows = computed(() => props.data?.rows || []);
const columns = [
  { key: "created_at", label: "Waktu", sortable: true, format: "date" },
  { key: "user", label: "User" },
  { key: "src", label: "Sumber" },
  { key: "dst", label: "Tujuan" },
  { key: "mode", label: "Mode" },
  { key: "total_items", label: "Baris", align: "right", format: "number" },
  { key: "status", label: "Status" },
];
const detail = ref(null);
</script>

<template>
  <AdminLayout title="Riwayat Sinkronisasi Harga">
    <Deferred data="data">
      <template #fallback><LoadingCard message="Mengambil riwayat…" /></template>
      <ReportView
        title="Riwayat Sinkronisasi Harga"
        :columns="columns"
        :rows="rows"
        row-key="id"
        :search-keys="['user', 'src', 'dst']"
        export-name="riwayat-sync"
        sheet-name="Riwayat Sync"
        :conn-error="data && data.conn_error"
      >
        <template #cell-status="{ value }">
          <Badge :variant="value === 'ok' ? 'success' : value === 'gagal' ? 'danger' : 'warning'">{{ value }}</Badge>
        </template>
        <template #cell-total_items="{ row, value }">
          <button class="text-brand-fg underline" @click="detail = row">{{ value }}</button>
        </template>
      </ReportView>
    </Deferred>

    <Modal :show="!!detail" title="Detail Item Sinkronisasi" size="lg" @close="detail = null">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-ink-muted">
            <th class="py-1 text-left">Barang</th>
            <th class="py-1 text-left">Satuan</th>
            <th class="py-1 text-right">Harga Lama</th>
            <th class="py-1 text-right">Harga Baru</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(it, i) in (detail?.items || [])" :key="i" class="border-t border-border-default">
            <td class="py-1">{{ it.nama_barang }}</td>
            <td class="py-1">{{ it.kd_satuan }}</td>
            <td class="py-1 text-right text-ink-muted">{{ it.harga_lama_dst }}</td>
            <td class="py-1 text-right font-semibold text-ink">{{ it.harga_baru }}</td>
          </tr>
        </tbody>
      </table>
    </Modal>
  </AdminLayout>
</template>
