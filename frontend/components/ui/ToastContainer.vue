<script setup>
import { watch } from "vue";
import { usePage } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
const { toasts } = storeToRefs(ui);
const page = usePage();

// Surface Django flash messages (shared via inertia_share) as toasts.
watch(
  () => page.props.flash,
  (flash) => {
    if (!flash) return;
    if (flash.success) ui.pushToast(flash.success, "success");
    if (flash.error) ui.pushToast(flash.error, "danger");
  },
  { immediate: true, deep: true },
);

const styles = {
  success: "bg-success-600",
  danger: "bg-danger-600",
  error: "bg-danger-600", // alias: callers use "error"; without this it fell through to info (blue)
  warning: "bg-warning-600",
  info: "bg-brand-600",
};
</script>

<template>
  <Teleport to="body">
    <!-- w-80 tetap (320px) meluber di viewport 320px begitu ditambah right-4. -->
    <!-- role=status + aria-live: tanpa ini setiap konfirmasi simpan/hapus lewat
         tanpa pernah terdengar oleh pembaca layar. "polite" supaya tidak
         memotong pengumuman yang sedang berjalan. -->
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      class="fixed right-4 top-4 z-[60] flex w-[calc(100vw-2rem)] max-w-80 flex-col gap-2"
    >
      <TransitionGroup
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0 translate-x-4"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="opacity-0 translate-x-4"
      >
        <div
          v-for="t in toasts"
          :key="t.id"
          :class="['flex items-start justify-between gap-3 rounded-lg px-4 py-3 text-sm text-white shadow-lg', styles[t.type] || styles.info]"
        >
          <span>{{ t.message }}</span>
          <button
            type="button"
            class="shrink-0 rounded opacity-80 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            aria-label="Tutup notifikasi"
            @click="ui.dismissToast(t.id)"
          >
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
