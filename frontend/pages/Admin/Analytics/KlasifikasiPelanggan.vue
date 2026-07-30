<script setup>
import { computed, ref } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportPage from "@/components/report/ReportPage.vue";
import ColumnFilters from "@/components/report/ColumnFilters.vue";
import DetailPelanggan from "@/components/report/DetailPelanggan.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import Badge from "@/components/ui/Badge.vue";
import { useServerReport } from "@/composables/useServerReport.js";
import { useHiddenData } from "@/composables/useHiddenData.js";
import { paramNamesFor } from "@/utils/reportFilters.js";

const props = defineProps({
  report: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/klasifikasi-pelanggan";

const SEGMEN = ["Hilang", "Mulai Jarang", "Baru", "Setia", "Aktif"];
const TIER = ["Besar", "Sedang", "Kecil"];
const opsi = (list) => list.map((v) => ({ value: v, label: v }));

const filterDefs = [
  { key: "customer", label: "Pelanggan", type: "text" },
  { key: "kota", label: "Kota", type: "text" },
  { key: "segmen", label: "Segmen", type: "category", options: opsi(SEGMEN) },
  { key: "tier_nilai", label: "Kelas Nilai", type: "category", options: opsi(TIER) },
  { key: "jml_nota", label: "Jml Nota", type: "number_range" },
  { key: "total_belanja", label: "Total Belanja", type: "number_range" },
  { key: "rata_nota", label: "Rata per Nota", type: "number_range" },
  { key: "jeda_hari", label: "Jeda (hari)", type: "number_range" },
];

const { form, apply, onPage, onSort, onPerPage, reset, exportHref } = useServerReport(
  URL, props.filters, paramNamesFor(filterDefs),
);

// Kolom uang dibuang dari tabel HANYA sebagai kerapian tampilan — datanya sendiri
// tak pernah dikirim server (lihat _hidden_fields). Tanpa ini kolomnya tetap ada
// dengan seluruh sel berisi "-".
const { saringKolom } = useHiddenData();
const columns = computed(() =>
  saringKolom(
    [
      { key: "customer", label: "Pelanggan" },
      { key: "segmen", label: "Segmen" },
      { key: "hp", label: "HP" },
      { key: "kota", label: "Kota" },
      { key: "jml_nota", label: "Jml Nota", align: "right", format: "number" },
      { key: "total_belanja", label: "Total Belanja", align: "right", format: "rupiah" },
      { key: "rata_nota", label: "Rata per Nota", align: "right", format: "rupiah" },
      { key: "tier_nilai", label: "Kelas Nilai" },
      { key: "nota_terakhir", label: "Belanja Terakhir" },
      { key: "jeda_hari", label: "Jeda (hari)", align: "right", format: "number" },
      { key: "nota_pertama", label: "Belanja Pertama" },
      { key: "umur_hari", label: "Lama Jadi Pelanggan", align: "right", format: "number" },
    ],
    {
      total_belanja: "nominal",
      rata_nota: "nominal",
      tier_nilai: "nominal",
    },
  ),
);

// Warna mengikuti urgensi follow-up, bukan selera: merah = sudah hilang.
const WARNA_SEGMEN = {
  Hilang: "danger",
  "Mulai Jarang": "warning",
  Baru: "brand",
  Setia: "success",
  Aktif: "neutral",
};

const divisiOptions = computed(() => props.report?.options?.divisi || []);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const summaryItems = computed(() => {
  const s = props.report?.summary || {};
  const items = [
    { label: "Jumlah Pelanggan", value: nf.format(s.jml_pelanggan || 0) },
    { label: "Baru", value: nf.format(s.jml_baru || 0) },
    { label: "Setia", value: nf.format(s.jml_setia || 0) },
    { label: "Mulai Jarang", value: nf.format(s.jml_jarang || 0) },
    { label: "Hilang", value: nf.format(s.jml_hilang || 0) },
  ];
  // Hanya ditambahkan kalau server memang mengirimnya — kartu Rp 0 pada user
  // yang nilai uangnya dicabut lebih menyesatkan daripada tak ada kartu.
  if (s.total_nilai !== undefined) {
    items.push({ label: "Total Belanja", value: rp.format(s.total_nilai) });
  }
  if (s.rata_nota_semua !== undefined) {
    items.push({ label: "Rata per Nota", value: rp.format(s.rata_nota_semua) });
  }
  return items;
});

// Panel detail. Params periode/divisi ikut dikirim supaya angka di panel berasal
// dari rentang yang sama dengan tabel di belakangnya.
const dipilih = ref(null);
const detailParams = computed(() => ({
  date_mode: form.date_mode,
  date_from: form.date_from,
  date_to: form.date_to,
  date: form.date,
  kd_divisi: form.kd_divisi,
}));
</script>

<template>
  <AdminLayout title="Klasifikasi Pelanggan">
    <ReportPage
      deferred-key="report"
      :data="report"
      :columns="columns"
      row-key="kd_customer"
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
            <DateModeField
              class="sm:col-span-2"
              label="Tanggal"
              :mode="form.date_mode"
              :from="form.date_from"
              :to="form.date_to"
              :date="form.date"
              @update:mode="form.date_mode = $event"
              @update:from="form.date_from = $event"
              @update:to="form.date_to = $event"
              @update:date="form.date = $event"
            />
            <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
            <Input v-model="form.search" label="Cari" placeholder="nama pelanggan / kode" />
          </FilterSection>

          <template #lanjutan>
            <!-- Ambang segmen bisa diubah di sini: ritme belanja grosir dan
                 retail berbeda, jadi angka bawaan tak mungkin benar untuk
                 keduanya sekaligus. -->
            <FilterSection title="Aturan Segmen (hari)">
              <Input
                v-model="form.baru_hari"
                label="Baru: belanja pertama dalam"
                type="number"
                placeholder="90"
              />
              <Input
                v-model="form.jarang_hari"
                label="Mulai jarang: jeda lebih dari"
                type="number"
                placeholder="90"
              />
              <Input
                v-model="form.hilang_hari"
                label="Hilang: jeda lebih dari"
                type="number"
                placeholder="180"
              />
              <Input
                v-model="form.setia_min_nota"
                label="Setia: minimal jumlah nota"
                type="number"
                placeholder="5"
              />
            </FilterSection>
            <FilterSection title="Kelas Nilai (rata per nota)">
              <Input v-model="form.tier_besar" label="Besar: mulai dari" type="number" />
              <Input v-model="form.tier_sedang" label="Sedang: mulai dari" type="number" />
            </FilterSection>
            <FilterSection title="Pencarian Lanjutan">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['text', 'category']" />
            </FilterSection>
            <FilterSection title="Rentang Nilai">
              <ColumnFilters :filter-defs="filterDefs" :form="form" :types="['number_range']" />
            </FilterSection>
          </template>
        </FilterPanel>
      </template>

      <!-- Nama pelanggan jadi pemicu panel detail. Tombol, bukan baris yang
           bisa diklik: bisa dijangkau keyboard, dan tak merebut aksi ketika
           pengguna cuma ingin menyeleksi teks nomor HP untuk disalin. -->
      <template #cell-customer="{ row }">
        <button
          type="button"
          class="text-left text-brand-fg underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          @click="dipilih = row"
        >
          {{ row.customer || row.kd_customer }}
        </button>
      </template>

      <template #cell-segmen="{ value }">
        <Badge :variant="WARNA_SEGMEN[value] || 'neutral'">{{ value }}</Badge>
      </template>
    </ReportPage>

    <DetailPelanggan :baris="dipilih" :params="detailParams" @close="dipilih = null" />
  </AdminLayout>
</template>
