<script setup>
/**
 * Audit Harga Beli — pembelian toko vs pembelian gudang.
 *
 * Sinkronisasi legacy menerbitkan pembelian di toko dengan harga_beli diisi
 * HARGA JUAL gudang; admin selama ini mengoreksinya manual satu per satu.
 * Halaman ini menemukan yang terlewat dan mengusulkan penggantinya.
 *
 * Kolom "dasar usulan" sengaja ditampilkan: admin harus bisa memeriksa dari nota
 * gudang mana angka itu berasal, bukan disuruh percaya.
 */
import { computed, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import DateRangeFilter from "@/components/report/DateRangeFilter.vue";
import { useReportFilters } from "@/composables/useReportFilters";
import { downloadXlsx, stamp } from "@/utils/xlsx";

const props = defineProps({
  audit: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  profil_aktif: { type: String, default: "" },
});

const data = computed(() => props.audit || {});
const rows = computed(() => data.value.rows || []);

const { filters: form, loading, apply: tampilkan } = useReportFilters(
  "/admin-panel/master/audit-harga-beli",
  { date_from: props.filters.date_from || "", date_to: props.filters.date_to || "" },
);

// --- seleksi ---------------------------------------------------------------
// Kunci baris harus persis kunci yang dipakai backend untuk UPDATE, kalau tidak
// baris yang dicentang dan baris yang ditulis bisa berbeda.
const rowId = (r) => `${r.no_transaksi}|${r.kd_barang}|${r.kd_satuan}|${r.jenis}`;
const dipilih = ref(new Set());

const semuaDipilih = computed(
  () => rows.value.length > 0 && rows.value.every((r) => dipilih.value.has(rowId(r))),
);

function toggle(r) {
  const s = new Set(dipilih.value);
  const id = rowId(r);
  s.has(id) ? s.delete(id) : s.add(id);
  dipilih.value = s;
}

function toggleSemua() {
  dipilih.value = semuaDipilih.value ? new Set() : new Set(rows.value.map(rowId));
}

const terpilih = computed(() => rows.value.filter((r) => dipilih.value.has(rowId(r))));

// --- terapkan --------------------------------------------------------------
const konfirmasi = ref(false);

function terapkan() {
  if (!terpilih.value.length) return;
  router.post(
    "/admin-panel/master/audit-harga-beli/terapkan",
    { items: terpilih.value },
    {
      preserveScroll: true,
      onFinish: () => {
        dipilih.value = new Set();
        konfirmasi.value = false;
      },
    },
  );
}

const columns = [
  { key: "pilih", label: "", sortable: false, align: "center" },
  { key: "no_transaksi", label: "Nota Toko", sortable: true },
  { key: "tanggal", label: "Tanggal", sortable: true },
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "barang", label: "Barang", sortable: true },
  { key: "qty", label: "Qty", sortable: true, align: "right" },
  { key: "harga_tercatat", label: "Harga Tercatat", sortable: true, align: "right" },
  { key: "harga_usulan", label: "Harga Usulan", sortable: true, align: "right" },
  { key: "selisih", label: "Selisih", sortable: true, align: "right" },
  { key: "dasar_nota", label: "Dasar Usulan", sortable: false },
  { key: "status", label: "Status", sortable: true },
];

