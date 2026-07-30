<script setup>
/**
 * Klasifikasi Pelanggan — kolumnar, dicari di peramban.
 *
 * Pekerjaan nyata di halaman ini adalah MENCARI orang: "yang sudah lama tak
 * datang", "yang di Lombok Timur", "yang belanjanya besar". Di tabel yang
 * dipaginasi server tiap pertanyaan itu satu putaran ke server; di sini semua
 * pelanggan dikirim sekali lalu disaring lokal. Payload-nya kolom-mayor dan
 * TIDAK pernah masuk reaktivitas Vue — lihat useColumnarTable.js.
 *
 * Yang tetap ke server: periode, divisi, dan ambang segmen. Ketiganya mengubah
 * angka yang dihitung SQL, bukan cuma baris mana yang tampil, jadi menekan
 * "Tampilkan" memang harus memuat ulang.
 */
import { computed, ref, watch } from "vue";
import AdminLayout from "@/layouts/AdminLayout.vue";
import BaseTable from "@/components/ui/BaseTable.vue";
import DetailPelanggan from "@/components/report/DetailPelanggan.vue";
import Banner from "@/components/ui/Banner.vue";
import Badge from "@/components/ui/Badge.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Button from "@/components/ui/Button.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import DateModeField from "@/components/ui/DateModeField.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import TableSkeleton from "@/components/ui/TableSkeleton.vue";
import ExportButton from "@/components/ui/ExportButton.vue";
import { Deferred } from "@inertiajs/vue3";
import { useColumnarTable } from "@/composables/useColumnarTable";
import { useHiddenData } from "@/composables/useHiddenData.js";
import { useReportFilters } from "@/composables/useReportFilters.js";

const props = defineProps({
  klasifikasi: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/analitik/klasifikasi-pelanggan";

const connError = computed(() => props.klasifikasi?.conn_error ?? null);
const notice = computed(() => props.klasifikasi?.notice ?? null);

const {
  ingest, dictOptions, sumOf, countBy,
  searchInput, search, sortKey, sortDir, page, perPage, equals,
  total, n, pageRows, setSort, setPerPage, setEquals, resetFilters,
} = useColumnarTable(() => props.klasifikasi?.tabel, {
  searchKeys: ["kd_customer", "customer", "kota", "hp"],
  defaultSort: "segmen_urut",
  defaultSortDir: "asc",
});

watch(() => props.klasifikasi?.tabel, (payload) => ingest(payload), { immediate: true });

// Hanya periode/divisi/ambang yang perlu ke server; sisanya disaring di klien.
const AMBANG = ["baru_hari", "jarang_hari", "hilang_hari", "setia_min_nota",
                "tier_besar", "tier_sedang"];
const { filters: pull, loading: pulling, apply: tarikData } = useReportFilters(
  URL,
  {
    date_mode: props.filters.date_mode || "range",
    date_from: props.filters.date_from || "",
    date_to: props.filters.date_to || "",
    date: props.filters.date || "",
    kd_divisi: props.filters.kd_divisi || "",
    ...Object.fromEntries(AMBANG.map((k) => [k, props.filters[k] ?? ""])),
  },
);

const divisiOptions = computed(() => props.klasifikasi?.options?.divisi || []);
const segmenOptions = computed(() => dictOptions("segmen"));
const tierOptions = computed(() => dictOptions("tier_nilai"));
const kotaOptions = computed(() => dictOptions("kota"));

// Kolom uang dirapikan dari layar; datanya sendiri memang sudah tak ada di
// payload (_tanpa_kolom di views.py). Tanpa ini yang muncul deretan sel "-".
const { bisaLihat, saringKolom } = useHiddenData();
const KOLOM_UANG = { total_belanja: "nominal", rata_nota: "nominal", tier_nilai: "nominal" };

const SEMUA_KOLOM = [
  { key: "customer", label: "Pelanggan", sortable: true },
  // Kunci sengaja `segmen_urut` (angka urgensi) walau labelnya "Segmen":
  // mengurut teksnya menaruh 'Aktif' sebelum 'Hilang' secara abjad, membuang
  // yang paling perlu dihubungi ke halaman terakhir. Selnya tetap menampilkan
  // nama segmen lewat slot di bawah.
  { key: "segmen_urut", label: "Segmen", sortable: true },
  { key: "hp", label: "HP" },
  { key: "kota", label: "Kota", sortable: true },
  { key: "jml_nota", label: "Jml Nota", align: "right", format: "number", sortable: true },
  { key: "total_belanja", label: "Total Belanja", align: "right", format: "rupiah", sortable: true },
  { key: "rata_nota", label: "Rata per Nota", align: "right", format: "rupiah", sortable: true },
  { key: "tier_nilai", label: "Kelas Nilai" },
  { key: "nota_terakhir", label: "Belanja Terakhir", sortable: true },
  { key: "jeda_hari", label: "Jeda (hari)", align: "right", format: "number", sortable: true },
  { key: "nota_pertama", label: "Belanja Pertama", sortable: true },
  { key: "umur_hari", label: "Lama Jadi Pelanggan", align: "right", format: "number", sortable: true },
];
const columns = computed(() => saringKolom(SEMUA_KOLOM, KOLOM_UANG));

const WARNA_SEGMEN = {
  Hilang: "danger",
  "Mulai Jarang": "warning",
  Baru: "brand",
  Setia: "success",
  Aktif: "neutral",
};

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});

