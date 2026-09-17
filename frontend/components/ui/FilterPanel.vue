<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots } from "vue";
import Button from "@/components/ui/Button.vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  loading: { type: Boolean, default: false },
  // Optional: the useServerReport() form object. Enables the "N aktif" badge,
  // the summary shown while the panel is closed, and auto-opens "Filter
  // Lanjutan" when an advanced (f_*) filter is filled.
  form: { type: Object, default: null },
});
const emit = defineEmits(["submit", "reset"]);
const slots = useSlots();
const formEl = ref(null);

// Terbuka/tertutup diingat lintas halaman. Panel yang selalu terbuka memakan
// ±300px di atas tabel — di layar 1440×900 baris pertama laporan baru muncul
// di sekitar piksel ke-740. Sekali orang menutupnya (atau menekan Tampilkan),
// laporan berikutnya dibuka dengan tabel di atas, ringkasan filter di header.
const KUNCI_TERBUKA = "sct.filterTerbuka";
function muatTerbuka() {
  try {
    return localStorage.getItem(KUNCI_TERBUKA) !== "0";
  } catch {
    return true;
  }
}
const open = ref(muatTerbuka());
function setOpen(v) {
  open.value = v;
  try {
    localStorage.setItem(KUNCI_TERBUKA, v ? "1" : "0");
  } catch {
    /* mode privat: berlaku untuk halaman ini saja */
  }
}

function kirim() {
  emit("submit");
  // Hasilnya ada di bawah; filternya sudah terangkum di header.
  setOpen(false);
}

// Pintasan "/" ke kolom isian pertama panel ini. Sebelumnya tinggal di
// ServerTable: satu listener window per instance tabel, yang mencari kolom
// pencarian lewat document.querySelector berdasarkan teks placeholder dan
// mengambil input pertama yang cocok di mana pun di halaman. Di sini
// pencariannya dibatasi ke <form> milik panel sendiri, dan panel yang tertutup
// dibuka dulu supaya fokusnya tak jatuh ke elemen tersembunyi.
function onKey(e) {
  if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (/input|textarea|select/i.test(e.target.tagName) || e.target.isContentEditable) return;
  e.preventDefault();
  setOpen(true);
  nextTick(() => {
    formEl.value?.querySelector('input:not([type="checkbox"]):not([type="radio"])')?.focus();
  });
}
onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
const hasAdvanced = computed(() => !!slots.lanjutan);

function isFilled(v) {
  return v !== "" && v !== null && v !== undefined;
}

// Count logical active filters: date_from/date_to/date collapse into one,
// f_qty_min/f_qty_max into one; paging/sort state and mode toggles don't count.
const activeCount = computed(() => {
  if (!props.form) return 0;
  const skip = new Set(["page", "per_page", "sort", "sort_dir"]);
  const bases = new Set();
  for (const [k, v] of Object.entries(props.form)) {
    if (skip.has(k) || k.endsWith("_mode")) continue;
    if (!isFilled(v)) continue;
    bases.add(k.replace(/_(from|to|date|min|max)$/, ""));
  }
  return bases.size;
});

// "YYYY-MM-DD" dibaca sebagai tanggal lokal. `new Date("2026-09-01")` dibaca
// sebagai UTC dan di WITA bisa bergeser sehari saat diformat.
function tgl(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

// Ringkasan untuk header saat panel tertutup: periode, istilah cari, lalu sisa
// filter sebagai angka. Tanpa ini panel tertutup menyembunyikan apa yang
// sedang menyaring tabel di bawahnya.
const ringkasan = computed(() => {
  const f = props.form;
  if (!f) return "";
  const bagian = [];
  let terhitung = 0;
  if (f.date_mode === "exact" ? f.date : f.date_from || f.date_to) {
    bagian.push(f.date_mode === "exact" ? tgl(f.date) : `${tgl(f.date_from) || "…"} – ${tgl(f.date_to) || "…"}`);
    terhitung++;
  }
  if (isFilled(f.search)) {
    bagian.push(`"${f.search}"`);
    terhitung++;
  }
  const sisa = activeCount.value - terhitung;
  if (sisa > 0) bagian.push(`+${sisa} filter`);
  return bagian.join(" · ");
});

const advancedOpen = ref(
  props.form
    ? Object.entries(props.form).some(
        ([k, v]) => k.startsWith("f_") && !k.endsWith("_mode") && isFilled(v),
      )
    : false,
);
</script>

<template>
  <div class="surface-flat mb-4">
    <button
      type="button"
      :aria-expanded="open"
      aria-controls="filter-panel-body"
      @click="setOpen(!open)"
      class="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left"
    >
      <span class="flex min-w-0 items-center gap-2">
        <span class="text-sm font-semibold text-ink">Filter</span>
        <span
          v-if="activeCount"
          class="shrink-0 rounded-full bg-brand-bg px-2 py-0.5 text-[10px] font-semibold leading-none text-brand-fg"
        >
          {{ activeCount }} aktif
        </span>
        <span v-if="!open && ringkasan" class="truncate text-xs text-ink-muted">{{ ringkasan }}</span>
      </span>
      <span class="flex shrink-0 items-center gap-2">
        <!-- Pintasannya tak berguna kalau tak ada yang tahu ia ada. -->
        <kbd
          class="hidden rounded-control border border-border-default bg-surface-2 px-1.5 py-0.5 font-sans text-[10px] font-semibold text-ink-subtle sm:inline-block"
          title="Tekan / untuk melompat ke isian filter pertama"
        >/</kbd>
        <!-- Ikon, bukan glyph teks "▾"/"▸": glyph tak ikut ukuran/warna ikon
             lain dan bentuknya berbeda antar-font. Sama seperti
             CollapsibleSection, yang mengerjakan hal yang sama. -->
        <Icon
          name="chevron"
          size="h-4 w-4"
          :class="['shrink-0 text-ink-subtle transition-transform duration-200', open ? '' : '-rotate-90']"
        />
      </span>
    </button>
    <form
      id="filter-panel-body"
      ref="formEl"
      v-show="open"
      @submit.prevent="kirim"
      class="px-5 pb-4"
    >
      <div class="grid grid-cols-1 gap-3 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
        <slot />
        <template v-if="hasAdvanced && advancedOpen">
          <slot name="lanjutan" />
        </template>
      </div>
      <!-- "Filter lanjutan" sebaris dengan tombol: dulu ia punya baris sendiri
           di antara isian dan tombol, satu baris kosong lagi di atas tabel. -->
      <div class="mt-4 flex items-center gap-2 border-t border-border-default pt-4">
        <button
          v-if="hasAdvanced"
          type="button"
          :aria-expanded="advancedOpen"
          @click="advancedOpen = !advancedOpen"
          class="flex items-center gap-1.5 text-xs font-semibold text-ink-muted transition-colors hover:text-ink"
        >
          Filter lanjutan
          <Icon
            name="chevron"
            size="h-3.5 w-3.5"
            :class="['shrink-0 transition-transform duration-200', advancedOpen ? '' : '-rotate-90']"
          />
        </button>
        <div class="ml-auto flex items-center gap-2">
          <Button type="button" variant="ghost" @click="emit('reset')">Reset</Button>
          <Button type="submit" variant="primary" :loading="loading">Tampilkan</Button>
        </div>
      </div>
    </form>
  </div>
</template>
