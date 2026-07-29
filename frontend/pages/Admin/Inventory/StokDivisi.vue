<script setup>
/**
 * Cek stok cepat: SELALU saldo hari ini, seluruh katalog di peramban.
 *
 * Bentuk payload kolumnar seperti Stok Akhir — halaman ini dulu mengirim
 * 54.955 baris list-of-dict (5,2 MB) lalu mengurut/memaginasi di Vue. Lihat
 * useColumnarTable.js untuk alasannya.
 *
 * Filter divisi TETAP lewat server. Bukan kelalaian: `stock_levels`
 * mengagregasi berbeda ketika divisi dipilih (per (divisi, barang), bukan
 * diruntuhkan per barang), jadi memilih divisi mengubah ANGKANYA — tak bisa
 * dikerjakan sebagai penyaringan baris di klien.
 */
import { computed, watch } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import Badge from "@/components/ui/Badge.vue";
import BaseTable from "@/components/ui/BaseTable.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import { useReportFilters } from "@/composables/useReportFilters";
import { useColumnarTable } from "@/composables/useColumnarTable";

const props = defineProps({
  // Bundle deferred {tabel, divisi_list, snapshot, conn_error}.
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const snapshot = computed(() => props.data?.snapshot ?? null);
const connError = computed(() => props.data?.conn_error ?? null);

const {
  ingest, searchInput, sortKey, sortDir, page, perPage,
  total, n, pageRows, setSort, setPerPage,
} = useColumnarTable(() => props.data?.tabel, {
  searchKeys: ["kd_barang", "nama"],
  defaultSort: "nama",
  defaultSortDir: "asc",
});

watch(() => props.data?.tabel, (payload) => ingest(payload), { immediate: true });

// Sengaja TANPA filter tanggal: halaman ini selalu "stok hari ini". Tanggal
// lampau apa pun mematikan jalur snapshot di backend dan bikin halaman lambat
// lagi — untuk itu ada menu "Stok Akhir".
const { filters: pull, loading: pulling, apply: tarikData } = useReportFilters(
  "/admin-panel/inventory/stok-divisi",
  { kd_divisi: props.filters.kd_divisi || "" },
);

const divisiOptions = computed(() =>
  (props.data?.divisi_list ?? []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

const divisiAktif = computed(() => {
  const d = (props.data?.divisi_list ?? []).find((x) => x.kd_divisi === props.filters.kd_divisi);
  return d ? d.nama : "Semua Divisi";
});

// Kolom Divisi sengaja tak ada: nilainya konstan (sudah ditentukan filter di
// server), jadi mengirimnya per baris cuma menggandakan payload di ~55rb baris.
const columns = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Barang", sortable: true },
  { key: "stok_akhir", label: "Stok", align: "right", sortable: true },
];

const nf = new Intl.NumberFormat("id-ID");
const summaryItems = computed(() => [
  { label: "Divisi", value: divisiAktif.value },
  { label: "Baris", value: `${nf.format(total.value)} dari ${nf.format(n.value)}` },
]);
</script>

<template>
  <AdminLayout title="Stok per Divisi">
    <Banner v-if="connError" variant="warning" :message="connError" />

    <!-- Filter di luar <Deferred> supaya langsung tampil sebelum data datang. -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="min-w-[14rem]">
          <Select v-model="pull.kd_divisi" label="Divisi" :options="divisiOptions" placeholder="Semua Divisi" />
        </div>
        <Button :loading="pulling" @click="tarikData()">Tampilkan</Button>
      </div>
      <p class="mt-2 text-sm text-ink-muted">
        Menampilkan saldo stok saat ini. Untuk stok pada tanggal lampau, gunakan menu
        <strong>Stok Akhir</strong>.
      </p>
    </Card>

    <Deferred data="data">
      <template #fallback><TableSkeleton /></template>

      <Banner
        v-if="snapshot && !snapshot.fresh"
        variant="warning"
        message="Perhitungan stok sedang memakai jalur lambat karena ringkasan stok harian belum siap. Angka tetap benar, hanya lebih lambat. Hubungi admin aplikasi."
        class="mb-4"
      />

      <SummaryStrip :items="summaryItems" />

      <div class="mb-3 sm:max-w-xs">
        <Input v-model="searchInput" label="Cari (seluruh data)" placeholder="kode / nama barang…" />
      </div>

      <BaseTable
        :columns="columns"
        :rows="pageRows"
        row-key="_rid"
        :total="total"
        :page="page"
        :per-page="perPage"
        :sort-key="sortKey"
        :sort-dir="sortDir"
        empty-message="Tidak ada barang dengan stok atau pergerakan di divisi ini."
        @page-change="page = $event"
        @sort-change="setSort($event)"
        @per-page-change="setPerPage($event)"
      >
        <template #cell-stok_akhir="{ row }">
          <Badge v-if="row.stok_min && row.stok_akhir < row.stok_min" variant="danger">
            {{ nf.format(row.stok_akhir) }}
          </Badge>
          <span v-else>{{ nf.format(row.stok_akhir || 0) }}</span>
        </template>
      </BaseTable>
    </Deferred>
  </AdminLayout>
</template>
