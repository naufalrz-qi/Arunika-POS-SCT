<script setup>
import { Link } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";

const ui = useUiStore();
const { sidebarCollapsed } = storeToRefs(ui);
const { activeTab, isActive } = useNav();
</script>

<template>
  <!-- Sidebar dulu berupa panel gelap yang mengambang dengan jarak dari tepi,
       bevel bahu, dan bayangannya sendiri — satu-satunya benda gelap di
       halaman yang selebihnya terang, jadi mata tertarik ke sana lebih dulu
       daripada ke tabel. Sekarang ia permukaan yang sama dengan halaman,
       dipisahkan satu garis. -->
  <aside
    v-if="activeTab"
    :class="[
      'hidden shrink-0 flex-col border-r border-border-default bg-surface transition-[width] duration-200 lg:flex',
      sidebarCollapsed ? 'w-14' : 'w-60',
    ]"
  >
    <p
      v-if="!sidebarCollapsed"
      class="px-4 pb-1 pt-4 text-xs font-semibold text-ink-subtle"
    >
      {{ activeTab.label }}
    </p>
    <div v-else class="pt-4" />

    <nav class="scroll-slim flex-1 overflow-y-auto px-2 pb-3">
      <template v-for="(sub, i) in activeTab.subsections" :key="sub.key">
        <p
          v-if="!sidebarCollapsed && activeTab.subsections.length > 1"
          class="px-2 pb-1 pt-3 text-xs text-ink-subtle"
        >
          {{ sub.label }}
        </p>
        <div
          v-else-if="sidebarCollapsed && activeTab.subsections.length > 1 && i > 0"
          class="mx-2 my-2 border-t border-border-default"
        />
        <div class="space-y-0.5">
          <Link
            v-for="item in sub.items"
            :key="item.key"
            :href="item.href"
            :title="sidebarCollapsed ? item.label : undefined"
            :class="[
              'group flex items-center gap-2.5 rounded-control py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
              sidebarCollapsed ? 'justify-center px-0' : 'px-2.5',
              isActive(item.href)
                ? 'bg-brand-bg font-medium text-brand-fg'
                : 'text-ink-muted hover:bg-surface-2 hover:text-ink',
            ]"
          >
            <Icon :name="item.icon" size="h-4 w-4" class="shrink-0" />
            <span v-if="!sidebarCollapsed" class="truncate">{{ item.label }}</span>
          </Link>
        </div>
      </template>
    </nav>

    <button
      type="button"
      :aria-expanded="!sidebarCollapsed"
      class="flex items-center gap-2.5 border-t border-border-default px-4 py-3 text-xs text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      :class="sidebarCollapsed ? 'justify-center px-0' : ''"
      :title="sidebarCollapsed ? 'Perlebar sidebar' : 'Ciutkan sidebar'"
      @click="ui.toggleSidebar()"
    >
      <Icon
        name="chevron"
        size="h-4 w-4"
        :class="['shrink-0 transition-transform duration-200', sidebarCollapsed ? '-rotate-90' : 'rotate-90']"
      />
      <span v-if="!sidebarCollapsed">Ciutkan panel</span>
    </button>
  </aside>
</template>
