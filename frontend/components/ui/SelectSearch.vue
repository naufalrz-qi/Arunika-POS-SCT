<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from "vue";
const props = defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  options: { type: Array, default: () => [] }, // [{value,label}]
  label: { type: String, default: "" },
  placeholder: { type: String, default: "Semua" },
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const q = ref("");
const root = ref(null);
const trigger = ref(null);
const search = ref(null);
const listbox = ref(null);
// Indeks pilihan yang sedang disorot keyboard; -1 = baris placeholder "Semua".
const activeIndex = ref(-1);

let uid = 0;
const listboxId = `selectsearch-${++uid}-${Math.random().toString(36).slice(2, 7)}`;

function onClickOutside(e) {
  if (open.value && root.value && !root.value.contains(e.target)) open.value = false;
}
onMounted(() => document.addEventListener("mousedown", onClickOutside));
onBeforeUnmount(() => document.removeEventListener("mousedown", onClickOutside));
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
  open.value = false;
  q.value = "";
  activeIndex.value = -1;
  if (refocus) nextTick(() => trigger.value?.focus());
}

// Membuka daftar langsung menaruh kursor di kolom pencarian: kontrol ini dipakai
// untuk daftar divisi/supplier yang panjang, dan tanpa itu pengguna harus
// meraih mouse hanya untuk mulai mengetik.
function toggle() {
  open.value = !open.value;
  if (open.value) {
    activeIndex.value = -1;
    nextTick(() => search.value?.focus());
  } else {
    q.value = "";
  }
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
    <span v-if="label" class="mb-1.5 block text-[11px] font-heading font-semibold tracking-wide text-ink-muted">{{ label }}</span>
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
      class="flex h-10 w-full items-center justify-between rounded border border-border-strong bg-surface/50 backdrop-blur-sm px-3 py-2 text-left text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:shadow-[0_0_10px_rgba(11,61,145,0.2)]"
    >
      <span :class="modelValue === '' || modelValue === null ? 'text-ink-subtle' : ''">{{ currentLabel }}</span>
      <span class="text-brand-500" aria-hidden="true">▾</span>
    </button>
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full rounded border border-border-strong bg-surface shadow-[0_4px_15px_rgba(0,0,0,0.15)] backdrop-blur-md"
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
        class="h-10 w-full border-b border-border-strong bg-transparent px-3 py-2 text-sm text-ink focus:outline-none focus:bg-surface-3/50"
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
