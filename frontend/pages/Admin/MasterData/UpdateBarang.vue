<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { router, Deferred } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import BarangEditModal from "@/components/master/BarangEditModal.vue";
import { useUiStore } from "@/stores/ui.js";
import { suggestFor } from "@/utils/priceSuggestion.js";

const props = defineProps({
  active: { type: Object, default: null },
  profile_type: { type: String, default: null },
  items: { type: Object, default: null },
  saran: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const data = computed(() => props.items || {});
const saranData = computed(() => props.saran || {});
const saranRows = computed(() => saranData.value.rows || []);

const isRetail = computed(() => props.profile_type === "retail");

const typeName = { gudang: "Gudang", grosir: "Grosir", retail: "Toko Retail" };

const pick = reactive({
  search: props.filters.search || "",
  status: "", // filter by status
  sort: "nama", // sort: nama, kd_barang, price
});

function reload() {
  router.get("/admin-panel/master/update-barang", { search: pick.search }, { preserveState: true, preserveScroll: true });
}

const num = (n) => (n ?? 0).toLocaleString("id-ID");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);
const tanggalJam = (iso) =>
  new Date(iso).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });

const statusLabel = (s) => ({ 0: "Non-aktif", 1: "Aktif", 2: "Tidak dijual" }[s] ?? s);
const statusVariant = (s) => ({ 0: "danger", 1: "success", 2: "warning" }[s] ?? "neutral");
const statusDotClass = (s) =>
  ({
    0: "bg-danger-bg text-danger-fg",
    1: "bg-success-bg text-success-fg",
    2: "bg-warning-bg text-warning-fg",
  })[s] ?? "bg-surface-3 text-ink-muted";

// Nama tabel teknis -> label yang dimengerti orang awam.
const statusScopes = [
  { key: "m_barang", label: "Produk (keseluruhan)", hint: "Aktif/nonaktifkan barang di semua toko & satuan." },
  { key: "m_barang_divisi", label: "Ketersediaan per Divisi/Toko", hint: "Status barang di tiap divisi." },
  { key: "m_barang_satuan", label: "Ketersediaan per Satuan", hint: "Status tiap satuan jual (pcs, dus, dll)." },
];

// Filter & sort items
const filtered = computed(() => {
  let result = data.value.rows || [];

  // Filter by status
  if (pick.status) {
    result = result.filter((i) => i.status === pick.status);
  }

  // Sort
  const sorted = [...result];
  switch (pick.sort) {
    case "kd_barang":
      sorted.sort((a, b) => a.kd_barang.localeCompare(b.kd_barang));
      break;
    case "status":
      sorted.sort((a, b) => a.status.localeCompare(b.status));
      break;
    case "price":
      sorted.sort((a, b) => {
        const pa = a.satuan[0]?.harga_jual ?? 0;
        const pb = b.satuan[0]?.harga_jual ?? 0;
        return pb - pa; // descending
      });
      break;
    case "nama":
    default:
      sorted.sort((a, b) => a.nama.localeCompare(b.nama, "id"));
  }
  return sorted;
});

// --- Infinite scroll: 25 kartu awal, +25 tiap digulirkan ke bawah ---
const CHUNK = 25;
const visibleCount = ref(CHUNK);
const visibleItems = computed(() => filtered.value.slice(0, visibleCount.value));
const hasMore = computed(() => visibleCount.value < filtered.value.length);

watch(filtered, () => {
  visibleCount.value = CHUNK;
});

const sentinel = ref(null);
let observer = null;
watch(sentinel, (el) => {
  observer?.disconnect();
  if (!el) return;
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && hasMore.value) visibleCount.value += CHUNK;
    },
    { rootMargin: "600px" },
  );
  observer.observe(el);
});
onBeforeUnmount(() => observer?.disconnect());

function margin(row) {
  const u = row.satuan[0];
  if (!u || !u.modal) return null;
  return ((u.harga_jual - u.modal) / u.modal) * 100;
}

// --- Edit modal (komponen bersama dengan halaman Pergerakan Harga) ---
const editing = ref(null);
const ui = useUiStore();

function openEdit(item) {
  editing.value = item;
}

// Saran harga (browse modal) referensi barang yang mungkin di luar kartu yang
// sedang tampil (search/filter) — ambil detail lengkap dari server dulu.
const editLoadingKd = ref(null);
async function openEditByCode(kd_barang) {
  showSuggest.value = false;
  editLoadingKd.value = kd_barang;
  try {
    const { data: res } = await axios.get("/admin-panel/master/update-barang/detail", {
      params: { kd_barang },
    });
    if (res.item) editing.value = res.item;
    else ui.pushToast(res.error || "Barang tidak ditemukan.", "error");
  } catch {
    ui.pushToast("Gagal memuat detail barang.", "error");
  } finally {
    editLoadingKd.value = null;
  }
}

