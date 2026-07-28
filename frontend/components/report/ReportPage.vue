<script setup>
import { computed, ref } from "vue";
import { Deferred, usePage } from "@inertiajs/vue3";
import Banner from "@/components/ui/Banner.vue";
import Input from "@/components/ui/Input.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import ServerTable from "@/components/report/ServerTable.vue";
import ExportButton from "@/components/ui/ExportButton.vue";

const props = defineProps({
  // Judul halaman sengaja tidak diterima di sini — AdminLayout yang memilikinya.
  deferredKey: { type: String, required: true }, // Inertia prop name, e.g. "report"
  data: { type: Object, default: null }, // the deferred payload
  columns: { type: Array, required: true },
  rowKey: { type: String, default: "id" },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  sortKey: { type: String, default: "" },
  sortDir: { type: String, default: "desc" },
  exportHref: { type: String, default: "" },
  summaryItems: { type: Array, default: () => [] },
  recent: { type: Boolean, default: false }, // showing the "100 terbaru" first-load snapshot
});
const emit = defineEmits(["page-change", "sort-change", "per-page-change"]);

// Kolom yang bisa diurut ditentukan server: `filters.sort_keys` adalah whitelist
// ORDER BY yang sama yang dipakai parse_report_params. Dulu tiap halaman menandai
// `sortable: true` sendiri dan daftarnya menyimpang — header yang bisa diklik tapi
// diam-diam jatuh ke sort default (Piutang/Shift/Opname "No. Transaksi"), dan kolom
// yang sebenarnya bisa diurut tapi tak pernah ditawarkan (Promo, Voucher, FMI).
// Flag kolom tetap dihormati bagi halaman yang belum mengirim sort_keys.
// Dibaca di dalam computed (Inertia mengganti objek props tiap kunjungan, jadi
// salinan setup akan basi); dinamai `inertiaPage` supaya tak menutupi prop `page`.
const inertiaPage = usePage();
const sortKeys = computed(() => inertiaPage.props.filters?.sort_keys || null);
const cols = computed(() =>
  sortKeys.value
    ? props.columns.map((c) => ({ ...c, sortable: sortKeys.value.includes(c.key) }))
    : props.columns,
);

// Pencarian sisi-peramban: menyaring baris yang SEDANG tampil saja (halaman ini
// dipaginasi server). Filter "Cari" di panel filter yang menyaring seluruh
// dataset di server; yang ini untuk menemukan satu baris di antara 100 yang
// sudah di layar tanpa bolak-balik ke server.
const q = ref("");
const rows = computed(() => (props.data && props.data.rows) || []);
const displayed = computed(() => {
  const term = q.value.toLowerCase().trim();
  if (!term) return rows.value;
  const keys = props.columns.map((c) => c.key);
  return rows.value.filter((r) =>
    keys.some((k) => String(r[k] ?? "").toLowerCase().includes(term)),
  );
});
const nf = new Intl.NumberFormat("id-ID");
</script>

<template>
  <div>
    <!-- Judul halaman dimiliki AdminLayout (bersama eyebrow seksi). Merender
         ulang di sini membuat judul tercetak dua kali sekaligus dua <h1> dalam
         satu dokumen. -->

    <!-- Filter panel lives OUTSIDE Deferred so it shows instantly -->
    <slot name="filters" />

    <Deferred :data="deferredKey">
      <template #fallback><TableSkeleton /></template>

      <Banner v-if="data && data.conn_error" variant="warning" :message="data.conn_error" />
      <!-- Rentang tanggal dipangkas: pemberitahuan, bukan kegagalan koneksi. -->
      <Banner v-if="data && data.notice" variant="info" :message="data.notice" />
      <Banner
        v-if="!(data && data.conn_error) && recent"
        variant="info"
        message="Menampilkan 100 data terbaru. Gunakan filter untuk melihat data lain."
      />
      <SummaryStrip :items="summaryItems" />

      <!-- Satu baris alat di atas tabel — sama seperti halaman Operasional:
           cari-dalam-halaman, hitungan baris, lalu export di ujung kanan.
           Sebelumnya tombol export berdiri sendiri di barisnya sendiri DI ATAS
           panel filter, jauh dari tabel yang diexportnya. -->
      <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="sm:max-w-xs sm:flex-1">
          <Input v-model="q" label="Cari (dalam halaman ini)" placeholder="saring baris yang tampil…" />
        </div>
        <p class="text-xs text-ink-subtle sm:pb-2">
          Menampilkan {{ nf.format(displayed.length) }} dari {{ nf.format(rows.length) }} baris di halaman
          ini<template v-if="data && data.total"> · {{ nf.format(data.total) }} total</template>.
        </p>
        <div v-if="exportHref" class="sm:ml-auto sm:pb-0.5">
          <ExportButton mode="server" :href="exportHref" />
        </div>
      </div>

      <ServerTable
        :columns="cols"
        :rows="displayed"
        :row-key="rowKey"
        :total="(data && data.total) || 0"
        :page="page"
        :per-page="perPage"
        :sort-key="sortKey"
        :sort-dir="sortDir"
        @page-change="emit('page-change', $event)"
        @sort-change="emit('sort-change', $event)"
        @per-page-change="emit('per-page-change', $event)"
      >
        <template v-for="(_, name) in $slots" #[name]="slotProps">
          <slot :name="name" v-bind="slotProps" />
        </template>
      </ServerTable>
    </Deferred>
  </div>
</template>
