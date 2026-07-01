<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";
import { useUserStore } from "@/stores/user";
import SidebarSection from "./SidebarSection.vue";
import Icon from "./Icon.vue";

const ui = useUiStore();
const { sidebarCollapsed } = storeToRefs(ui);
const userStore = useUserStore();
const { allowedMenus } = storeToRefs(userStore);

// Display labels for each section group (keep in sync with apps/core/menus.py).
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

// Group the (already RBAC-filtered) menus by their `section`, preserving the
// order they arrive in. Items without a section fall back to "ringkasan".
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
</script>

<template>
  <aside
    :class="[
      'flex h-screen flex-col bg-sidebar transition-all duration-200',
      sidebarCollapsed ? 'w-16' : 'w-64',
    ]"
  >
    <div class="flex h-16 items-center gap-2.5 px-4">
      <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm">
        <Icon name="crown" size="h-5 w-5" />
      </div>
      <span v-if="!sidebarCollapsed" class="text-base font-semibold leading-tight text-white">
        Sukses<br /><span class="text-brand-200">Crown Toys</span>
      </span>
    </div>

    <nav class="flex-1 space-y-3 overflow-y-auto px-3 py-4">
      <SidebarSection
        v-for="section in sections"
        :key="section.key"
        :section-key="section.key"
        :label="section.label"
        :items="section.items"
        :collapsed="sidebarCollapsed"
      />
    </nav>

    <div v-if="!sidebarCollapsed" class="px-4 py-3 text-xs text-white/50">
      Sukses Crown Toys • Admin
    </div>
  </aside>
</template>
