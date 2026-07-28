<script setup>
import { ref } from "vue";
import Icon from "@/components/nav/Icon.vue";

const props = defineProps({
  title: { type: String, default: "" },
  subtitle: { type: String, default: "" },
  icon: { type: String, default: "" },
  defaultOpen: { type: Boolean, default: true },
});

const open = ref(props.defaultOpen);
</script>

<template>
  <div class="surface-flat mb-4 last:mb-0">
    <button
      type="button"
      :aria-expanded="open"
      class="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-2"
      @click="open = !open"
    >
      <div class="flex items-center gap-3">
        <span v-if="icon" class="flex h-7 w-7 items-center justify-center rounded-control bg-surface-3 text-ink-muted">
          <Icon :name="icon" size="h-4 w-4" />
        </span>
        <div>
          <h3 v-if="title" class="text-sm font-semibold text-ink">{{ title }}</h3>
          <p v-if="subtitle" class="text-xs text-ink-muted">{{ subtitle }}</p>
        </div>
      </div>
      <Icon
        name="chevron"
        size="h-4 w-4"
        :class="['shrink-0 text-ink-subtle transition-transform duration-200', open ? '' : '-rotate-90']"
      />
    </button>
    <div v-show="open" class="border-t border-border-default p-4">
      <slot />
    </div>
  </div>
</template>
