<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useSlots } from "vue";
import Button from "@/components/ui/Button.vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  loading: { type: Boolean, default: false },
  // Optional: the useServerReport() form object. Enables the "N aktif" badge
  // and auto-opens "Filter Lanjutan" when an advanced (f_*) filter is filled.
  form: { type: Object, default: null },
});
const emit = defineEmits(["submit", "reset"]);
const open = ref(true);
const slots = useSlots();
const formEl = ref(null);

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
  open.value = true;
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

const advancedOpen = ref(
  props.form
    ? Object.entries(props.form).some(
        ([k, v]) => k.startsWith("f_") && !k.endsWith("_mode") && isFilled(v),
      )
    : false,
);
</script>

<template>
  <div class="panel-cut-frame panel-cut-frame-accent mb-4">
    <div class="mecha-card panel-cut bg-surface">
      <button
        type="button"
        :aria-expanded="open"
        aria-controls="filter-panel-body"
        @click="open = !open"
        class="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span class="flex items-center gap-2">
          <span class="text-sm font-semibold text-ink">Filter</span>
          <span
            v-if="activeCount"
            class="rounded-full bg-brand-500 px-2 py-0.5 text-[10px] font-bold leading-none text-white"
          >
            {{ activeCount }} aktif
          </span>
        </span>
        <span class="flex items-center gap-2">
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
        @submit.prevent="emit('submit')"
        class="border-t border-border-default p-4"
      >
        <div class="grid grid-cols-1 gap-3 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          <slot />
          <template v-if="hasAdvanced">
            <button
              type="button"
              :aria-expanded="advancedOpen"
              @click="advancedOpen = !advancedOpen"
              class="col-span-full flex items-center gap-2 border-t border-border-default pt-3 text-left text-[11px] font-heading font-bold uppercase tracking-wide text-ink-subtle transition-colors hover:text-brand-fg"
            >
              <span class="h-3 w-0.5 rounded-full bg-rx-yellow"></span>
              Filter Lanjutan
              <Icon
                name="chevron"
                size="h-3.5 w-3.5"
                :class="['shrink-0 transition-transform duration-200', advancedOpen ? '' : '-rotate-90']"
              />
            </button>
            <template v-if="advancedOpen">
              <slot name="lanjutan" />
            </template>
          </template>
        </div>
        <div
          class="mt-4 -mx-4 -mb-4 flex items-center justify-end gap-2 border-t border-border-default bg-surface-2 px-4 py-3"
        >
          <Button type="button" variant="ghost" @click="emit('reset')">Reset</Button>
          <Button type="submit" variant="primary" :loading="loading">Tampilkan</Button>
        </div>
      </form>
    </div>
  </div>
</template>
