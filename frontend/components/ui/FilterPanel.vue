<script setup>
import { ref } from "vue";
import Button from "@/components/ui/Button.vue";
defineProps({
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(["submit", "reset"]);
const open = ref(true);
</script>

<template>
  <div class="mb-4 rounded-card border border-border-default bg-surface">
    <button
      type="button"
      @click="open = !open"
      class="flex w-full items-center justify-between px-4 py-3 text-left"
    >
      <span class="text-sm font-semibold text-ink">Filter</span>
      <span class="text-ink-subtle">{{ open ? "▾" : "▸" }}</span>
    </button>
    <form v-show="open" @submit.prevent="emit('submit')" class="border-t border-border-default p-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <slot />
      </div>
      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" @click="emit('reset')">Reset</Button>
        <Button type="submit" variant="primary" :loading="loading">Tampilkan</Button>
      </div>
    </form>
  </div>
</template>
