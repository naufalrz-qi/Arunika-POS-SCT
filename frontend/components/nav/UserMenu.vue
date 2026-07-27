<script setup>
import { Link } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";
import { useDismissable } from "@/composables/useDismissable";
import { ROLE_LABELS } from "@/utils/labels";
import Icon from "./Icon.vue";

const userStore = useUserStore();
const { user } = storeToRefs(userStore);
const { open, root, close, toggle } = useDismissable();
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="flex h-10 items-center gap-2.5 rounded-control border border-white/10 bg-white/5 pl-1.5 pr-3 text-white transition-all duration-200 hover:border-white/20 hover:bg-white/10"
      :aria-expanded="open"
      aria-haspopup="menu"
      aria-label="Menu pengguna"
      @click="toggle"
    >
      <div class="flex h-7 w-7 items-center justify-center rounded-full bg-brand-500 font-heading text-xs font-bold uppercase text-white">
        {{ (user?.name || "?").charAt(0) }}
      </div>
      <div class="hidden text-left sm:block">
        <p class="text-xs font-bold leading-none tracking-wide text-white">{{ user?.name }}</p>
        <p class="text-[10px] uppercase tracking-wider text-white/60 mt-0.5">{{ ROLE_LABELS[user?.role] || user?.role }}</p>
      </div>
    </button>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="opacity-0 scale-95"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="open"
        class="absolute right-0 mt-2 w-48 overflow-hidden rounded-control border border-border-default bg-surface shadow-lg"
      >
        <Link
          href="/admin-panel/profile"
          class="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-ink hover:bg-surface-3"
        >
          <Icon name="user" size="h-4 w-4" /> Profil Saya
        </Link>
        <Link
          href="/logout"
          method="post"
          as="button"
          class="flex w-full items-center gap-2 border-t border-border-default px-4 py-2.5 text-left text-sm text-danger-600 hover:bg-danger-bg"
        >
          <Icon name="logout" size="h-4 w-4" /> Keluar
        </Link>
      </div>
    </Transition>
  </div>
</template>
