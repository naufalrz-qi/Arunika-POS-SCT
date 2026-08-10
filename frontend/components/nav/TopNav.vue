<script setup>
import { reactive, ref, watch } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import { useUiStore } from "@/stores/ui";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";
import UserMenu from "./UserMenu.vue";
import NotifMenu from "./NotifMenu.vue";
import ConnectionMenu from "./ConnectionMenu.vue";

const ui = useUiStore();
const page = usePage();
const { tabs, activeTab, isActive } = useNav();

// Mobile drawer with per-tab accordion; the active tab starts open.
const drawerOpen = ref(false);
const openSection = reactive({});
function toggleSection(key) {
  openSection[key] = !openSection[key];
}
watch(drawerOpen, (open) => {
  if (open && activeTab.value) openSection[activeTab.value.key] = true;
});
watch(
  () => page.url,
  () => {
    drawerOpen.value = false;
  },
);
</script>

<template>
  <!-- Rata dengan tepi, satu garis pemisah. Sebelumnya header ini adalah panel
       gelap mengambang dengan bevel bahu (yang butuh lapisan latar terpisah
       karena clip-path ikut memotong dropdown di dalamnya) plus strip
       merah-kuning 3px di bawahnya. -->
  <header class="relative z-50 shrink-0 border-b border-border-default bg-surface">
    <!-- Row 1: brand + actions -->
    <div class="flex h-14 items-center gap-3 px-3 sm:px-4">
      <Link href="/admin-panel/dashboard" class="flex items-center gap-2.5">
        <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-brand-600 text-white">
          <Icon name="crown" size="h-4 w-4" />
        </span>
        <span class="hidden text-sm font-semibold text-ink sm:block">
          Sukses Crown Toys
        </span>
      </Link>

      <div class="ml-auto flex items-center gap-1">
        <button
          class="flex h-9 w-9 items-center justify-center rounded-control text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
          :title="ui.theme === 'dark' ? 'Ganti ke tema terang' : 'Ganti ke tema gelap'"
          @click="ui.toggleTheme()"
        >
          <Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" />
        </button>
        <NotifMenu />
        <ConnectionMenu />
        <UserMenu />
        <button
          class="flex h-9 w-9 items-center justify-center rounded-control text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink lg:hidden"
          title="Menu"
          aria-label="Buka menu navigasi"
          :aria-expanded="drawerOpen"
          @click="drawerOpen = true"
        >
          <Icon name="menu" />
        </button>
      </div>
    </div>

    <!-- Row 2: section tabs (desktop). Click goes to the section's first menu. -->
    <nav class="hidden items-stretch border-t border-border-default px-3 sm:px-4 lg:flex">
      <Link
        v-for="tab in tabs"
        :key="tab.key"
        :href="tab.items[0].href"
        :class="[
          'relative px-3 py-2 text-sm transition-colors',
          activeTab?.key === tab.key
            ? 'font-medium text-ink'
            : 'text-ink-muted hover:text-ink',
        ]"
      >
        {{ tab.label }}
        <span
          v-if="activeTab?.key === tab.key"
          class="absolute inset-x-3 bottom-0 h-0.5 bg-brand-500"
        />
      </Link>
    </nav>

    <!-- Mobile drawer -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="opacity-0"
      >
        <div v-if="drawerOpen" class="fixed inset-0 z-[70] lg:hidden">
          <div class="absolute inset-0 bg-ink/40" @click="drawerOpen = false" />
          <Transition
            enter-active-class="transition duration-200 ease-out"
            enter-from-class="-translate-x-full"
            leave-active-class="transition duration-150 ease-in"
            leave-to-class="-translate-x-full"
          >
            <aside
              v-if="drawerOpen"
              class="absolute left-0 top-0 flex h-full w-72 max-w-[85%] flex-col border-r border-border-default bg-surface"
            >
              <div class="flex h-14 shrink-0 items-center justify-between border-b border-border-default px-3">
                <span class="text-sm font-semibold text-ink">Sukses Crown Toys</span>
                <button
                  class="rounded-control p-2 text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
                  aria-label="Tutup menu"
                  @click="drawerOpen = false"
                >
                  <Icon name="close" />
                </button>
              </div>
              <nav class="scroll-slim flex-1 overflow-y-auto px-2 py-3">
                <div v-for="tab in tabs" :key="tab.key" class="mb-1">
                  <button
                    type="button"
                    class="flex w-full items-center justify-between rounded-control px-2.5 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface-2"
                    :aria-expanded="!!openSection[tab.key]"
                    @click="toggleSection(tab.key)"
                  >
                    <span>{{ tab.label }}</span>
                    <Icon
                      name="chevron"
                      size="h-4 w-4"
                      :class="['text-ink-subtle transition-transform duration-200', openSection[tab.key] ? '' : '-rotate-90']"
                    />
                  </button>
                  <div v-show="openSection[tab.key]" class="ml-3 mt-0.5 space-y-0.5 border-l border-border-default pl-2">
                    <template v-for="sub in tab.subsections" :key="sub.key">
                      <p
                        v-if="tab.subsections.length > 1"
                        class="px-2.5 pb-1 pt-2 text-xs text-ink-subtle"
                      >
                        {{ sub.label }}
                      </p>
                      <Link
                        v-for="item in sub.items"
                        :key="item.key"
                        :href="item.href"
                        :class="[
                          'flex items-center gap-2.5 rounded-control px-2.5 py-1.5 text-sm transition-colors',
                          isActive(item.href)
                            ? 'bg-brand-bg font-medium text-brand-fg'
                            : 'text-ink-muted hover:bg-surface-2 hover:text-ink',
                        ]"
                      >
                        <Icon :name="item.icon" size="h-4 w-4" class="shrink-0" />
                        <span class="truncate">{{ item.label }}</span>
                      </Link>
                    </template>
                  </div>
                </div>
              </nav>
            </aside>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </header>
</template>
