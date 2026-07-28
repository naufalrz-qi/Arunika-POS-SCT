<script setup>
import { watch, onBeforeUnmount, nextTick, ref } from "vue";

const props = defineProps({
  show: { type: Boolean, default: false },
  title: { type: String, default: "" },
  size: { type: String, default: "md" }, // sm | md | lg
});
const emit = defineEmits(["close"]);

const sizes = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" };

const panel = ref(null);
// Elemen yang memicu modal, supaya fokus bisa dikembalikan saat ditutup —
// tanpa itu fokus terlempar ke <body> dan pengguna keyboard harus menelusuri
// halaman dari awal untuk kembali ke tempatnya.
let lastFocused = null;

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables() {
  return Array.from(panel.value?.querySelectorAll(FOCUSABLE) ?? []).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

// Tab tidak boleh keluar dari dialog: aria-modal saja hanya memberi tahu
// pembaca layar, tidak menahan fokus.
function trapTab(e) {
  const items = focusables();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (e.shiftKey && (active === first || !panel.value?.contains(active))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}

function onKey(e) {
  if (!props.show) return;
  if (e.key === "Escape") emit("close");
  else if (e.key === "Tab") trapTab(e);
}

// Lock body scroll + Esc-to-close + focus trap while open.
watch(
  () => props.show,
  (open) => {
    document.body.style.overflow = open ? "hidden" : "";
    if (open) {
      lastFocused = document.activeElement;
      window.addEventListener("keydown", onKey);
      nextTick(() => focusables()[0]?.focus());
    } else {
      window.removeEventListener("keydown", onKey);
      lastFocused?.focus?.();
      lastFocused = null;
    }
  },
);
// Unmounting while open (Inertia navigation, parent v-if) would otherwise
// leave body scroll locked with no way back short of a reload.
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
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
          <!-- Modal melayang di atas halaman, bukan bagian dari kanvasnya, jadi
               ia boleh memakai bayangan sekalipun permukaan lain rata — tanpa
               itu ia menempel ke latar. -->
          <div
            v-if="show"
            ref="panel"
            role="dialog"
            aria-modal="true"
            :aria-label="title || undefined"
            :class="['surface-raised relative flex max-h-[85vh] w-full flex-col overflow-hidden shadow-lg', sizes[size]]"
          >
            <div class="flex shrink-0 items-center justify-between border-b border-border-default px-4 py-3">
              <h3 class="text-base font-semibold text-ink">{{ title }}</h3>
              <button class="rounded-control p-1 text-ink-muted hover:bg-surface-3 hover:text-ink" aria-label="Tutup" title="Tutup" @click="emit('close')">
                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div class="min-h-0 overflow-y-auto px-4 py-4">
              <slot />
            </div>
            <div v-if="$slots.footer" class="flex shrink-0 justify-end gap-2 border-t border-border-default bg-surface-2 px-4 py-3">
              <slot name="footer" />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
