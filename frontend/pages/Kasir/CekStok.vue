<script setup>
import { computed, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  stok: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const data = computed(() => props.stok || {});
const rows = computed(() => data.value.rows || []);

const cari = ref(props.filters.cari || "");
const kdDivisi = ref(props.filters.kd_divisi || "");

const divisiOptions = computed(() =>
  (data.value.divisi_list || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

function submit() {
  router.get(
    "/kasir/stok",
    { cari: cari.value, kd_divisi: kdDivisi.value },
    { preserveState: true, preserveScroll: true },
  );
}

// Persis kolom yang dikirim stock_levels — bentuknya sengaja ramping di sana
// (~55rb barang, tiap kolom tambahan ~1 MB JSON). Harga jual TIDAK ada di
// payload ini dan sengaja tidak diambil lewat query kedua: layar ini menjawab
// "ada berapa", bukan "berapa harganya".
const columns = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Barang", sortable: true },
  { key: "stok_akhir", label: "Stok", align: "right", sortable: true },
  { key: "stok_min", label: "Stok Min.", align: "right" },
];

const sudahCari = computed(() => Boolean(props.filters.cari));
</script>

<template>
  <AdminLayout title="Cek Stok">
    <!-- Form di LUAR <Deferred> supaya kotak carinya langsung bisa diketik,
         tak menunggu hasil pencarian sebelumnya selesai dimuat. -->
    <Card class="mb-4">
      <form class="flex flex-wrap items-end gap-3" @submit.prevent="submit">
        <Input
          v-model="cari"
          label="Cari barang"
          placeholder="Kode atau nama barang…"
          class="min-w-[16rem] flex-1"
        />
        <Select
          v-model="kdDivisi"
          label="Divisi"
          :options="divisiOptions"
          placeholder="Semua divisi"
          class="min-w-[12rem]"
        />
        <Button type="submit">Cari</Button>
      </form>
    </Card>

    <Deferred data="stok">
      <template #fallback>
        <LoadingCard message="Mencari barang…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" class="mb-4" />

      <Card>
        <EmptyState
          v-if="!sudahCari"
          message="Ketik kode atau nama barang di atas, lalu tekan Cari."
        />
        <EmptyState
          v-else-if="!rows.length"
          message="Tidak ada barang yang cocok dengan pencarian itu."
        />
        <DataTable v-else :rows="rows" :columns="columns" />
      </Card>
    </Deferred>
  </AdminLayout>
</template>
