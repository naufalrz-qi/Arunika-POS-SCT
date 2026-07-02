<script setup>
import { reactive, ref, watch } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import { useUiStore } from "@/stores/ui";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";
import UserMenu from "./UserMenu.vue";
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
  <header class="shrink-0 bg-sidebar">
    <!-- Row 1: brand + actions -->
    <div class="flex h-14 items-center gap-3 px-4 sm:px-6">
      <Link href="/admin-panel/dashboard" class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm">
          <Icon name="crown" size="h-4.5 w-4.5" />
        </div>
        <span class="hidden text-sm font-semibold leading-tight text-white sm:block">
          Sukses <span class="text-brand-200">Crown Toys</span>
        </span>
      </Link>

      <div class="ml-auto flex items-center gap-1.5 sm:gap-2">
        <button
          class="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white"
          title="Ganti tema"
          @click="ui.toggleTheme()"
        >
          <Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" />
        </button>
        <ConnectionMenu />
        <UserMenu />
        <button
          class="rounded-lg p-2 text-white/70 transition hover:bg-white/10 hover:text-white lg:hidden"
          title="Menu"
          @click="drawerOpen = true"
        >
          <Icon name="menu" />
        </button>
      </div>
    </div>

    <!-- Row 2: section tabs (desktop). Click goes to the section's first menu;
         the active tab wears the RX-78-2 V-fin tick. -->
    <nav class="hidden items-stretch gap-1 border-t border-white/10 px-4 sm:px-6 lg:flex">
      <Link
        v-for="tab in tabs"
        :key="tab.key"
        :href="tab.items[0].href"
        :class="[
          'relative px-3 py-2 text-sm font-medium transition',
          activeTab?.key === tab.key
            ? 'text-white'
            : 'text-white/55 hover:bg-white/5 hover:text-white',
        ]"
      >
        {{ tab.label }}
        <span
          v-if="activeTab?.key === tab.key"
          class="vfin absolute bottom-0 left-1/2 h-1.5 w-5 -translate-x-1/2"
        />
      </Link>
    </nav>

    <!-- RX-78-2 chest-vent accent strip -->
    <div class="panel-strip h-[3px]" />

    <!-- Mobile drawer -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0"
        leave-active-class="transition duration-100 ease-in"
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
              class="absolute left-0 top-0 flex h-full w-80 max-w-[85%] flex-col bg-sidebar shadow-xl"
            >
              <div class="flex h-14 shrink-0 items-center justify-between px-4">
                <span class="text-sm font-semibold text-white">
                  Sukses <span class="text-brand-200">Crown Toys</span>
                </span>
                <button class="rounded-lg p-2 text-white/70 hover:bg-white/10" @click="drawerOpen = false">
                  <Icon name="close" />
                </button>
              </div>
              <div class="panel-strip h-[3px] shrink-0" />
              <nav class="scroll-slim flex-1 overflow-y-auto px-3 py-2">
                <div v-for="tab in tabs" :key="tab.key" class="mb-1">
                  <button
                    type="button"
                    class="flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-semibold text-white/80 transition hover:bg-white/10"
                    @click="toggleSection(tab.key)"
                  >
                    <span>{{ tab.label }}</span>
                    <Icon
                      name="chevron"
                      size="h-4 w-4"
                      :class="['transition-transform duration-200', openSection[tab.key] ? '' : '-rotate-90']"
                    />
                  </button>
                  <div v-show="openSection[tab.key]" class="mt-0.5 space-y-0.5 pl-2">
                    <template v-for="sub in tab.subsections" :key="sub.key">
                      <p
                        v-if="tab.subsections.length > 1"
                        class="px-3 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-white/35"
                      >
                        {{ sub.label }}
                      </p>
                      <Link
                        v-for="item in sub.items"
                        :key="item.key"
                        :href="item.href"
                        :class="[
                          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition',
                          isActive(item.href)
                            ? 'bg-brand-600 text-white'
                            : 'text-white/60 hover:bg-white/10 hover:text-white',
                        ]"
                      >
                        <Icon :name="item.icon" size="h-4 w-4" />
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
