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
  <div class="overflow-hidden rounded-card border border-border-default bg-surface shadow-sm">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left transition hover:bg-surface-3"
      @click="open = !open"
    >
      <div class="flex items-center gap-3">
        <span v-if="icon" class="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-bg text-brand-fg">
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
        :class="['shrink-0 text-ink-muted transition-transform duration-200', open ? '' : '-rotate-90']"
      />
    </button>
    <div v-show="open" class="border-t border-border-default p-5">
      <slot />
    </div>
  </div>
</template>
