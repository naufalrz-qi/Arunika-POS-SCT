<script setup>
import { computed, ref } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUiStore } from "@/stores/ui";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";
import NavTree from "./NavTree.vue";

const ui = useUiStore();
const { sidebarCollapsed: ciutTersimpan } = storeToRefs(ui);
const { tabs, activeTab, lipat, itemAktif } = useNav();
const page = usePage();

// Mode kasir: di layar /kasir/* sidebar selalu mulai ciut. Layar itu grid
// entri barang yang butuh setiap piksel lebar, dan kasir tak berpindah menu di
// tengah transaksi. Membukanya hanya berlaku untuk kunjungan ini (AdminLayout
// dipasang ulang tiap halaman) dan tak menimpa pilihan tersimpan di laporan.
const layarKasir = computed(() => page.url.startsWith("/kasir/"));
const bukaDiKasir = ref(false);
const sidebarCollapsed = computed(() => (layarKasir.value ? !bukaDiKasir.value : ciutTersimpan.value));
function toggle() {
  if (layarKasir.value) bukaDiKasir.value = !bukaDiKasir.value;
  else ui.toggleSidebar();
}

const railItem =
  "flex h-9 w-9 items-center justify-center rounded-control transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
</script>

<template>
  <!-- Satu-satunya navigasi di desktop. Dulu grup menu tinggal di baris tab
       header dan isinya di sidebar ini — dua tempat untuk satu pilihan, dan
       satu baris header yang memakan tinggi tabel di setiap halaman. -->
  <aside
    :class="[
      'hidden shrink-0 flex-col border-r border-border-default bg-surface transition-[width] duration-200 lg:flex',
      sidebarCollapsed ? 'w-16' : 'w-64',
    ]"
  >
    <Link
      href="/admin-panel/dashboard"
      :class="['flex h-14 shrink-0 items-center gap-2.5', sidebarCollapsed ? 'justify-center' : 'px-5']"
    >
      <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-ink text-surface">
        <Icon name="crown" size="h-4 w-4" />
      </span>
      <span v-if="!sidebarCollapsed" class="truncate text-sm font-semibold tracking-tight text-ink">
        Sukses Crown Toys
      </span>
    </Link>

    <div class="scroll-slim min-h-0 flex-1 overflow-y-auto px-3 py-2">
      <NavTree v-if="!sidebarCollapsed" />

      <!-- Ciut: ikon grup (klik = menu pertama grup itu, seperti tab dulu),
           lalu ikon menu grup yang aktif. Tak ada tujuan yang hilang. -->
      <div v-else class="flex flex-col items-center gap-1">
        <Link
          v-for="tab in tabs"
          :key="tab.key"
          :href="tab.items[0].href"
          :title="tab.label"
          :aria-label="tab.label"
          :class="[
            railItem,
            activeTab?.key === tab.key ? 'bg-surface-3 text-ink' : 'text-ink-muted hover:bg-surface-3 hover:text-ink',
          ]"
        >
          <Icon :name="tab.icon" size="h-4 w-4" />
        </Link>
        <template v-if="activeTab">
          <div class="my-2 w-6 border-t border-border-default" />
          <Link
            v-for="item in activeTab.subsections.flatMap((s) => lipat(s.items))"
            :key="item.key"
            :href="item.href"
            :title="item.label"
            :aria-label="item.label"
            :aria-current="itemAktif(item) ? 'page' : undefined"
            :class="[
              railItem,
              itemAktif(item) ? 'bg-brand-bg text-brand-fg' : 'text-ink-muted hover:bg-surface-3 hover:text-ink',
            ]"
          >
            <Icon :name="item.icon" size="h-4 w-4" />
          </Link>
        </template>
      </div>
    </div>

    <button
      type="button"
      :aria-expanded="!sidebarCollapsed"
      :class="[
        'flex h-11 shrink-0 items-center gap-2.5 border-t border-border-default text-xs text-ink-muted transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-500',
        sidebarCollapsed ? 'justify-center' : 'px-5',
      ]"
      :title="sidebarCollapsed ? 'Perlebar sidebar' : 'Ciutkan sidebar'"
      @click="toggle"
    >
      <Icon
        name="chevron"
        size="h-4 w-4"
        :class="['shrink-0 transition-transform duration-200', sidebarCollapsed ? '-rotate-90' : 'rotate-90']"
      />
      <span v-if="!sidebarCollapsed">Ciutkan</span>
    </button>
  </aside>
</template>
