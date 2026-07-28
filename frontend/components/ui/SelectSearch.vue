<script setup>
import { ref, computed, nextTick, watch } from "vue";
import { useDismissable } from "@/composables/useDismissable";
import Icon from "@/components/nav/Icon.vue";
const props = defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  options: { type: Array, default: () => [] }, // [{value,label}]
  label: { type: String, default: "" },
  placeholder: { type: String, default: "Semua" },
});
const emit = defineEmits(["update:modelValue"]);
const q = ref("");
const trigger = ref(null);
const search = ref(null);
const listbox = ref(null);
// Indeks pilihan yang sedang disorot keyboard; -1 = baris placeholder "Semua".
const activeIndex = ref(-1);

// Id unik per instance: satu halaman laporan memasang beberapa SelectSearch,
// dan aria-controls harus menunjuk ke daftar miliknya sendiri.
const listboxId = `selectsearch-${Math.random().toString(36).slice(2, 9)}`;

// Klik-di-luar dan Escape ditangani composable yang sama dengan menu kolom,
// menu pengguna, dan menu koneksi.
const { open, root, close: dismiss } = useDismissable({
  onClose: () => {
    q.value = "";
    activeIndex.value = -1;
  },
});

const filtered = computed(() => {
  const t = q.value.toLowerCase().trim();
  if (!t) return props.options;
  return props.options.filter((o) => String(o.label).toLowerCase().includes(t));
});
const currentLabel = computed(() => {
  const hit = props.options.find((o) => String(o.value) === String(props.modelValue));
  return hit ? hit.label : props.placeholder;
});
function pick(v) {
  emit("update:modelValue", v);
  close({ refocus: true });
}

function close({ refocus = false } = {}) {
  dismiss();
  if (refocus) nextTick(() => trigger.value?.focus());
}

// Membuka daftar langsung menaruh kursor di kolom pencarian: kontrol ini dipakai
// untuk daftar divisi/supplier yang panjang, dan tanpa itu pengguna harus
// meraih mouse hanya untuk mulai mengetik.
function toggle() {
  if (open.value) {
    close();
    return;
  }
  open.value = true;
  activeIndex.value = -1;
  nextTick(() => search.value?.focus());
}

// Menyaring ulang bisa membuat sorotan menunjuk ke luar daftar.
watch(filtered, (list) => {
  if (activeIndex.value >= list.length) activeIndex.value = list.length - 1;
});

function move(delta) {
  if (!open.value) {
    toggle();
    return;
  }
  const lower = -1; // baris placeholder
  const upper = filtered.value.length - 1;
  let next = activeIndex.value + delta;
  if (next < lower) next = upper;
  if (next > upper) next = lower;
  activeIndex.value = next;
  nextTick(() => {
    listbox.value
      ?.querySelector(`[data-index="${activeIndex.value}"]`)
      ?.scrollIntoView({ block: "nearest" });
  });
}

function chooseActive() {
  if (!open.value) return;
  if (activeIndex.value === -1) pick("");
  else {
    const hit = filtered.value[activeIndex.value];
    if (hit) pick(hit.value);
  }
}

const activeId = computed(() =>
  open.value ? `${listboxId}-opt-${activeIndex.value}` : undefined,
);
</script>

<template>
  <div ref="root" class="relative">
    <span v-if="label" class="mb-1 block text-xs font-medium text-ink-muted">{{ label }}</span>
    <button
      ref="trigger"
      type="button"
      role="combobox"
      :aria-expanded="open"
      :aria-controls="listboxId"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.escape="close({ refocus: true })"
      class="flex h-9 w-full items-center justify-between rounded-control border border-border-strong bg-surface px-2.5 text-left text-sm text-ink transition-colors duration-150 focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500"
    >
      <span :class="modelValue === '' || modelValue === null ? 'text-ink-subtle' : ''">{{ currentLabel }}</span>
      <Icon name="chevron" size="h-4 w-4" class="shrink-0 text-ink-muted" aria-hidden="true" />
    </button>
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full rounded-control border border-border-strong bg-surface shadow-lg"
    >
      <input
        ref="search"
        v-model="q"
        type="text"
        placeholder="Cari…"
        role="searchbox"
        :aria-controls="listboxId"
        :aria-activedescendant="activeId"
        @keydown.down.prevent="move(1)"
        @keydown.up.prevent="move(-1)"
        @keydown.enter.prevent="chooseActive"
        @keydown.escape.prevent="close({ refocus: true })"
        @keydown.tab="close()"
        class="h-9 w-full border-b border-border-strong bg-transparent px-2.5 text-sm text-ink focus:outline-none focus:bg-surface-2"
      />
      <div ref="listbox" :id="listboxId" role="listbox" class="max-h-56 overflow-y-auto scroll-slim">
        <button
          type="button"
          role="option"
          data-index="-1"
          :id="`${listboxId}-opt--1`"
          :aria-selected="modelValue === '' || modelValue === null"
          @click="pick('')"
          :class="[
            'block w-full px-3 py-2 text-left text-sm text-ink-muted hover:bg-surface-3',
            activeIndex === -1 ? 'bg-surface-3' : '',
          ]"
        >
          {{ placeholder }}
        </button>
        <button
          v-for="(o, i) in filtered"
          :key="o.value"
          type="button"
          role="option"
          :data-index="i"
          :id="`${listboxId}-opt-${i}`"
          :aria-selected="String(o.value) === String(modelValue)"
          @click="pick(o.value)"
          :class="[
            'block w-full px-3 py-2 text-left text-sm text-ink hover:bg-surface-3',
            activeIndex === i ? 'bg-surface-3' : '',
          ]"
        >
          {{ o.label }}
        </button>
      </div>
    </div>
  </div>
</template>
