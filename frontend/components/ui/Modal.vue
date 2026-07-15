<script setup>
import { watch, onBeforeUnmount } from "vue";

const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: "" },
  size: { type: String, default: "md" }, // sm | md | lg
});
const emit = defineEmits(["close"]);

const sizes = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" };

function onKey(e) {
  if (e.key === "Escape" && props.show) emit("close");
}

// Lock body scroll + Esc-to-close while open.
watch(
  () => props.show,
  (open) => {
    document.body.style.overflow = open ? "hidden" : "";
    if (open) window.addEventListener("keydown", onKey);
    else window.removeEventListener("keydown", onKey);
  },
);
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      leave-active-class="transition duration-100 ease-in"
      leave-to-class="opacity-0"
    >
      <div v-if="show" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-ink/30 dark:bg-ink/50" @click="emit('close')" />
        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="opacity-0 translate-y-2 scale-95"
          leave-active-class="transition duration-100 ease-in"
          leave-to-class="opacity-0 scale-95"
        >
          <div
            v-if="show"
            role="dialog"
            aria-modal="true"
            :aria-label="title || undefined"
            :class="['relative flex max-h-[85vh] w-full flex-col rounded-card bg-surface shadow-xl', sizes[size]]"
          >
            <div class="flex shrink-0 items-center justify-between border-b border-border-default px-5 py-3.5">
              <h3 class="text-base font-semibold text-ink">{{ title }}</h3>
              <button class="rounded p-1 text-ink-muted hover:bg-surface-3 hover:text-ink" aria-label="Tutup" title="Tutup" @click="emit('close')">
                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="min-h-0 overflow-y-auto px-5 py-4">
              <slot />
            </div>
            <div v-if="$slots.footer" class="flex shrink-0 justify-end gap-2 border-t border-border-default px-5 py-3.5">
              <slot name="footer" />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
