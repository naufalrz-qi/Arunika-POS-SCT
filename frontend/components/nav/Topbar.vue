<script setup>
import { useUiStore } from "@/stores/ui";
import Icon from "./Icon.vue";
import UserMenu from "./UserMenu.vue";
import ConnectionMenu from "./ConnectionMenu.vue";

const props = defineProps({
  title: { type: String, default: "" },
});

const ui = useUiStore();
</script>

<template>
  <header class="flex h-16 items-center justify-between border-b border-border-default bg-surface px-4 sm:px-6">
    <div class="flex items-center gap-3">
      <button class="rounded-lg p-2 text-ink-muted hover:bg-surface-3" @click="ui.toggleSidebar()">
        <Icon name="menu" />
      </button>
      <h1 class="text-lg font-semibold text-ink">{{ title }}</h1>
    </div>

    <div class="flex items-center gap-3">
      <button class="rounded-lg p-2 text-ink-muted hover:bg-surface-3" @click="ui.toggleTheme()" title="Toggle theme">
        <Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" />
      </button>
      <ConnectionMenu />
      <UserMenu />
    </div>
  </header>
</template>
