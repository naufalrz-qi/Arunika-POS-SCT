<script setup>
import { computed } from "vue";

const props = defineProps({
  page: { type: Number, required: true },
  total: { type: Number, required: true }, // total items
  perPage: { type: Number, default: 10 },
});
const emit = defineEmits(["update:page"]);

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.perPage)));
const from = computed(() => (props.total === 0 ? 0 : (props.page - 1) * props.perPage + 1));
const to = computed(() => Math.min(props.page * props.perPage, props.total));

function go(p) {
  if (p >= 1 && p <= totalPages.value) emit("update:page", p);
}
</script>

<template>
  <div class="flex items-center justify-between px-1 py-2 text-sm text-ink-muted">
    <span>Menampilkan {{ from }}–{{ to }} dari {{ total }}</span>
    <div class="flex items-center gap-1">
      <button
        class="rounded-md border border-border-default px-2.5 py-1 disabled:opacity-40 hover:bg-surface-3"
        :disabled="page <= 1"
        @click="go(page - 1)"
      >
        Sebelumnya
      </button>
      <span class="px-2">{{ page }} / {{ totalPages }}</span>
      <button
        class="rounded-md border border-border-default px-2.5 py-1 disabled:opacity-40 hover:bg-surface-3"
        :disabled="page >= totalPages"
        @click="go(page + 1)"
      >
        Berikutnya
      </button>
    </div>
  </div>
</template>
