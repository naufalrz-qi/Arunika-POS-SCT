<script setup>
/**
 * Nota Tanggal Mundur — dokumen yang tanggalnya berbeda hari dari waktu simpan
 * terakhirnya, beserta PENYEBABNYA menurut jejak log server.
 *
 * Di aplikasi POS legacy, `tanggal` dokumen dirakit dari jam PC kasir;
 * `tanggal_server` adalah waktu dokumen TERAKHIR disimpan. Saat nota diedit,
 * legacy menimpa waktu simpan DAN kasir di nota dengan waktu dan akun
 * pengedit. Karena itu selisih tanggal punya dua penyebab yang tampak identik
 * di tabel — nota yang diedit belakangan, dan nota yang memang diinput dengan
 * tanggal lama — dan layar ini memisahkannya lewat jejak log
 * (apps/transactions/reports.py::nota_mundur).
 *
 * Nada layar ini sengaja NETRAL. Di data nyata 83% pembelian testGudang masuk
 * daftar ini secara sah (faktur pemasok bertanggal mundur itu normal). Layar
 * yang menuduh akan diabaikan dalam seminggu, dan bersamanya ekor yang benar-
 * benar layak diperiksa ikut hilang.
 */
import { computed, ref } from "vue";
import { Link } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import DetailNotaMundur from "@/components/report/DetailNotaMundur.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Banner from "@/components/ui/Banner.vue";
import Badge from "@/components/ui/Badge.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { tanggal } from "@/utils/tanggal";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/nota-mundur";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

const columns = [
  { key: "jenis", label: "Jenis Dokumen" },
  { key: "no_dokumen", label: "No. Dokumen" },
  { key: "tanggal", label: "Tanggal", format: "datetime" },
  { key: "tanggal_server", label: "Terakhir Disimpan", format: "datetime" },
  { key: "selisih_hari", label: "Selisih (hari)", align: "right", format: "number" },
  { key: "penyebab", label: "Penyebab" },
  { key: "dibuat_oleh", label: "Dibuat oleh" },
  { key: "diedit_oleh", label: "Diedit oleh" },
  { key: "divisi", label: "Divisi" },
  { key: "keterangan", label: "Keterangan" },
];

const divisiOptions = computed(() => props.report?.options?.divisi || []);
const jenisOptions = computed(() => props.report?.options?.jenis || []);
const penyebabOptions = computed(() => props.report?.options?.penyebab || []);

const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const nf = new Intl.NumberFormat("id-ID");
  // Satu kartu per penyebab. "Selisih Terjauh" dibuang: tabel sudah bisa
  // diurut menurut selisih, dan kartunya tak menjawab "apa yang terjadi".
  return [
    { label: "Jumlah Nota", value: nf.format(s.jml_dokumen || 0) },
    { label: "Tanggal Diubah (Edit)", value: nf.format(s.jml_pindah || 0) },
    { label: "Jam Komputer Salah", value: nf.format(s.jml_jam_komputer || 0) },
    { label: "Tanggal Tidak Wajar", value: nf.format(s.jml_tidak_wajar || 0) },
    { label: "Diedit Belakangan", value: nf.format(s.jml_diedit || 0) },
    { label: "Diinput Mundur", value: nf.format(s.jml_input_mundur || 0) },
    // Dipisah, bukan digabung: bertanggal MAJU jauh lebih jarang dan jauh lebih
    // aneh — 49 baris dari 3.483 di testGudang. Menjumlahkannya dengan yang
    // mundur akan menguburnya.
    { label: "Bertanggal Maju", value: nf.format(s.jml_maju || 0) },
    { label: "Tak Tercatat", value: nf.format(s.jml_tak_tercatat || 0) },
  ];
});

// Warna mengikuti seberapa perlu diperiksa, bukan seberapa sering. Yang paling
// berat "Tanggal tidak wajar": nota itu tak muncul di laporan mana pun. Lalu
// yang memindah penjualan ke hari lain (edit yang mengganti tanggal) dan jam
// komputer yang salah. "Diedit" biru: temuan paling umum, tanggalnya tetap.
const WARNA_PENYEBAB = {
  "Tanggal tidak wajar": "danger",
  "Tanggal diubah lewat edit": "warning",
  "Jam komputer salah": "warning",
  "Diinput maju": "warning",
  Diedit: "brand",
};