// Ringkasan dihitung atas hasil saringan KLIEN, langsung dari kolomnya — jadi
// menyaring satu kota langsung memperbarui hitungan tiap segmen.
const summaryItems = computed(() => {
  const per = countBy("segmen");
  const items = [
    { label: "Pelanggan", value: `${nf.format(total.value)} dari ${nf.format(n.value)}` },
    { label: "Baru", value: nf.format(per.Baru || 0) },
    { label: "Setia", value: nf.format(per.Setia || 0) },
    { label: "Mulai Jarang", value: nf.format(per["Mulai Jarang"] || 0) },
    { label: "Hilang", value: nf.format(per.Hilang || 0) },
  ];
  if (bisaLihat("nominal")) {
    const totalBelanja = sumOf("total_belanja");
    const totalNota = sumOf("jml_nota");
    items.push({ label: "Total Belanja", value: rp.format(totalBelanja) });
    items.push({
      label: "Rata per Nota",
      value: rp.format(totalNota ? totalBelanja / totalNota : 0),
    });
  }
  return items;
});

// Ada DUA reset di halaman ini dan keduanya harus jelas miliknya masing-masing.
// Tombol Reset di panel filter berada tepat di samping "Tampilkan", jadi ia
// harus mengembalikan yang dikirim ke server (periode/divisi/ambang) — bukan
// saringan klien di bawah tabel, yang punya tombol "Bersihkan" sendiri.
// Sebelum ini keduanya memanggil fungsi yang sama, sehingga menekan Reset di
// atas tak mengubah apa pun yang terlihat.
function resetServer() {
  for (const k of Object.keys(pull)) pull[k] = k === "date_mode" ? "range" : "";
  // Query kosong, bukan hasil pull: server yang menetapkan periode 730 hari dan
  // ambang bawaannya, lalu mengirimnya balik terisi lewat `filters`.
  tarikData();
}

// Export HARUS ikut saringan klien, bukan hanya periode/ambang. Tanpa ini
// seseorang menyaring "Hilang di Lombok Timur", menekan Export, lalu mendapat
// seluruh 316 pelanggan — file yang salah tanpa satu pun tanda di layar.
// Saringan klien diterjemahkan ke parameter yang sudah dimengerti server
// (FILTERS_KLASIFIKASI_PELANGGAN), jadi SQL-nya yang menyaring ulang.
const exportHref = computed(() => {
  const q = { ...pull };
  if (search.value.trim()) q.search = search.value.trim();
  if (equals.value.segmen) q.f_segmen = equals.value.segmen;
  if (equals.value.tier_nilai) q.f_tier_nilai = equals.value.tier_nilai;
  if (equals.value.kota) q.f_kota = equals.value.kota;
  const bersih = Object.fromEntries(
    Object.entries(q).filter(([, v]) => v !== "" && v != null),
  );
  return `${URL}/export?` + new URLSearchParams(bersih).toString();
});

const dipilih = ref(null);
const detailParams = computed(() => ({
  date_mode: pull.date_mode,
  date_from: pull.date_from,
  date_to: pull.date_to,
  date: pull.date,
  kd_divisi: pull.kd_divisi,
}));
</script>

