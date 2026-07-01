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
  warning: "bg-warning-600",
  info: "bg-brand-600",
};
</script>

<template>
  <Teleport to="body">
    <div class="fixed right-4 top-4 z-[60] flex w-80 flex-col gap-2">
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
          <button class="opacity-80 hover:opacity-100" @click="ui.dismissToast(t.id)">✕</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
