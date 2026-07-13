import { computed } from "vue";
import { usePage } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";

// Display labels per section group. Keep in sync with apps/core/menus.py.
const SECTION_LABELS = {
  ringkasan: "Ringkasan",
  penjualan: "Penjualan",
  pembelian: "Pembelian",
  stok: "Inventori & Stok",
  analitik: "Analitik",
  promo: "Promo & Voucher",
  kas: "Kas & Shift",
  master: "Master Data",
  master_harga: "Harga & Update Barang",
  master_sync: "Sinkronisasi",
  admin: "Administrasi",
};

// Navbar tabs: backend sections consolidated into 5 groups so the tab row
// stays airy; the original sections become sub-headers in the sidebar.
const NAV_GROUPS = [
  { key: "ringkasan", label: "Ringkasan", sections: ["ringkasan"] },
  { key: "laporan", label: "Laporan", sections: ["penjualan", "pembelian", "analitik"] },
  { key: "operasional", label: "Operasional", sections: ["stok", "promo", "kas"] },
  { key: "master", label: "Master Data", sections: ["master", "master_harga", "master_sync"] },
  { key: "admin", label: "Administrasi", sections: ["admin"] },
];

// Single source for nav logic: section grouping + active-state matching.
export function useNav() {
  const page = usePage();
  const { allowedMenus } = storeToRefs(useUserStore());

  const currentPath = computed(() =>
    page.url.split(/[?#]/)[0].replace(/\/+$/, ""),
  );

  // Segment-boundary match so /laporan/penjualan doesn't stay active on
  // /laporan/penjualan-periode.
  function isActive(href) {
    const h = href.replace(/\/+$/, "");
    return currentPath.value === h || currentPath.value.startsWith(h + "/");
  }

  // Group the (already RBAC-filtered) menus by section, preserving arrival
  // order. Items without a section fall back to "ringkasan".
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

  // Section containing the current page; falls back to the first section so
  // the sidebar is never empty on unknown routes (e.g. /admin-panel/profile).
  const activeSection = computed(
    () =>
      sections.value.find((s) => s.items.some((it) => isActive(it.href))) ??
      sections.value[0] ??
      null,
  );

  // Navbar tabs: NAV_GROUPS with only the (RBAC-visible) sections present;
  // sections outside NAV_GROUPS get their own tab so nothing silently vanishes.
  const tabs = computed(() => {
    const byKey = Object.fromEntries(sections.value.map((s) => [s.key, s]));
    const grouped = new Set(NAV_GROUPS.flatMap((g) => g.sections));
    const out = NAV_GROUPS.map((g) => {
      const subsections = g.sections.map((k) => byKey[k]).filter(Boolean);
      return {
        key: g.key,
        label: g.label,
        subsections,
        items: subsections.flatMap((s) => s.items),
      };
    }).filter((t) => t.items.length);
    for (const s of sections.value) {
      if (!grouped.has(s.key)) {
        out.push({ key: s.key, label: s.label, subsections: [s], items: s.items });
      }
    }
    return out;
  });

  const activeTab = computed(
    () =>
      tabs.value.find((t) => t.subsections.includes(activeSection.value)) ??
      tabs.value[0] ??
      null,
  );

  return { sections, tabs, activeSection, activeTab, isActive };
}
