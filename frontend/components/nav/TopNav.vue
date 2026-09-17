<script setup>
import { computed, ref, watch } from "vue";
import { Link, usePage } from "@inertiajs/vue3";
import { useNav } from "@/composables/useNav";
import Icon from "./Icon.vue";
import NavTree from "./NavTree.vue";
import CommandPalette from "./CommandPalette.vue";
import UserMenu from "./UserMenu.vue";
import NotifMenu from "./NotifMenu.vue";
import ConnectionMenu from "./ConnectionMenu.vue";

const page = usePage();
const { activeTab, activeSection, lipatanAktif, isActive } = useNav();

// Jejak "Laporan / Penjualan". Grup yang isinya satu bagian bernama sama
// (Ringkasan / Ringkasan) cukup ditulis sekali. Di bawah hub, "Pengaturan"
// ikut sebagai tautan kembali ke halaman kartunya.
const crumbs = computed(() => {
  const out = [activeTab.value?.label, activeSection.value?.label]
    .filter((label, i, all) => label && all.indexOf(label) === i)
    .map((label) => ({ label }));
  const l = lipatanAktif.value;
  if (l?.hub) out.push({ label: l.label, href: l.href, sini: isActive(l.href) && !l.anggota.some((a) => a.aktif) });
  return out;
});

const drawerOpen = ref(false);
watch(
  () => page.url,
  () => {
    drawerOpen.value = false;
  },
);

const iconButton =
  "flex h-9 w-9 items-center justify-center rounded-control text-ink-muted transition-colors hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
</script>

<template>
  <!-- Satu baris. Grup menu pindah ke sidebar, jadi header tinggal konteks di
       kiri dan aksi akun di kanan. -->
  <header class="relative z-50 flex h-14 shrink-0 items-center gap-3 border-b border-border-default bg-surface px-3 sm:px-5">
    <button
      :class="[iconButton, 'lg:hidden']"
      title="Menu"
      aria-label="Buka menu navigasi"
      :aria-expanded="drawerOpen"
      @click="drawerOpen = true"
    >
      <Icon name="menu" />
    </button>
    <Link href="/admin-panel/dashboard" class="flex items-center gap-2 lg:hidden">
      <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-ink text-surface">
        <Icon name="crown" size="h-4 w-4" />
      </span>
    </Link>

    <nav v-if="crumbs.length" aria-label="Lokasi" class="hidden min-w-0 items-center gap-1.5 text-sm sm:flex">
      <template v-for="(c, i) in crumbs" :key="c.label">
        <span v-if="i" class="text-ink-subtle">/</span>
        <Link v-if="c.href && !c.sini" :href="c.href" class="truncate text-ink hover:text-brand-fg">{{ c.label }}</Link>
        <span v-else :class="['truncate', i === crumbs.length - 1 ? 'text-ink' : 'text-ink-muted']">{{ c.label }}</span>
      </template>
    </nav>

    <div class="ml-auto flex items-center gap-1.5">
      <CommandPalette />
      <NotifMenu />
      <ConnectionMenu />
      <UserMenu />
    </div>

    <!-- Mobile drawer -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="opacity-0"
      >
        <div v-if="drawerOpen" class="fixed inset-0 z-[70] lg:hidden">
          <div class="absolute inset-0 bg-black/40" @click="drawerOpen = false" />
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
              <div class="flex h-14 shrink-0 items-center justify-between px-5">
                <span class="text-sm font-semibold tracking-tight text-ink">Sukses Crown Toys</span>
                <button :class="iconButton" aria-label="Tutup menu" @click="drawerOpen = false">
                  <Icon name="close" />
                </button>
              </div>
              <div class="scroll-slim flex-1 overflow-y-auto px-3 pb-4">
                <NavTree />
              </div>
            </aside>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </header>
</template>
