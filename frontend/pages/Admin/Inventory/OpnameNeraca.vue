<script setup>
/**
 * Neraca Opname — mencocokkan selisih opname LINTAS sesi, divisi, dan tanggal.
 *
 * Opname dihitung parsial supaya operasi tak berhenti, tapi akibatnya pasangan
 * plus-minus yang jatuh di sesi berbeda tak pernah bertemu di satu layar.
 * Halaman ini menjumlahkannya lebih dulu, lalu mengelompokkan barang sejenis,
 * sehingga "barang A minus 3, barang B plus 3" muncul sebagai satu baris.
 *
 * "Bisa Dipasangkan" = MIN(lebih, kurang), yaitu bagian yang masuk akal
 * dianggap tertukar. "Sisa Neto" = yang benar-benar belum terjelaskan.
 */
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Select from "@/components/ui/Select.vue";
import Input from "@/components/ui/Input.vue";
import DetailNeracaOpname from "@/components/report/DetailNeracaOpname.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { useHiddenData } from "@/composables/useHiddenData.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/inventory/opname-neraca";
const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(URL, props.filters);

// Urutan = urutan kegunaan. "Nama sama" menemukan sedikit pasangan tapi yang
// ketemu langsung bisa dikerjakan; "Kategori+Merk+Model" jaring yang jauh lebih
// lebar, dengan keluarga yang bisa berisi ratusan barang.
const GRUP_OPTIONS = [
  { value: "nama", label: "Nama barang sama (pasangan tepat)" },
  { value: "kkm", label: "Kategori + Merk + Model (jaring lebar)" },
];

// Tanpa `sortable`: ReportPage menetapkannya dari filters.sort_keys milik server.
// Menandainya manual di sini persis yang dulu menghasilkan header bisa-diklik
// tapi diam-diam jatuh ke sort bawaan.
const SEMUA_KOLOM = [
  { key: "grup", label: "Keluarga" },
  { key: "contoh", label: "Contoh Barang" },
  { key: "anggota", label: "Jml Barang", align: "right", format: "number" },
  { key: "lebih", label: "Koreksi Lebih", align: "right", format: "number" },
  { key: "kurang", label: "Koreksi Kurang", align: "right", format: "number" },
  { key: "terpasang", label: "Bisa Dipasangkan", align: "right", format: "number" },
  { key: "neto", label: "Sisa Neto", align: "right", format: "number" },
  { key: "nilai_kurang", label: "Nilai Kurang", align: "right", format: "rupiah" },
  { key: "nilai_neto", label: "Nilai Neto", align: "right", format: "rupiah" },
  { key: "status_neraca", label: "Status" },
  { key: "catatan", label: "Contoh Catatan" },
];
// Kosmetik saja — server sudah tak mengirim field-nya. Ini cuma supaya tak ada
// kolom yang seluruh selnya "-".
const KOLOM_UANG = { nilai_kurang: "nominal", nilai_neto: "nominal" };
const { bisaLihat, saringKolom } = useHiddenData();
const columns = computed(() => saringKolom(SEMUA_KOLOM, KOLOM_UANG));

const divisiOptions = computed(() => props.report?.options?.divisi || []);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const items = [
    { label: "Keluarga", value: nf.format(s.jml_grup || 0) },
    { label: "Koreksi Lebih", value: nf.format(s.total_lebih || 0) },
    { label: "Koreksi Kurang", value: nf.format(s.total_kurang || 0) },
    { label: "Bisa Dipasangkan", value: nf.format(s.total_terpasang || 0) },
    { label: "Sisa Neto", value: nf.format(s.total_neto || 0) },
  ];
  // Server tak mengirim kunci ini saat izin `nominal` dicabut; menampilkan
  // Rp 0 di situ justru menyesatkan, jadi kartunya ikut hilang.
  if (bisaLihat("nominal")) {
    items.push(
      { label: "Nilai Kurang", value: rp.format(s.total_nilai_kurang || 0) },
      { label: "Nilai Neto", value: rp.format(s.total_nilai_neto || 0) },
    );
  }
  return items;
});

const dipilih = ref(null);
// Panel detail harus menjawab rentang & pengelompokan YANG SAMA dengan tabel;
// tanpa ini ia diam-diam menjawab pertanyaan lain.
const detailParams = computed(() => ({
  date_from: form.date_from,
  date_to: form.date_to,
  kd_divisi: form.kd_divisi,
  grup: form.grup,
}));
</script>

<template>
  <AdminLayout title="Neraca Opname">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="grup"
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
          <FilterSection title="Periode & Pengelompokan">
            <DateRangeField class="sm:col-span-2" v-model:from="form.date_from" v-model:to="form.date_to" />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Select v-model="form.grup" :options="GRUP_OPTIONS" label="Dasar Pengelompokan" />
            <Input v-model="form.search" label="Cari" placeholder="keluarga / barang / catatan" />
          </FilterSection>
        </FilterPanel>
      </template>

      <!-- Sel Keluarga jadi tombol pembuka, bukan seluruh baris: bisa dijangkau
           keyboard, dan tak merebut aksi saat orang cuma ingin menyeleksi teks. -->
      <template #cell-grup="{ row }">
        <button
          type="button"
          class="text-left text-brand-fg underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          @click="dipilih = row"
        >
          {{ row.grup }}
        </button>
      </template>

      <template #cell-neto="{ row }">
        <span
          :class="[
            'tabular-nums',
            row.neto < 0 ? 'text-danger-fg' : row.neto > 0 ? 'text-success-fg' : 'text-ink-muted',
          ]"
        >
          {{ nf.format(row.neto || 0) }}
        </span>
      </template>
    </ReportPage>

    <DetailNeracaOpname :baris="dipilih" :params="detailParams" @close="dipilih = null" />
  </AdminLayout>
</template>
