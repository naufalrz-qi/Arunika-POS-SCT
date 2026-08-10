<script setup>
/**
 * Tampilan tabel — satu-satunya. Tidak tahu-menahu soal dari mana baris datang.
 *
 * Sebelum ini ada dua salinan yang ~80% identik: DataTable (urut/paginasi di
 * peramban) dan ServerTable (di server). Keduanya sudah menyimpang diam-diam —
 * pilihan per-halaman 25/50/100 lawan 25/50/100/200/500/1000, format `persen`
 * dan `date` hanya ada di satu sisi, sel kosong dirender "" lawan "-", latar
 * thead bg-surface-2 lawan bg-surface-3, pemisah baris divide-y lawan border-t.
 * Pengguna yang pindah dari Log Aktivitas ke Laporan Penjualan melihat dua
 * tabel yang seharusnya sama tapi terasa beda.
 *
 * Semua state di sini terkendali (controlled): pengurutan dan paginasi
 * dilaporkan lewat event, pemanggilnya yang memutuskan cara mengerjakannya.
 * Yang dimiliki sendiri hanya visibilitas kolom, karena itu murni preferensi
 * tampilan.
 */
import { computed, ref, watch } from "vue";
import { usePage } from "@inertiajs/vue3";
import { useDismissable } from "@/composables/useDismissable";
import Spinner from "./Spinner.vue";
import EmptyState from "./EmptyState.vue";
import Pagination from "./Pagination.vue";

const props = defineProps({
  // columns: [{ key, label, sortable?, align?: 'left'|'right'|'center',
  //             format?: 'number'|'rupiah'|'persen'|'date' }]
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: "id" },
  loading: { type: Boolean, default: false },
  // Jumlah seluruh baris (server) — untuk tabel sisi-peramban sama dengan
  // panjang baris yang sudah tersaring.
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  perPageOptions: { type: Array, default: () => [25, 50, 100, 200, 500, 1000] },
  sortKey: { type: String, default: "" },
  sortDir: { type: String, default: "desc" },
  emptyMessage: { type: String, default: "Tidak ada data untuk filter yang dipilih." },
});
const emit = defineEmits(["page-change", "sort-change", "per-page-change"]);

const { open: columnMenuOpen, root: columnMenuRoot, toggle: toggleColumnMenu } = useDismissable();

