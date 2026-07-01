<script setup>
import { ref } from "vue";
import { Link } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";
import Icon from "./Icon.vue";

const userStore = useUserStore();
const { user } = storeToRefs(userStore);
const open = ref(false);
</script>

<template>
  <div class="relative">
    <button
      class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-white transition hover:bg-white/10"
      @click="open = !open"
      @blur="open = false"
    >
      <div class="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white">
        {{ (user?.name || "?").charAt(0) }}
      </div>
      <div class="hidden text-left sm:block">
        <p class="text-sm font-medium leading-tight text-white">{{ user?.name }}</p>
        <p class="text-xs capitalize text-white/60">{{ user?.role }}</p>
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
        class="absolute right-0 mt-2 w-48 overflow-hidden rounded-lg border border-border-default bg-surface shadow-lg"
        @mousedown.prevent
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
