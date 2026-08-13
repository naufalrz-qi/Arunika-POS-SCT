<script setup>
import { computed, ref } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Banner from "@/components/ui/Banner.vue";
import SummaryStrip from "@/components/ui/SummaryStrip.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import FilterSection from "@/components/ui/FilterSection.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";
import Input from "@/components/ui/Input.vue";
import ExportButton from "@/components/ui/ExportButton.vue";

const props = defineProps({
  laporan: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const URL = "/admin-panel/laporan/laba-rugi";
const data = computed(() => props.laporan || {});

const form = ref({
  date_from: props.filters.date_from || "",
  date_to: props.filters.date_to || "",
  kd_divisi: props.filters.kd_divisi || "",
});

function terapkan() {
  router.get(URL, { ...form.value }, { preserveState: true, preserveScroll: true });
}
function reset() {
  form.value = { date_from: "", date_to: "", kd_divisi: "" };
  terapkan();
}

const exportHref = computed(() => {
  const q = new URLSearchParams(
    Object.entries(form.value).filter(([, v]) => v),
  ).toString();
  return `${URL}/export${q ? `?${q}` : ""}`;
});

const divisiOptions = computed(() => data.value.divisi || []);
const baris = computed(() => data.value.baris || []);
const memo = computed(() => data.value.memo || []);
const info = computed(() => data.value.info || {});

const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const nf = new Intl.NumberFormat("id-ID");

// Konvensi akuntansi: nilai negatif dalam kurung, bukan tanda minus. Baris
// pengurang (retur, potongan, persediaan akhir, biaya) memang dikirim negatif
// supaya kolomnya benar-benar menjumlah ke subtotalnya.
function uang(v) {
  const n = Number(v) || 0;
  return n < 0 ? `(${rp.format(Math.abs(n))})` : rp.format(n);
}
function nilai(b) {
  return b.jenis === "persen" ? `${nf.format(b.nilai)}%` : uang(b.nilai);
}

const ambil = (label) => baris.value.find((b) => b.label === label)?.nilai ?? 0;
const summaryItems = computed(() => [
  { label: "Penjualan Bersih", value: rp.format(ambil("Penjualan Bersih")) },
  { label: "Harga Pokok Penjualan", value: rp.format(ambil("Harga Pokok Penjualan")) },
  { label: "Laba Kotor", value: rp.format(ambil("Laba Kotor")) },
  { label: "Laba Bersih", value: rp.format(ambil("Laba Bersih")) },
]);

const KELAS = {
  subtotal: "border-t border-line font-medium",
  total: "border-t-2 border-line text-base font-semibold",
  persen: "text-ink-muted",
};
</script>

<template>
  <AdminLayout title="Laba Rugi">
    <FilterPanel :form="form" @submit="terapkan" @reset="reset">
      <FilterSection title="Periode">
        <Input v-model="form.date_from" label="Dari Tanggal" type="date" />
        <Input v-model="form.date_to" label="Sampai Tanggal" type="date" />
        <SelectSearch v-model="form.kd_divisi" :options="divisiOptions" label="Divisi" />
      </FilterSection>
    </FilterPanel>

    <Deferred data="laporan">
      <template #fallback><LoadingCard message="Menyusun laba rugi…" /></template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />
      <Banner v-else-if="data.ditolak" variant="warning" :message="data.ditolak" />

      <template v-else>
        <Banner v-if="data.notice" variant="info" :message="data.notice" />
        <!-- Wajib ada dan permanen: pembaca yang membandingkan dengan aplikasi
             lama HARUS tahu selisihnya disengaja, bukan salah hitung. -->
        <Banner
          variant="info"
          message="Persediaan dinilai dengan rata-rata tertimbang (PSAK 14). Aplikasi lama memakai metode LIFO yang sudah tidak diperkenankan, jadi angka di sini memang tidak akan sama persis dengan laporan lamanya."
        />

        <SummaryStrip :items="summaryItems" />

        <div class="surface-flat mt-4 overflow-x-auto">
          <table class="w-full min-w-[28rem] text-sm">
            <tbody>
              <tr v-for="(b, i) in baris" :key="i" :class="KELAS[b.jenis]">
                <template v-if="b.jenis === 'pemisah'">
                  <td class="py-2" colspan="2"></td>
                </template>
                <template v-else>
                  <td class="px-4 py-1.5 text-ink">{{ b.label }}</td>
                  <td class="px-4 py-1.5 text-right tabular-nums text-ink">{{ nilai(b) }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start">
          <div class="surface-flat flex-1 overflow-x-auto">
            <p class="px-4 pt-3 text-xs font-medium text-ink-muted">Memo</p>
            <table class="w-full min-w-[24rem] text-sm">
              <tbody>
                <tr v-for="(b, i) in memo" :key="i">
                  <td class="px-4 py-1.5 text-ink">{{ b.label }}</td>
                  <td class="px-4 py-1.5 text-right tabular-nums text-ink">{{ uang(b.nilai) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="surface-flat flex-1 px-4 py-3 text-xs text-ink-muted">
            <p class="mb-1 font-medium text-ink-muted">Dasar penilaian persediaan</p>
            <p>{{ nf.format(info.barang_akhir || 0) }} barang bersaldo · {{ nf.format(info.unit_akhir || 0) }} unit.</p>
            <!-- Diberitahukan, bukan disembunyikan: keduanya menekan nilai
                 persediaan dan pembaca berhak tahu seberapa besar. -->
            <p v-if="info.tanpa_harga">
              {{ nf.format(info.tanpa_harga) }} barang tidak punya dasar harga perolehan
              (tanpa saldo awal maupun pembelian sejak tutup buku) sehingga dinilai Rp 0.
            </p>
            <p v-if="info.stok_negatif">
              {{ nf.format(info.stok_negatif) }} barang bersaldo negatif — cacat data, bukan
              keadaan fisik; tetap ikut dinilai agar laporan menjumlah.
            </p>
          </div>
        </div>

        <div class="mt-3 flex justify-end">
          <ExportButton mode="server" :href="exportHref" />
        </div>
      </template>
    </Deferred>
  </AdminLayout>
</template>