const dipilih = ref(null);
</script>

<template>
  <AdminLayout title="Nota Tanggal Mundur">
    <!-- Pendek dan tanpa istilah teknis; penjelasan lengkapnya di Bantuan. -->
    <Banner variant="info" class="mb-4">
      Nota di sini tanggalnya perlu dicek: berbeda dengan hari terakhir disimpan, <strong>dipindah lewat
      edit</strong>, atau tidak masuk akal. Penyebab paling umum adalah nota <strong>diedit belakangan</strong>;
      yang perlu diperhatikan adalah tanggal yang dipindah dan <strong>jam komputer kasir yang salah</strong>.
      Klik nomor nota untuk melihat isinya dan siapa yang mengubahnya.
      <Link href="/admin-panel/bantuan#nota-mundur" class="underline underline-offset-2 hover:no-underline">Penjelasan lengkap</Link>
    </Banner>

    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="_rid"
      :page="Number(form.page)"
      :per-page="Number(form.per_page)"
      :sort-key="form.sort"
      :sort-dir="form.sort_dir"
      :export-href="exportHref"
      :summary-items="summaryItems"
      @page-change="onPage"
      @sort-change="onSort"
      @per-page-change="onPerPage"
    >
      <template #filters>
        <FilterPanel :form="form" @submit="apply({ page: 1 })" @reset="reset">
          <FilterSection title="Periode & Pencarian">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.jenis" :options="jenisOptions" label="Jenis Dokumen" />
            <SelectSearch v-model="form.penyebab" :options="penyebabOptions" label="Penyebab" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <!-- Wajib ada, dan bawaannya 1. Tanpa ambang, pembelian testGudang
                 menyumbang 13.021 baris dan menenggelamkan ekornya. -->
            <Input v-model="form.min_selisih" label="Min. selisih (hari)" type="number" placeholder="1" />
            <Input v-model="form.search" label="Cari" placeholder="no dokumen / keterangan" />
          </FilterSection>
        </FilterPanel>
      </template>

      <!-- Nomor jadi tombol pembuka panel detail, bukan seluruh baris: bisa
           dijangkau keyboard, dan tak merebut aksi saat orang cuma ingin
           menyeleksi teks. -->
      <template #cell-no_dokumen="{ row }">
        <button
          type="button"
          class="text-left text-brand-fg underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          @click="dipilih = row"
        >
          {{ row.no_dokumen }}
        </button>
        <!-- Nomor lama = tanggal lamanya; nomornya berganti saat tanggal dipindah. -->
        <div v-if="row.nomor_asal" class="text-xs text-ink-subtle">
          dulu {{ row.nomor_asal }}<template v-if="row.tanggal_asal"> · {{ tanggal(row.tanggal_asal) }}</template>
        </div>
      </template>
      <template #cell-penyebab="{ row }">
        <Badge :variant="WARNA_PENYEBAB[row.penyebab] || 'neutral'">{{ row.penyebab }}</Badge>
      </template>
      <template #cell-dibuat_oleh="{ row }">
        <span :class="row.dibuat_oleh ? '' : 'text-ink-subtle'">{{ row.dibuat_oleh || "—" }}</span>
      </template>
      <template #cell-diedit_oleh="{ row }">
        <span :class="row.diedit_oleh ? '' : 'text-ink-subtle'">{{ row.diedit_oleh || "—" }}</span>
      </template>
      <template #cell-selisih_hari="{ row }">
        <span :class="Math.abs(row.selisih_hari) > 30 ? 'font-semibold text-warning-fg' : ''">
          {{ row.selisih_hari > 0 ? "+" : "" }}{{ row.selisih_hari }}
        </span>
      </template>
    </ReportPage>

    <DetailNotaMundur :baris="dipilih" @close="dipilih = null" />
  </AdminLayout>
</template>
