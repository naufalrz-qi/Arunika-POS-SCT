<script setup>
/**
 * Stok Akhir — seluruh katalog dipegang peramban, tapi dalam bentuk kolumnar.
 *
 * Halaman ini ada untuk mencari satu SKU di antara ~55rb tanpa bolak-balik ke
 * server, jadi paginasi server bukan jawabannya. Yang dulu membunuhnya bukan
 * jumlah baris melainkan bentuk payload: 15,6 MB "list of dict" yang jadi
 * 54.955 objek reaktif Vue (123 MB heap, tab Firefox Android tak pernah
 * selesai memuat). Sekarang 4,65 MB kolom-mayor + kamus, disimpan sebagai
 * typed array di luar reaktivitas — lihat useColumnarTable.js.
 *
 * Tanggal satu-satunya filter yang perlu ke server. Divisi/kategori/cari/urut
 * dikerjakan di sini, instan.
 */
import { computed, watch } from "vue";
import { Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import BaseTable from "@/components/ui/BaseTable.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import { useReportFilters } from "@/composables/useReportFilters";
import { useColumnarTable } from "@/composables/useColumnarTable";
import { useHiddenData } from "@/composables/useHiddenData";

const props = defineProps({
  // Bundle deferred {tabel, divisi_list, conn_error} — datang setelah mount.
  stok: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const connError = computed(() => props.stok?.conn_error ?? null);

const {
  ingest, dictOptions, sumOf,
  searchInput, search, sortKey, sortDir, page, perPage, equals,
  total, n, pageRows, setSort, setPerPage, setEquals,
} = useColumnarTable(() => props.stok?.tabel, {
  searchKeys: ["kd_barang", "barang", "merk"],
  defaultSort: "barang",
  defaultSortDir: "asc",
});

// Prop deferred datang belakangan, dan berganti lagi tiap kali tanggal ditarik
// ulang. `immediate` menangkap kasus prop sudah ada saat mount (navigasi balik).
watch(() => props.stok?.tabel, (payload) => ingest(payload), { immediate: true });

// Hanya tanggal yang perlu ke server; sisanya disaring di klien.
const { filters: pull, loading: pulling, apply: tarikData } = useReportFilters(
  "/admin-panel/inventory/stock",
  { tanggal: props.filters.tanggal || new Date().toISOString().slice(0, 10) },
);

const divisiOptions = computed(() => dictOptions("divisi"));
const kategoriOptions = computed(() => dictOptions("kategori"));

// Kolom nilai uang dibuang bila izinnya dicabut. Ini hanya merapikan layar —
// field-nya memang sudah tak ada di payload (lihat _tanpa_kolom di views.py),
// jadi tanpa penyaringan ini yang muncul cuma deretan sel "-".
const { bisaLihat, saringKolom } = useHiddenData();
const KOLOM_UANG = {
  harga_jual: "harga_jual",
  harga_average: "harga_beli",
  harga_beli_akhir: "harga_beli",
  nominal: "nominal",
};

const SEMUA_KOLOM = [
  { key: "kd_divisi", label: "Kode Div." },
  { key: "divisi", label: "Divisi", sortable: true },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "kategori", label: "Kategori", sortable: true },
  // Kunci mengikuti kolom legacy (merk/model/warna); labelnya sebutan di toko.
  { key: "merk", label: "Divisi Barang", sortable: true },
  { key: "model", label: "Departemen" },
  { key: "warna", label: "Sub Kategori" },
  { key: "ukuran", label: "Ukuran" },
  { key: "stok_akhir", label: "Stok Akhir", align: "right", sortable: true },
  { key: "harga_average", label: "Harga Avg", align: "right", format: "rupiah" },
  { key: "harga_jual", label: "Harga Jual", align: "right", format: "rupiah" },
  { key: "nominal", label: "Nominal", align: "right", format: "rupiah", sortable: true },
  { key: "harga_beli_akhir", label: "Harga Beli Akhir", align: "right", format: "rupiah" },
];
const columns = computed(() => saringKolom(SEMUA_KOLOM, KOLOM_UANG));

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});

// Ringkasan dihitung atas hasil saringan, langsung dari typed array — tak ada
// baris yang dijadikan objek untuk ini.
const summaryItems = computed(() => {
  const items = [
    { label: "Baris", value: `${nf.format(total.value)} dari ${nf.format(n.value)}` },
    { label: "Total Stok", value: nf.format(Math.round(sumOf("stok_akhir") * 1000) / 1000) },
  ];
  // Tanpa kolom `nominal`, sumOf mengembalikan 0 — menampilkan "Rp 0" sebagai
  // total nilai persediaan bukan sekadar jelek, itu angka yang salah.
  if (bisaLihat("nominal")) {
    items.push({ label: "Total Nilai Stok", value: rp.format(sumOf("nominal")) });
  }
  return items;
});

// Export tetap dikerjakan server: SheetJS atas 55rb baris adalah lonjakan heap
// yang justru sedang dihindari halaman ini. Kirim keadaan filter yang sedang
// dilihat supaya isi file = isi layar.
const exportHref = computed(() => {
  const p = new URLSearchParams({ tanggal: pull.tanggal });
  if (search.value.trim()) p.set("search", search.value.trim());
  if (equals.value.kategori) p.set("kategori", equals.value.kategori);
  if (equals.value.divisi) p.set("divisi", equals.value.divisi);
  if (sortKey.value) {
    p.set("sort", sortKey.value);
    p.set("sort_dir", sortDir.value);
  }
  return `/admin-panel/inventory/stock/export?${p.toString()}`;
});
</script>

<template>
  <AdminLayout title="Stok Akhir">
    <Banner v-if="connError" variant="warning" :message="connError" />

    <!-- Di luar <Deferred>: tanggal harus bisa diubah sebelum data datang. -->
    <Card title="Tarik Data" subtitle="Hanya tanggal yang perlu ditarik ulang dari server" class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <div class="w-44">
          <Input v-model="pull.tanggal" label="Per Tanggal" type="date" />
        </div>
        <Button :loading="pulling" @click="tarikData()">Tarik Data</Button>
      </div>
    </Card>

    <Deferred data="stok">
      <template #fallback><TableSkeleton /></template>

      <SummaryStrip :items="summaryItems" />

      <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="searchInput" label="Cari (seluruh data)" placeholder="kode / nama barang / merk…" />
        </div>
        <div class="sm:w-48">
          <Select
            :model-value="equals.divisi || ''"
            label="Divisi"
            :options="divisiOptions"
            placeholder="Semua divisi"
            @update:model-value="setEquals('divisi', $event)"
          />
        </div>
        <div class="sm:w-52">
          <Select
            :model-value="equals.kategori || ''"
            label="Kategori"
            :options="kategoriOptions"
            placeholder="Semua kategori"
            @update:model-value="setEquals('kategori', $event)"
          />
        </div>
        <div class="sm:ml-auto sm:pb-0.5">
          <ExportButton mode="server" :href="exportHref" />
        </div>
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
        empty-message="Tidak ada barang yang cocok dengan filter ini."
        @page-change="page = $event"
        @sort-change="setSort($event)"
        @per-page-change="setPerPage($event)"
      >
        <template #cell-stok_akhir="{ value }">
          <span :class="value <= 0 ? 'font-semibold text-danger-fg' : 'font-semibold'">
            {{ nf.format(value ?? 0) }}
          </span>
        </template>
      </BaseTable>
    </Deferred>
  </AdminLayout>
</template>