// --- Saran Harga (retail): nominal dari kolom keterangan, katalog penuh ---
// Bukan tombol "terapkan" — cuma daftar untuk dibaca, penerapan harus lewat
// modal Edit Barang secara manual (lihat BarangEditModal.vue).
const showSuggest = ref(false);

// Badge per kartu: pakai data yang sudah ada di kartu (row), bukan katalog
// penuh — cukup untuk kartu yang sedang dirender.
function cardSuggestion(row) {
  return suggestFor(row);
}

// --- Riwayat (history) modal ---
const riwayat = ref(null); // { kd_barang, nama }
const riwayatLoading = ref(false);
const riwayatRows = ref([]);

const fieldLabel = {
  harga: "Harga Jual",
  status_barang: "Status Barang",
  status_divisi: "Status Divisi",
  status_satuan: "Status Satuan",
};
const fieldBadgeVariant = (f) => (f === "harga" ? "brand" : "neutral");

function formatNilai(field, v) {
  if (field === "harga") return rupiah(Number(v) || 0);
  if (field.startsWith("status_")) return statusLabel(v);
  return v;
}

async function openRiwayat(item) {
  riwayat.value = { kd_barang: item.kd_barang, nama: item.nama };
  riwayatLoading.value = true;
  riwayatRows.value = [];
  try {
    const { data: res } = await axios.get("/admin-panel/master/update-barang/riwayat", {
      params: { kd_barang: item.kd_barang },
    });
    riwayatRows.value = res.rows || [];
  } catch {
    ui.pushToast("Gagal memuat riwayat.", "error");
  } finally {
    riwayatLoading.value = false;
  }
}
</script>