// Pilihan kolom disimpan per halaman. Tanpa ini pilihannya hilang tiap kali
// pengguna berpindah menu, dan di tabel 25 kolom seperti Penjualan Detail itu
// berarti mengulang pekerjaan yang sama berkali-kali sehari.
const halaman = computed(() => usePage().url.split(/[?#]/)[0].replace(/\/+$/, ""));
const storageKey = computed(() => `sct.cols.${halaman.value}`);
const lebarKey = computed(() => `sct.lebar.${halaman.value}`);

function loadHidden() {
  try {
    const raw = localStorage.getItem(storageKey.value);
    if (!raw) return new Set();
    const keys = JSON.parse(raw);
    // Saring terhadap kolom yang benar-benar ada: definisi kolom bisa berubah
    // setelah rilis, dan key basi akan menyembunyikan kolom yang salah.
    const known = new Set(props.columns.map((c) => c.key));
    return new Set((Array.isArray(keys) ? keys : []).filter((k) => known.has(k)));
  } catch {
    return new Set();
  }
}

const hiddenKeys = ref(loadHidden());

// Halaman berganti (komponen dipakai ulang oleh Inertia) — muat ulang pilihan.
watch(storageKey, () => {
  hiddenKeys.value = loadHidden();
});

const visibleColumns = computed(() => props.columns.filter((c) => !hiddenKeys.value.has(c.key)));

function toggleColumn(key) {
  const next = new Set(hiddenKeys.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  // Sisakan minimal satu kolom; tabel tanpa kolom tak bisa dipulihkan lewat UI.
  if (next.size >= props.columns.length) return;
  hiddenKeys.value = next;
  try {
    if (next.size) localStorage.setItem(storageKey.value, JSON.stringify([...next]));
    else localStorage.removeItem(storageKey.value);
  } catch {
    /* mode privat / kuota penuh: pilihan tetap berlaku untuk sesi ini */
  }
}

function resetColumns() {
  hiddenKeys.value = new Set();
  try {
    localStorage.removeItem(storageKey.value);
  } catch {
    /* abaikan */
  }
}

function toggleSort(col) {
  if (!col.sortable) return;
  const dir = props.sortKey === col.key && props.sortDir === "asc" ? "desc" : "asc";
  emit("sort-change", { key: col.key, dir });
}

// --- Lebar kolom yang bisa ditarik pengguna --------------------------------
//
// Disimpan per halaman dengan cara yang sama persis dengan pilihan kolom di
// atas: laporan di sini punya sampai 25 kolom, dan mengulang penyetelan yang
// sama tiap kali berpindah menu itu pekerjaan yang tak berujung.
//
// Tabelnya tetap `table-layout: auto` SELAMA belum ada yang ditarik. Beralih ke
// `fixed` sejak awal akan membagi lebar rata untuk semua kolom dan mengubah
// tampilan setiap tabel di aplikasi ini, padahal tak seorang pun memintanya.
const LEBAR_MIN = 56;

function muatLebar() {
  try {
    const raw = localStorage.getItem(lebarKey.value);
    if (!raw) return {};
    const simpanan = JSON.parse(raw);
    if (!simpanan || typeof simpanan !== "object") return {};
    // Disaring terhadap kolom yang benar-benar ada — alasan yang sama dengan
    // `loadHidden`: definisi kolom berubah antar rilis, dan lebar basi akan
    // menempel di kolom yang salah.
    const dikenal = new Set(props.columns.map((c) => c.key));
    return Object.fromEntries(
      Object.entries(simpanan).filter(
        ([k, v]) => dikenal.has(k) && Number.isFinite(v) && v >= LEBAR_MIN),
    );
  } catch {
    return {};
  }
}

const lebar = ref(muatLebar());
const adaLebar = computed(() => Object.keys(lebar.value).length > 0);
const barisJudul = ref(null);

// Lebar tabel disebut eksplisit, bukan `w-full`. Dengan `table-fixed` dan lebar
// 100%, peramban membagi ulang sisa ruang ke seluruh kolom — menyempitkan satu
// kolom justru MELEBARKAN kolom lain, dan tarikan pengguna seperti tak
// berpengaruh. Menyebut jumlahnya membuat setiap piksel jadi milik kolomnya.
const totalLebar = computed(() =>
  visibleColumns.value.reduce((n, c) => n + (lebar.value[c.key] || LEBAR_MIN), 0));

watch(lebarKey, () => {
  lebar.value = muatLebar();
});

function simpanLebar() {
  try {
    if (adaLebar.value) localStorage.setItem(lebarKey.value, JSON.stringify(lebar.value));
    else localStorage.removeItem(lebarKey.value);
  } catch {
    /* mode privat / kuota penuh: lebar tetap berlaku untuk sesi ini */
  }
}

/** Bekukan lebar SEMUA kolom pada nilai yang sedang tampak di layar.
 *
 * Dipanggil sekali, tepat sebelum tarikan pertama. Tanpa ini peralihan ke
 * `table-fixed` membagi lebar rata dan seluruh tabel melompat di bawah kursor
 * pengguna — ia menarik satu kolom, dua puluh empat kolom lain ikut bergeser.
 */
function bekukanLebar() {
  const th = barisJudul.value?.querySelectorAll("th") || [];
  const awal = {};
  visibleColumns.value.forEach((col, i) => {
    const w = th[i]?.getBoundingClientRect().width;
    if (w) awal[col.key] = Math.max(LEBAR_MIN, Math.round(w));
  });
  lebar.value = awal;
}

function mulaiTarik(col, ev) {
  // Pegangan ada DI DALAM <th> yang juga tombol pengurut. Tanpa keduanya,
  // setiap tarikan ikut mengurut ulang tabelnya.
  ev.preventDefault();
  ev.stopPropagation();
  if (!adaLebar.value) bekukanLebar();

  const pegangan = ev.currentTarget;
  const mulaiX = ev.clientX;
  const mulaiLebar = lebar.value[col.key] || LEBAR_MIN;
  // Pointer event, bukan mouse: satu jalur yang sama untuk tetikus, layar
  // sentuh, dan pena — dan `setPointerCapture` membuat tarikan tetap terkirim
  // ke pegangan ini walau kursor keluar dari tabel, jadi tak ada penyimak yang
  // menempel di document dan bisa tertinggal.
  pegangan.setPointerCapture(ev.pointerId);

  const geser = (e) => {
    lebar.value = {
      ...lebar.value,
      [col.key]: Math.max(LEBAR_MIN, Math.round(mulaiLebar + e.clientX - mulaiX)),
    };
  };
  const selesai = () => {
    pegangan.removeEventListener("pointermove", geser);
    pegangan.removeEventListener("pointerup", selesai);
    pegangan.removeEventListener("pointercancel", selesai);
    simpanLebar();
  };
  pegangan.addEventListener("pointermove", geser);
  pegangan.addEventListener("pointerup", selesai);
  pegangan.addEventListener("pointercancel", selesai);
}

function resetLebar() {
  lebar.value = {};
  try {
    localStorage.removeItem(lebarKey.value);
  } catch {
    /* abaikan */
  }
}

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
const pf = new Intl.NumberFormat("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

function fmt(value, col) {
  if (value === null || value === undefined || value === "") return "-";
  if (col.format === "number") return nf.format(value);
  if (col.format === "rupiah") return rp.format(value);
  if (col.format === "persen") return `${pf.format(value)}%`;
  if (col.format === "date") {
    const d = new Date(value);
    return isNaN(d) ? value : d.toLocaleDateString("id-ID");
  }
  return value;
}

function alignClass(col) {
  return col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left";
}

// Elipsis hanya untuk teks bebas. Kolom angka tak pernah butuh dipotong, dan
// memotongnya diam-diam di laporan keuangan menyembunyikan digit — persis
// kesalahan yang paling mahal di layar ini.
const NUMERIC_FORMATS = new Set(["number", "rupiah", "persen"]);
function isNumeric(col) {
  return NUMERIC_FORMATS.has(col.format) || col.align === "right";
}
</script>

<template>
  <!-- Satu-satunya permukaan terangkat di halaman ini; lihat catatan
       .surface-raised di main.css. -->
  <div class="surface-raised overflow-hidden">
      <div class="flex justify-end border-b border-border-default bg-surface-2 px-3 py-1.5">
        <div ref="columnMenuRoot" class="relative">
          <button
            type="button"
            class="rounded-control border border-border-default px-2.5 py-1 text-xs text-ink-muted hover:bg-surface-3"
            :aria-expanded="columnMenuOpen"
            aria-haspopup="true"
            @click="toggleColumnMenu"
          >
            Kolom ({{ visibleColumns.length }}/{{ columns.length }})
          </button>
          <div
            v-if="columnMenuOpen"
            class="absolute right-0 z-20 mt-1 max-h-72 w-56 overflow-y-auto rounded-control border border-border-default bg-surface p-1.5 shadow-lg"
          >
            <label
              v-for="col in columns"
              :key="col.key"
              class="flex items-center gap-2 rounded-control px-2 py-1.5 text-sm text-ink hover:bg-surface-3"
            >
              <input type="checkbox" :checked="!hiddenKeys.has(col.key)" @change="toggleColumn(col.key)" />
              {{ col.label }}
            </label>
            <!-- Pilihan kini tersimpan antar-kunjungan, jadi harus ada jalan
                 kembali yang jelas ke "tampilkan semua". -->
            <button
              v-if="hiddenKeys.size"
              type="button"
              class="mt-1 w-full border-t border-border-default px-2 pt-2 text-left text-xs text-brand-fg hover:underline"
              @click="resetColumns"
            >
              Tampilkan semua kolom
            </button>
            <!-- Lebar juga tersimpan antar-kunjungan, jadi ia butuh jalan
                 pulang yang sama jelasnya. Tanpa ini kolom yang telanjur
                 disempitkan hanya bisa dikembalikan dengan menarik ulang satu
                 per satu. -->
            <button
              v-if="adaLebar"
              type="button"
              class="mt-1 w-full border-t border-border-default px-2 pt-2 text-left text-xs text-brand-fg hover:underline"
              @click="resetLebar"
            >
              Kembalikan lebar kolom
            </button>
          </div>
        </div>
      </div>

      <!-- Tinggi dibatasi supaya tabel tidak memanjang sampai bawah laman:
           badan tabel yang di-scroll, header sticky di dalam kontainer ini. -->
      <div class="max-h-[65vh] overflow-auto scroll-slim">
        <!-- `table-fixed` HANYA setelah ada kolom yang ditarik. Selama belum,
             tabelnya melebar mengikuti isinya persis seperti sebelum ini. -->
        <table
          :class="['text-xs tabular-nums', adaLebar ? 'table-fixed' : 'w-full']"
          :style="adaLebar ? { width: `${totalLebar}px` } : undefined"
        >
          <colgroup>
            <col
              v-for="col in visibleColumns"
              :key="col.key"
              :style="lebar[col.key] ? { width: `${lebar[col.key]}px` } : undefined"
            />
          </colgroup>
          <!-- Kolom yang sedang mengurut memakai satu-satunya warna yang muncul
               di dalam tabel: garis brand 2px di tepi bawah judulnya. Itu
               menjawab "tabel ini urut berdasarkan apa?" tanpa harus mencari
               tanda panah kecil di antara 25 judul kolom. -->
          <thead class="sticky top-0 z-10 bg-surface-3">
            <tr ref="barisJudul">
              <th
                v-for="col in visibleColumns"
                :key="col.key"
                scope="col"
                :role="col.sortable ? 'button' : undefined"
                :tabindex="col.sortable ? 0 : undefined"
                :aria-sort="
                  col.sortable
                    ? sortKey === col.key
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                    : undefined
                "
                :class="[
                  'relative whitespace-nowrap border-b border-border-strong px-2 py-1.5 text-[11px] font-semibold',
                  adaLebar ? 'overflow-hidden' : '',
                  alignClass(col),
                  sortKey === col.key ? 'text-ink shadow-[inset_0_-2px_0_var(--color-brand-500)]' : 'text-ink-muted',
                  col.sortable
                    ? 'cursor-pointer select-none hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500'
                    : '',
                ]"
                @click="toggleSort(col)"
                @keydown.enter.prevent="toggleSort(col)"
                @keydown.space.prevent="toggleSort(col)"
              >
                <span class="inline-flex items-center gap-1">
                  {{ col.label }}
                  <span v-if="col.sortable && sortKey === col.key" class="text-brand-fg">
                    {{ sortDir === "asc" ? "▲" : "▼" }}
                  </span>
                </span>
                <!-- Pegangan lebar kolom. Lebar sentuhnya 8px sementara garisnya
                     1px: sasaran 1px mustahil dikenai di layar sentuh, dan di
                     tetikus pun ia menyiksa. `touch-none` mencegah peramban
                     menafsirkan tarikan sebagai gulir halaman. -->
                <span
                  class="group absolute right-0 top-0 h-full w-2 cursor-col-resize touch-none select-none"
                  role="separator"
                  aria-orientation="vertical"
                  :aria-label="`Ubah lebar kolom ${col.label}`"
                  :title="`Tarik untuk mengubah lebar kolom ${col.label}`"
                  @pointerdown="mulaiTarik(col, $event)"
                  @click.stop
                  @dblclick.stop
                >
                  <!-- Seluruhnya DI DALAM <th>, tanpa menjorok ke kolom sebelah:
                       pegangan yang menyeberang tepi kanan kolom terakhir
                       memunculkan gulir horizontal beberapa piksel di setiap
                       tabel, walau tak ada yang melebar. -->
                  <span
                    class="pointer-events-none absolute right-0 top-1 h-[calc(100%-0.5rem)] w-px bg-border-strong group-hover:bg-brand-500"
                  />
                </span>
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border-default">
            <tr v-if="loading">
              <td :colspan="visibleColumns.length" class="py-12">
                <div class="flex justify-center"><Spinner /></div>
              </td>
            </tr>
            <tr v-else-if="!rows.length">
              <td :colspan="visibleColumns.length">
                <EmptyState :message="emptyMessage" />
              </td>
            </tr>
            <tr
              v-for="row in loading ? [] : rows"
              :key="row[rowKey]"
              class="even:bg-surface-2/60 hover:bg-surface-3"
            >
              <td
                v-for="col in visibleColumns"
                :key="col.key"
                :class="[
                  'px-2 py-1 leading-snug text-ink',
                  adaLebar ? 'overflow-hidden' : '',
                  alignClass(col),
                ]"
              >
                <!-- Nilai panjang (nama barang/supplier) dipotong dengan elipsis:
                     tanpa ini satu baris saja bisa memaksa tabel melebar dan
                     memunculkan scroll horizontal di layar 1366px. Teks utuh
                     tetap terbaca lewat tooltip. Isi slot tak disentuh — di situ
                     ada badge/tombol yang tak boleh dipotong.

                     Batas 26ch dilepas begitu kolomnya punya lebar sendiri:
                     lebar yang ditarik pengguna-lah yang memotong, bukan angka
                     tetap yang tak tahu-menahu soal itu. -->
                <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                  <!-- Angka ikut dipotong saat kolomnya disempitkan, dan itu
                       kompromi yang disengaja: melimpah ke kolom sebelah membuat
                       laporan tak terbaca sama sekali. Supaya tak ada digit yang
                       hilang diam-diam — kesalahan paling mahal di layar ini —
                       nilai utuhnya selalu ada di tooltip begitu pemotongan
                       mungkin terjadi. -->
                  <span
                    v-if="isNumeric(col)"
                    class="block truncate whitespace-nowrap"
                    :title="adaLebar ? String(fmt(row[col.key], col)) : undefined"
                  >{{ fmt(row[col.key], col) }}</span>
                  <span
                    v-else
                    :class="['block truncate', adaLebar ? 'max-w-full' : 'max-w-[26ch]']"
                    :title="String(row[col.key] ?? '')"
                  >
                    {{ fmt(row[col.key], col) }}
                  </span>
                </slot>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-if="!loading && total"
        class="flex flex-wrap items-center justify-between gap-2 border-t border-border-default bg-surface-2 px-3 py-1.5 text-xs text-ink-muted"
      >
        <div class="flex items-center gap-2">
          <label :for="`${rowKey}-per-page`">Per halaman:</label>
          <select
            :id="`${rowKey}-per-page`"
            :value="perPage"
            @change="emit('per-page-change', Number($event.target.value))"
            class="h-8 rounded-control border border-border-strong bg-surface px-2 text-xs text-ink"
          >
            <option v-for="n in perPageOptions" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <Pagination
          v-if="total > perPage"
          :page="page"
          :total="total"
          :per-page="perPage"
          @update:page="emit('page-change', $event)"
        />
        <span v-else>Menampilkan semua {{ total }} data</span>
      </div>
  </div>
</template>
