<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
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
  open.value = false;
  q.value = "";
}
</script>

<template>
  <div ref="root" class="relative">
    <span v-if="label" class="mb-1.5 block text-[10px] font-heading font-bold uppercase tracking-widest text-ink-muted">{{ label }}</span>
    <button
      type="button"
      @click="open = !open"
      class="flex h-10 w-full items-center justify-between rounded border border-border-strong bg-surface/50 backdrop-blur-sm px-3 py-2 text-left text-sm text-ink transition-all duration-200 hover:border-brand-400 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/50 focus:shadow-[0_0_10px_rgba(11,61,145,0.2)]"
    >
      <span :class="modelValue === '' || modelValue === null ? 'text-ink-subtle' : ''">{{ currentLabel }}</span>
      <span class="text-brand-500">▾</span>
    </button>
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full rounded border border-border-strong bg-surface shadow-[0_4px_15px_rgba(0,0,0,0.15)] backdrop-blur-md"
    >
      <input
        v-model="q"
        type="text"
        placeholder="Cari…"
        class="h-10 w-full border-b border-border-strong bg-transparent px-3 py-2 text-sm text-ink focus:outline-none focus:bg-surface-3/50"
      />
      <div class="max-h-56 overflow-y-auto scroll-slim">
        <button
          type="button"
          @click="pick('')"
          class="block w-full px-3 py-2 text-left text-sm text-ink-muted hover:bg-surface-3"
        >
          {{ placeholder }}
        </button>
        <button
          v-for="o in filtered"
          :key="o.value"
          type="button"
          @click="pick(o.value)"
          class="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-surface-3"
        >
          {{ o.label }}
        </button>
      </div>
    </div>
  </div>
</template>
