<script setup>
import { ref, computed } from "vue";
const props = defineProps({
  modelValue: { type: [String, Number, null], default: "" },
  options: { type: Array, default: () => [] }, // [{value,label}]
  label: { type: String, default: "" },
  placeholder: { type: String, default: "Semua" },
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const q = ref("");
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
  <div class="relative">
    <span v-if="label" class="mb-1 block text-xs text-ink-muted">{{ label }}</span>
    <button
      type="button"
      @click="open = !open"
      class="flex w-full items-center justify-between rounded-card border border-border-default bg-surface px-3 py-2 text-left text-sm text-ink"
    >
      <span :class="modelValue === '' || modelValue === null ? 'text-ink-subtle' : ''">{{ currentLabel }}</span>
      <span class="text-ink-subtle">▾</span>
    </button>
    <div
      v-if="open"
      class="absolute z-20 mt-1 w-full rounded-card border border-border-default bg-surface shadow-lg"
    >
      <input
        v-model="q"
        type="text"
        placeholder="Cari…"
        class="w-full border-b border-border-default bg-surface px-3 py-2 text-sm text-ink"
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
