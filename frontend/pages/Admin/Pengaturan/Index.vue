<script setup>
import { computed } from "vue";
import { Link } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Icon from "@/components/nav/Icon.vue";
import { useNav } from "@/composables/useNav";

// Halaman induk menu yang jarang dibuka. Daftarnya dari lipatan "pengaturan"
// di useNav.js, disaring ke menu yang diberikan ke akun ini — jadi halaman ini
// tak pernah menawarkan layar yang akan menolak pembukanya.
const { anggotaDari } = useNav();
const daftar = computed(() => anggotaDari("pengaturan"));
</script>

<template>
  <AdminLayout title="Pengaturan">
    <p v-if="!daftar.length" class="text-sm text-ink-muted">Belum ada pengaturan yang dibuka untuk akun Anda.</p>
    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <Link
        v-for="m in daftar"
        :key="m.key"
        :href="m.href"
        class="surface-flat group flex items-start gap-3 p-4 transition-colors hover:border-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        <span
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-3 text-ink-muted transition-colors group-hover:bg-brand-bg group-hover:text-brand-fg"
        >
          <Icon :name="m.icon" size="h-4 w-4" />
        </span>
        <span class="min-w-0">
          <span class="block text-sm font-medium text-ink">{{ m.label }}</span>
          <span class="mt-0.5 block text-xs text-ink-muted">{{ m.keterangan }}</span>
        </span>
      </Link>
    </div>
  </AdminLayout>
</template>