<template>
  <AdminLayout title="Klasifikasi Pelanggan">
    <!-- Panel filter di luar <Deferred> supaya bisa dipakai sebelum data datang -->
    <FilterPanel :form="pull" :loading="pulling" @submit="tarikData" @reset="resetServer">
      <FilterSection title="Periode & Divisi">
        <DateModeField
          class="sm:col-span-2"
          label="Tanggal"
          :mode="pull.date_mode"
          :from="pull.date_from"
          :to="pull.date_to"
          :date="pull.date"
          @update:mode="pull.date_mode = $event"
          @update:from="pull.date_from = $event"
          @update:to="pull.date_to = $event"
          @update:date="pull.date = $event"
        />
        <SelectSearch v-model="pull.kd_divisi" :options="divisiOptions" label="Divisi" />
      </FilterSection>
      <template #lanjutan>
        <!-- Ambang ini bagian dari perhitungan SQL, jadi mengubahnya perlu
             menekan Tampilkan — beda dari saringan di bawah tabel yang instan. -->
        <FilterSection title="Aturan Segmen (hari) — perlu Tampilkan">
          <Input v-model="pull.baru_hari" label="Baru: belanja pertama dalam" type="number" />
          <Input v-model="pull.jarang_hari" label="Mulai jarang: jeda lebih dari" type="number" />
          <Input v-model="pull.hilang_hari" label="Hilang: jeda lebih dari" type="number" />
          <Input v-model="pull.setia_min_nota" label="Setia: minimal jumlah nota" type="number" />
        </FilterSection>
        <FilterSection title="Kelas Nilai (rata per nota) — perlu Tampilkan">
          <Input v-model="pull.tier_besar" label="Besar: mulai dari" type="number" />
          <Input v-model="pull.tier_sedang" label="Sedang: mulai dari" type="number" />
        </FilterSection>
      </template>
    </FilterPanel>

    <Deferred data="klasifikasi">
      <template #fallback><TableSkeleton /></template>

      <Banner v-if="connError" variant="warning" :message="connError" />
      <Banner v-if="notice" variant="info" :message="notice" />

      <SummaryStrip :items="summaryItems" />

      <!-- Saringan di sini seketika: tak ada permintaan ke server sama sekali. -->
      <Card class="mb-3">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input
            v-model="searchInput"
            label="Cari pelanggan"
            placeholder="nama / kode / kota / HP…"
          />
          <Select
            :model-value="equals.segmen || ''"
            :options="segmenOptions"
            label="Segmen"
            placeholder="Semua"
            @update:model-value="setEquals('segmen', $event)"
          />
          <Select
            :model-value="equals.tier_nilai || ''"
            :options="tierOptions"
            label="Kelas Nilai"
            placeholder="Semua"
            @update:model-value="setEquals('tier_nilai', $event)"
          />
          <SelectSearch
            :model-value="equals.kota || ''"
            :options="kotaOptions"
            label="Kota"
            @update:model-value="setEquals('kota', $event)"
          />
          <div class="flex items-end gap-2">
            <Button variant="ghost" @click="resetFilters">Bersihkan</Button>
            <ExportButton mode="server" :href="exportHref" />
          </div>
        </div>
      </Card>

      <BaseTable
        :columns="columns"
        :rows="pageRows"
        row-key="kd_customer"
        :total="total"
        :page="page"
        :per-page="perPage"
        :sort-key="sortKey"
        :sort-dir="sortDir"
        empty-message="Tidak ada pelanggan yang cocok dengan saringan ini."
        @page-change="page = $event"
        @sort-change="setSort"
        @per-page-change="setPerPage"
      >
        <!-- Nama jadi tombol pembuka panel detail, bukan seluruh baris:
             bisa dijangkau keyboard, dan tak merebut aksi saat orang cuma
             ingin menyeleksi nomor HP untuk disalin. -->
        <template #cell-customer="{ row }">
          <button
            type="button"
            class="text-left text-brand-fg underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            @click="dipilih = row"
          >
            {{ row.customer || row.kd_customer }}
          </button>
        </template>

        <template #cell-segmen_urut="{ row }">
          <Badge :variant="WARNA_SEGMEN[row.segmen] || 'neutral'">{{ row.segmen }}</Badge>
        </template>
      </BaseTable>
    </Deferred>

    <DetailPelanggan :baris="dipilih" :params="detailParams" @close="dipilih = null" />
  </AdminLayout>
</template>
