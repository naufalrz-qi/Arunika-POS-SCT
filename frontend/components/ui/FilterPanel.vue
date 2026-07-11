<script setup>
import { computed, ref, useSlots } from "vue";
import Button from "@/components/ui/Button.vue";

const props = defineProps({
  loading: { type: Boolean, default: false },
  // Optional: the useServerReport() form object. Enables the "N aktif" badge
  // and auto-opens "Filter Lanjutan" when an advanced (f_*) filter is filled.
  form: { type: Object, default: null },
});
const emit = defineEmits(["submit", "reset"]);
const open = ref(true);
const slots = useSlots();
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
        <span class="text-ink-subtle">{{ open ? "▾" : "▸" }}</span>
      </button>
      <form v-show="open" @submit.prevent="emit('submit')" class="border-t border-border-default p-4">
        <div class="grid grid-cols-1 gap-3 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
          <slot />
          <template v-if="hasAdvanced">
            <button
              type="button"
              @click="advancedOpen = !advancedOpen"
              class="col-span-full flex items-center gap-2 border-t border-border-default pt-3 text-left text-[10px] font-heading font-bold uppercase tracking-widest text-ink-subtle transition-colors hover:text-brand-fg"
            >
              <span class="h-3 w-0.5 rounded-full bg-rx-yellow"></span>
              Filter Lanjutan
              <span>{{ advancedOpen ? "▾" : "▸" }}</span>
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
