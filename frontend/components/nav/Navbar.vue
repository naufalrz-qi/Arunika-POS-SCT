<script setup>
import { computed, reactive, ref } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";
import { useUserStore } from "@/stores/user";
import NavDropdown from "./NavDropdown.vue";
import Icon from "./Icon.vue";
import UserMenu from "./UserMenu.vue";
import ConnectionMenu from "./ConnectionMenu.vue";

defineProps({
  title: { type: String, default: "" },
});

const ui = useUiStore();
const userStore = useUserStore();
const { allowedMenus } = storeToRefs(userStore);
const page = usePage();

// Keep in sync with apps/core/menus.py.
const SECTION_LABELS = {
  ringkasan: "Ringkasan",
  penjualan: "Penjualan",
  pembelian: "Pembelian",
  stok: "Inventori & Stok",
  analitik: "Analitik",
  promo: "Promo & Voucher",
  kas: "Kas & Shift",
  master: "Master Data",
  admin: "Administrasi",
};

// Group the (already RBAC-filtered) menus by section, preserving arrival order.
const sections = computed(() => {
  const groups = [];
  const byKey = {};
  for (const item of allowedMenus.value) {
    const key = item.section || "ringkasan";
    if (!byKey[key]) {
      byKey[key] = { key, label: SECTION_LABELS[key] || key, items: [] };
      groups.push(byKey[key]);
    }
    byKey[key].items.push(item);
  }
  return groups;
});

const currentPath = computed(() => page.url.split(/[?#]/)[0].replace(/\/+$/, ""));
function isActive(href) {
  const h = href.replace(/\/+$/, "");
  return currentPath.value === h || currentPath.value.startsWith(h + "/");
}

// Mobile drawer + per-section accordion (default closed → "collapsed semua").
const drawerOpen = ref(false);
const openSection = reactive({});
function toggleSection(key) {
  openSection[key] = !openSection[key];
}
</script>

<template>
  <header class="bg-sidebar">
    <!-- Row 1: brand + actions -->
    <div class="flex h-16 items-center gap-3 px-4 sm:px-6">
      <Link href="/admin-panel/dashboard" class="flex items-center gap-2.5">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm">
          <Icon name="crown" size="h-5 w-5" />
        </div>
        <span class="hidden text-base font-semibold leading-tight text-white sm:block">
          Sukses <span class="text-brand-200">Crown Toys</span>
        </span>
      </Link>

      <div class="ml-auto flex items-center gap-2 sm:gap-3">
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

    <!-- Row 2: section dropdowns (desktop) -->
    <nav class="hidden flex-wrap items-center gap-1 border-t border-white/10 px-4 py-1.5 sm:px-6 lg:flex">
      <NavDropdown
        v-for="section in sections"
        :key="section.key"
        :label="section.label"
        :items="section.items"
      />
    </nav>

    <!-- RX-78-2 chest-vent + V-fin accent strip (always visible). -->
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
              <div class="flex h-16 shrink-0 items-center justify-between px-4">
                <span class="text-base font-semibold text-white">
                  Sukses <span class="text-brand-200">Crown Toys</span>
                </span>
                <button class="rounded-lg p-2 text-white/70 hover:bg-white/10" @click="drawerOpen = false">
                  <Icon name="close" />
                </button>
              </div>
              <nav class="flex-1 overflow-y-auto px-3 py-2">
                <div v-for="section in sections" :key="section.key" class="mb-1">
                  <button
                    type="button"
                    class="flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-semibold text-white/80 transition hover:bg-white/10"
                    @click="toggleSection(section.key)"
                  >
                    <span>{{ section.label }}</span>
                    <Icon
                      name="chevron"
                      size="h-4 w-4"
                      :class="['transition-transform duration-200', openSection[section.key] ? '' : '-rotate-90']"
                    />
                  </button>
                  <div v-show="openSection[section.key]" class="mt-0.5 space-y-0.5 pl-2">
                    <Link
                      v-for="item in section.items"
                      :key="item.key"
                      :href="item.href"
                      :class="[
                        'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition',
                        isActive(item.href)
                          ? 'bg-brand-600 text-white'
                          : 'text-white/60 hover:bg-white/10 hover:text-white',
                      ]"
                      @click="drawerOpen = false"
                    >
                      <Icon :name="item.icon" size="h-4 w-4" />
                      <span class="truncate">{{ item.label }}</span>
                    </Link>
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