<template>
  <AdminLayout title="Update Barang">
    <Card class="mb-4">
      <div class="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <span class="text-ink-muted">Database aktif:</span>
        <span class="font-semibold text-ink">{{ active?.name || "—" }}</span>
        <Badge v-if="active" variant="brand">{{ typeName[active.db_type] || active.db_type }}</Badge>
        <Badge v-if="isRetail" variant="success">Margin dihitung otomatis</Badge>
        <span class="text-xs text-ink-subtle">Ganti database lewat menu Koneksi di kanan atas.</span>
      </div>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div class="flex-1">
          <Input v-model="pick.search" label="Cari Barang" placeholder="kode / nama…" @keyup.enter="reload" />
        </div>
        <Select
          v-model="pick.status"
          label="Status"
          :options="[
            { value: '', label: 'Semua' },
            { value: '1', label: 'Aktif' },
            { value: '0', label: 'Non-aktif' },
            { value: '2', label: 'Tidak dijual' },
          ]"
          class="sm:w-40"
        />
        <Select
          v-model="pick.sort"
          label="Urutkan"
          :options="[
            { value: 'nama', label: 'Nama A-Z' },
            { value: 'kd_barang', label: 'Kode' },
            { value: 'status', label: 'Status' },
            { value: 'price', label: 'Harga (tinggi)' },
          ]"
          class="sm:w-40"
        />
        <Button variant="primary" @click="reload">Cari</Button>
        <Button v-if="isRetail" variant="yellow-outline" @click="showSuggest = true">
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
          </svg>
          Saran Harga<span v-if="saranRows.length" class="ml-1 rounded-full bg-rx-yellow px-1.5 text-[10px] font-bold text-ink">{{ saranRows.length }}</span>
        </Button>
        <span class="text-sm text-ink-muted whitespace-nowrap">{{ filtered.length }} barang</span>
      </div>
    </Card>

    <Deferred data="items">
      <template #fallback>
        <LoadingCard message="Mengambil daftar barang…" />
      </template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

      <div
        v-if="visibleItems.length > 0"
        class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      >
        <div v-for="row in visibleItems" :key="row.kd_barang" class="panel-cut-frame panel-cut-frame-accent">
          <div class="relative mecha-card panel-cut flex h-full flex-col gap-2.5 bg-surface p-3.5">
            <button
              v-if="isRetail && cardSuggestion(row)"
              type="button"
              class="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-full bg-rx-yellow px-2 py-0.5 text-[10px] font-bold text-ink shadow-sm"
              :title="`Saran harga: ${rupiah(cardSuggestion(row).harga_baru)} (sekarang ${rupiah(cardSuggestion(row).harga_lama)})`"
              @click="openEdit(row)"
            >
              ✨ Saran
            </button>

            <!-- Status trio: Barang / Divisi / Satuan -->
            <div class="flex flex-wrap items-center gap-1.5">
              <span :class="['inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold', statusDotClass(row.status)]">
                <span class="h-1.5 w-1.5 rounded-full bg-current"></span>B: {{ statusLabel(row.status) }}
              </span>
              <span :class="['inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold', statusDotClass(row.divisi[0]?.status)]">
                <span class="h-1.5 w-1.5 rounded-full bg-current"></span>D: {{ statusLabel(row.divisi[0]?.status) }}
              </span>
              <span :class="['inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold', statusDotClass(row.satuan[0]?.status)]">
                <span class="h-1.5 w-1.5 rounded-full bg-current"></span>S: {{ statusLabel(row.satuan[0]?.status) }}
              </span>
            </div>

            <span class="w-fit rounded bg-surface-3 px-2 py-1 font-mono text-[11px] font-semibold tracking-wide text-ink-muted">
              {{ row.kd_barang }}
            </span>

            <div class="min-w-0">
              <p class="line-clamp-2 font-heading text-sm font-bold leading-snug text-ink" :title="row.nama">{{ row.nama }}</p>
              <p v-if="row.keterangan" class="mt-0.5 truncate text-xs text-ink-subtle" :title="row.keterangan">
                {{ row.keterangan }}
              </p>
            </div>

            <div v-if="row.kategori || row.divisi[0]?.nama" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-muted">
              <span v-if="row.kategori" class="inline-flex items-center gap-1">
                <svg class="h-3 w-3 text-rx-red" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6z" />
                </svg>
                {{ row.kategori }}
              </span>
              <span v-if="row.divisi[0]?.nama" class="inline-flex items-center gap-1">
                <svg class="h-3 w-3 text-rx-yellow" fill="currentColor" viewBox="0 0 24 24" stroke="none">
                  <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                </svg>
                {{ row.divisi[0].nama }}
              </span>
            </div>

            <div class="mt-auto border-t border-border-default pt-2.5">
              <div class="flex items-baseline justify-between gap-2">
                <p class="flex items-baseline gap-1">
                  <span class="font-heading text-xl font-bold tabular-nums text-brand-700">
                    {{ row.satuan.length > 0 ? rupiah(row.satuan[0].harga_jual) : "—" }}
                  </span>
                  <span v-if="row.satuan.length > 0" class="text-xs font-medium text-ink-subtle">/{{ row.satuan[0].satuan || row.satuan[0].kd_satuan }}</span>
                </p>
                <span
                  v-if="isRetail && margin(row) !== null"
                  :class="['shrink-0 text-xs font-semibold', margin(row) < 0 ? 'text-danger-600' : 'text-success-700']"
                >
                  {{ margin(row).toFixed(1) }}%
                </span>
              </div>

              <div v-if="row.satuan.length > 0" class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div>
                  <p class="text-[9px] font-bold uppercase tracking-wide text-ink-subtle">Satuan</p>
                  <p class="font-semibold text-ink">{{ row.satuan[0].satuan || "—" }}</p>
                </div>
                <div>
                  <p class="text-[9px] font-bold uppercase tracking-wide text-ink-subtle">Jumlah/Satuan</p>
                  <p class="font-semibold text-ink">{{ num(row.satuan[0].jumlah) }}</p>
                </div>
              </div>
              <div v-if="row.satuan.length > 0" class="mt-1.5">
                <p class="text-[9px] font-bold uppercase tracking-wide text-ink-subtle">Kode Satuan</p>
                <p class="font-mono text-xs font-semibold text-ink">{{ row.satuan[0].kd_satuan }}</p>
              </div>
              <p v-if="row.satuan.length > 1" class="mt-1 text-[10px] text-ink-subtle">+{{ row.satuan.length - 1 }} satuan lain</p>
            </div>

            <div class="flex gap-1.5">
              <Button size="sm" variant="yellow-outline" class="flex-1" @click="openEdit(row)">
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 13.5v4.75A2.25 2.25 0 0117.25 20.5H5.75A2.25 2.25 0 013.5 18.25V6.75A2.25 2.25 0 015.75 4.5h4.75" />
                </svg>
                Edit Barang
              </Button>
              <Button size="sm" variant="ghost" class="shrink-0 px-2.5" title="Riwayat perubahan" @click="openRiwayat(row)">
                <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z" />
                </svg>
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="!data.conn_error" class="rounded-card border border-dashed border-border-default bg-surface-2 py-12 text-center">
        <p class="text-sm text-ink-muted">Tidak ada barang.</p>
      </div>

      <div v-if="hasMore" ref="sentinel" class="flex items-center justify-center gap-2 py-6 text-sm text-ink-muted">
        <Spinner size="h-4 w-4" />
        Memuat lebih banyak…
      </div>
    </Deferred>

    <BarangEditModal :item="editing" :is-retail="isRetail" @close="editing = null" />

    <Modal :show="!!riwayat" :title="riwayat ? `Riwayat — ${riwayat.kd_barang} ${riwayat.nama}` : ''" size="md" @close="riwayat = null">
      <div v-if="riwayatLoading" class="flex items-center justify-center gap-3 py-10">
        <Spinner />
        <span class="text-sm text-ink-muted">Memuat riwayat…</span>
      </div>
      <div v-else-if="riwayatRows.length" class="max-h-[60vh] space-y-1.5 overflow-y-auto scroll-slim">
        <div
          v-for="(r, i) in riwayatRows"
          :key="i"
          class="rounded border border-border-default bg-surface-2 px-3 py-2"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="flex items-center gap-1.5">
              <Badge :variant="fieldBadgeVariant(r.field)">{{ r.field_label }}</Badge>
              <span v-if="r.kd_ref" class="text-[10px] font-mono text-ink-subtle">{{ r.kd_ref }}</span>
            </span>
            <span class="text-[11px] text-ink-subtle">{{ tanggalJam(r.created_at) }}</span>
          </div>
          <div class="mt-1 flex items-center gap-1.5 text-sm">
            <span class="text-ink-muted line-through decoration-danger-500/60">{{ formatNilai(r.field, r.nilai_lama) }}</span>
            <span class="text-ink-subtle">→</span>
            <span class="font-semibold text-ink">{{ formatNilai(r.field, r.nilai_baru) }}</span>
          </div>
          <p v-if="r.username" class="mt-0.5 text-[10px] text-ink-subtle">oleh {{ r.username }}</p>
        </div>
      </div>
      <p v-else class="py-8 text-center text-sm text-ink-muted">Belum ada riwayat perubahan untuk barang ini.</p>
      <template #footer>
        <Button variant="ghost" @click="riwayat = null">Tutup</Button>
      </template>
    </Modal>

    <!-- Saran Harga (retail) — daftar baca-saja, katalog penuh. Prioritas: -->
    <!-- keterangan yang eksplisit sebut %/margin duluan (lihat backend). -->
    <!-- Tidak ada tombol terapkan — ubah harga lewat Edit Barang secara manual. -->
    <Modal :show="showSuggest" title="Saran Harga dari Keterangan" size="lg" @close="showSuggest = false">
      <div v-if="!props.saran" class="flex items-center justify-center gap-3 py-10">
        <Spinner />
        <span class="text-sm text-ink-muted">Memuat saran harga…</span>
      </div>
      <Banner v-else-if="saranData.conn_error" variant="warning" :message="saranData.conn_error" />
      <div v-else-if="saranRows.length" class="space-y-3">
        <Banner
          variant="info"
          message="Harga saran diambil dari nominal di kolom keterangan tiap barang, diurutkan barang dengan %/margin eksplisit duluan. Ubah harga lewat Edit Barang secara manual."
        />
        <div class="max-h-[55vh] overflow-y-auto scroll-slim">
          <table class="w-full text-sm">
            <thead class="sticky top-0 bg-surface">
              <tr class="text-left text-ink-muted">
                <th class="py-1.5">Barang</th>
                <th class="py-1.5">Keterangan</th>
                <th class="py-1.5 text-right">Sekarang</th>
                <th class="py-1.5 text-right">Saran</th>
                <th class="py-1.5 text-right">Selisih</th>
                <th class="py-1.5"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in saranRows" :key="s.kd_barang + s.kd_satuan" class="border-t border-border-default">
                <td class="py-1.5">
                  <p class="font-mono text-[11px] text-ink-muted">{{ s.kd_barang }} · {{ s.satuan }}</p>
                  <p class="font-medium text-ink">{{ s.nama }}</p>
                </td>
                <td class="py-1.5 max-w-[14rem] truncate text-xs text-ink-subtle" :title="s.keterangan">{{ s.keterangan }}</td>
                <td class="py-1.5 text-right text-ink-muted tabular-nums">{{ rupiah(s.harga_lama) }}</td>
                <td class="py-1.5 text-right font-semibold text-ink tabular-nums">{{ rupiah(s.harga_baru) }}</td>
                <td :class="['py-1.5 text-right font-medium tabular-nums', s.selisih < 0 ? 'text-danger-600' : 'text-success-700']">
                  {{ s.selisih > 0 ? "+" : "" }}{{ rupiah(s.selisih) }}
                </td>
                <td class="py-1.5 text-right">
                  <Button size="sm" variant="yellow-outline" :loading="editLoadingKd === s.kd_barang" @click="openEditByCode(s.kd_barang)">
                    Edit
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p v-else class="py-8 text-center text-sm text-ink-muted">
        Semua harga sudah sesuai nominal di keterangan — tidak ada saran perubahan.
      </p>
      <template #footer>
        <Button variant="ghost" @click="showSuggest = false">Tutup</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