const rp = (v) => (v ?? 0).toLocaleString("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (v) => (v ?? 0).toLocaleString("id-ID");

function ekspor() {
  downloadXlsx(
    rows.value.map((r) => ({
      Nota: r.no_transaksi, Tanggal: r.tanggal, Kode: r.kd_barang, Barang: r.barang,
      Qty: r.qty, "Harga Tercatat": r.harga_tercatat, "Harga Usulan": r.harga_usulan,
      Selisih: r.selisih, "Nota Gudang": r.dasar_nota, "Tanggal Gudang": r.dasar_tanggal,
      Status: r.status === "nol" ? "Harga nol" : "Masih harga jual gudang",
    })),
    `audit-harga-beli-${stamp()}`,
  );
}
</script>

<template>
  <AdminLayout title="Audit Harga Beli">
    <Card class="mb-6">
      <DateRangeFilter
        mode="range"
        :filters="form"
        :loading="loading"
        :inline-submit="false"
        submit-label="Tampilkan"
        @submit="tampilkan()"
      />
      <p class="mt-3 text-xs text-ink-subtle">
        Membandingkan pembelian di <strong>{{ profil_aktif || "koneksi aktif" }}</strong> dengan
        pembelian di server gudang acuannya. Hanya baris yang perlu tindakan yang ditampilkan.
      </p>
    </Card>

    <Deferred data="audit">
      <template #fallback>
        <LoadingCard message="Membandingkan harga beli dengan gudang…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

      <Banner
        v-else-if="data.perlu_cost_source"
        variant="warning"
        message="Koneksi aktif ini belum punya server gudang acuan. Atur 'Sumber Modal' di menu Koneksi Server, lalu buka halaman ini lagi."
      />

      <template v-else>
        <Banner
          v-if="data.terpotong"
          variant="warning"
          message="Temuan melebihi batas tampil. Persempit rentang tanggal supaya tak ada yang tertinggal di luar daftar."
        />

        <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Card>
            <p class="text-xs text-ink-muted">Masih Harga Jual Gudang</p>
            <p class="text-lg font-semibold">{{ num(data.ringkas?.harga_jual) }}</p>
          </Card>
          <Card>
            <p class="text-xs text-ink-muted">Harga Nol</p>
            <p class="text-lg font-semibold">{{ num(data.ringkas?.nol) }}</p>
          </Card>
          <Card>
            <p class="text-xs text-ink-muted">Gudang Acuan</p>
            <p class="text-lg font-semibold">{{ data.gudang || "—" }}</p>
          </Card>
        </div>

        <!-- Tak bisa ditindak tapi tak boleh disembunyikan: baris ini terdeteksi
             bermasalah, cuma tak punya pembanding di gudang untuk diusulkan. -->
        <Banner
          v-if="data.ringkas?.tanpa_pembanding"
          variant="info"
          :message="`${num(data.ringkas.tanpa_pembanding)} baris bermasalah tak bisa diusulkan koreksinya karena barangnya tak pernah dibeli gudang. Perlu diperiksa manual — tidak muncul di daftar bawah.`"
          class="mb-4"
        />

        <Card v-if="rows.length === 0">
          <p class="text-sm text-ink-muted">
            Tidak ada baris yang perlu dikoreksi pada rentang ini. Harga beli sudah sesuai pembelian gudang.
          </p>
        </Card>

        <template v-else>
          <div class="mb-4 flex flex-wrap items-center gap-3">
            <Button variant="secondary" @click="toggleSemua">
              {{ semuaDipilih ? "Batalkan Semua" : "Pilih Semua" }}
            </Button>
            <Button variant="secondary" @click="ekspor">Ekspor Excel</Button>
            <span class="text-sm text-ink-muted">{{ num(terpilih.length) }} baris dipilih</span>

            <div class="ms-auto flex items-center gap-3">
              <!-- Tombol mati di server selain database uji. Penjaganya ada di
                   backend juga: mematikan tombol saja tak cukup. -->
              <span v-if="!data.boleh_tulis" class="text-xs text-ink-subtle">
                Koreksi hanya bisa diterapkan pada database uji.
              </span>
              <Button
                v-else-if="!konfirmasi"
                :disabled="terpilih.length === 0"
                @click="konfirmasi = true"
              >
                Terapkan Koreksi…
              </Button>
              <template v-else>
                <span class="text-sm">Tulis {{ num(terpilih.length) }} baris ke {{ profil_aktif }}?</span>
                <Button variant="secondary" @click="konfirmasi = false">Batal</Button>
                <Button @click="terapkan">Ya, Terapkan</Button>
              </template>
            </div>
          </div>

          <DataTable :columns="columns" :rows="rows" :row-key="'no_transaksi'">
            <template #cell-pilih="{ row }">
              <input
                type="checkbox"
                class="size-4 accent-brand-600"
                :checked="dipilih.has(rowId(row))"
                :aria-label="`Pilih ${row.kd_barang} pada nota ${row.no_transaksi}`"
                @change="toggle(row)"
              />
            </template>
            <template #cell-qty="{ row }">{{ num(row.qty) }}</template>
            <template #cell-harga_tercatat="{ row }">{{ rp(row.harga_tercatat) }}</template>
            <template #cell-harga_usulan="{ row }">{{ rp(row.harga_usulan) }}</template>
            <template #cell-selisih="{ row }">
              <span :class="row.selisih < 0 ? 'text-danger-600' : 'text-success-700'">{{ rp(row.selisih) }}</span>
            </template>
            <template #cell-dasar_nota="{ row }">
              <span class="text-xs">{{ row.dasar_nota }}<br />{{ row.dasar_tanggal }}</span>
            </template>
            <template #cell-status="{ row }">
              <Badge :variant="row.status === 'nol' ? 'danger' : 'warning'">
                {{ row.status === "nol" ? "Harga nol" : "Masih harga jual" }}
              </Badge>
            </template>
          </DataTable>
        </template>
      </template>
    </Deferred>
  </AdminLayout>
</template>
