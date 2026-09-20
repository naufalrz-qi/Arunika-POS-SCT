<script setup>
import { computed } from "vue";
import { Deferred, usePage } from "@inertiajs/vue3";
import Banner from "@/components/ui/Banner.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import ServerTable from "@/components/report/ServerTable.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import Badge from "@/components/ui/Badge.vue";
import { tanggalJam } from "@/utils/tanggal";

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
// --- Cap waktu server ------------------------------------------------------
// Formatnya SAMA PERSIS dengan kolom `tanggal` di sebelahnya (`utils/tanggal.js`,
// dipakai juga oleh BaseTable). Dulu slot ini punya formatter sendiri
// (`20 Sep 2026`) sementara tetangganya `20/9/2026` — dua kolom yang dipasang
// bersebelahan justru untuk DIBANDINGKAN, dengan dua bentuk berbeda dan
// jam yang sama-sama dibuang.

/**
 * Selisih HARI antara cap server dan tanggal dokumen, bertanda.
 *
 * Positif = dokumen bertanggal LEBIH AWAL dari saat ia tersimpan (dimundurkan).
 * Negatif = bertanggal maju, dokumen bertanggal masa depan saat disimpan.
 * 0/NaN = tak ada yang perlu ditandai.
 *
 * Dibandingkan per HARI KALENDER, bukan per jam: nota yang disimpan pukul 23.50
 * dan dicetak 00.10 bukan anomali, dan selisih jam akan menandainya tiap malam.
 */
function bedaHari(row) {
  if (!row.tanggal || !row.tanggal_server) return 0;
  const hari = (v) => {
    const d = new Date(v);
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  };
  const n = Math.round((hari(row.tanggal_server) - hari(row.tanggal)) / 86400000);
  return Number.isFinite(n) ? n : 0;
}

const sumberArunika = computed(() => inertiaPage.props.sumber_laporan === "arunika");
const sortKeys = computed(() => inertiaPage.props.filters?.sort_keys || null);
const cols = computed(() =>
  sortKeys.value
    ? props.columns.map((c) => ({ ...c, sortable: sortKeys.value.includes(c.key) }))
    : props.columns,
);

// Satu kotak cari saja: "Cari" di panel filter, dikerjakan server atas seluruh
// data. Dulu ada kotak kedua di atas tabel yang hanya menyaring baris di
// halaman ini — duduknya lebih dekat, jadi itu yang dipakai orang, lalu mereka
// menyimpulkan barangnya tak ada padahal cuma tak ada DI HALAMAN INI. Label
// "(dalam halaman ini)" dan tombol "cari di seluruh data" tak cukup mencegahnya.
const rows = computed(() => (props.data && props.data.rows) || []);
const nf = new Intl.NumberFormat("id-ID");
</script>

<template>
  <div>
    <!-- Judul halaman dimiliki AdminLayout (bersama eyebrow seksi). Merender
         ulang di sini membuat judul tercetak dua kali sekaligus dua <h1> dalam
         satu dokumen. -->

    <!-- Sumber data laporan. HANYA muncul saat bentuk Arunika yang dibaca —
         pemasangan default (ARUNIKA_LAPORAN mati) tak melihat perubahan apa
         pun. Sebelum ini tak ada satu pun tanda di layar tentang sumber mana
         yang dipakai, padahal kedua syaratnya tersembunyi di .env dan tabel
         koneksi. Satu komponen, 26 laporan. -->
    <div v-if="sumberArunika" class="mb-3">
      <Badge variant="info">Sumber: Arunika</Badge>
      <span class="ml-2 text-xs text-ink-muted">
        Angka di halaman ini dibaca dari database Arunika, bukan tabel legacy.
      </span>
    </div>

    <!-- Filter panel lives OUTSIDE Deferred so it shows instantly -->
    <slot name="filters" />

    <Deferred :data="deferredKey">
      <template #fallback><TableSkeleton /></template>

      <Banner v-if="data && data.conn_error" variant="warning" :message="data.conn_error" />
      <!-- Rentang tanggal dipangkas: pemberitahuan, bukan kegagalan koneksi. -->
      <Banner v-if="data && data.notice" variant="info" :message="data.notice" />
      <!-- Peringatan milik halaman yang baru bisa dinilai SESUDAH datanya tiba
           (mis. Hutang: kolom cicilan nol karena tak pernah dicatat). Di dalam
           Deferred, jadi ia tak sempat berkedip saat data belum ada. -->
      <slot name="peringatan" />
      <SummaryStrip :items="summaryItems" />

      <ServerTable
        :columns="cols"
        :rows="rows"
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

        <!-- Hitungan dan export menempel di tabel yang mereka jelaskan. "100 data
             terbaru" dulu banner biru selebar layar; isinya keterangan, bukan
             peringatan, jadi cukup satu kalimat di sini. -->
        <template #toolbar>
          <p class="text-xs text-ink-muted">
            <template v-if="recent && !(data && data.conn_error)">100 data terbaru — atur periode di Filter untuk data lain.</template>
            <template v-else>
              {{ nf.format(rows.length) }} baris di halaman ini<template v-if="data && data.total"> · {{ nf.format(data.total) }} total</template>
            </template>
          </p>
          <ExportButton v-if="exportHref" mode="server" :href="exportHref" />
        </template>

        <!-- Cap waktu server, dirender SEKALI di sini alih-alih disalin ke 13
             halaman laporan. `tanggal` bisa diubah operator di aplikasi POS
             lama, `tanggal_server` tidak — dan tanpa penanda, membandingkan dua
             kolom tanggal per baris adalah pekerjaan mata.

             Nada penandanya NETRAL: pada data nyata 83% baris pembelian berbeda
             hari secara sah (faktur pemasok bertanggal mundur). Yang diberi
             warna hanya dokumen bertanggal MAJU, yang jarang dan tak punya
             penjelasan wajar. Rinciannya di layar Nota Tanggal Mundur.

             Dijaga `v-if` supaya halaman yang punya kebutuhan sendiri tetap
             bisa menyediakan slot bernama sama tanpa bentrok. -->
        <template v-if="!$slots['cell-tanggal_server']" #cell-tanggal_server="{ row }">
          <span>{{ row.tanggal_server ? tanggalJam(row.tanggal_server) : "—" }}</span>
          <Badge v-if="bedaHari(row)" :variant="bedaHari(row) < 0 ? 'warning' : 'neutral'" class="ml-2">
            {{ bedaHari(row) < 0 ? `maju ${-bedaHari(row)} hari` : `beda ${bedaHari(row)} hari` }}
          </Badge>
        </template>
      </ServerTable>
    </Deferred>
  </div>
</template>
