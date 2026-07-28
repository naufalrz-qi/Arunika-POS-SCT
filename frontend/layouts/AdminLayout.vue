<script setup>
import { Head } from "@inertiajs/vue3";
import TopNav from "@/components/nav/TopNav.vue";
import SideNav from "@/components/nav/SideNav.vue";
import ToastContainer from "@/components/ui/ToastContainer.vue";
import { useNav } from "@/composables/useNav";

defineProps({
  title: { type: String, default: "" },
});

const { activeSection } = useNav();
</script>

<template>
  <!-- Judul tab mengikuti judul halaman; formatnya diatur sekali di main.js.
       AdminLayout satu-satunya pemilik judul (lihat <h1> di bawah), jadi di
       sini pula tempatnya diteruskan ke <title>. -->
  <Head v-if="title" :title="title" />
  <!-- 100dvh, bukan 100vh: di browser ponsel 100vh termasuk area yang tertutup
       toolbar, jadi baris terbawah (footer tabel: pemilih per-halaman dan
       paginasi) tersembunyi di balik chrome browser. -->
  <div class="flex h-[100dvh] flex-col overflow-hidden bg-surface-2">
    <TopNav />
    <div class="flex min-h-0 flex-1">
      <SideNav />
      <main class="scroll-slim min-w-0 flex-1 overflow-y-auto">
        <div class="page-enter mx-auto max-w-[1600px] p-3 sm:p-4 lg:p-6">
          <!-- Judul halaman: nama bagian sebagai konteks, lalu judulnya.
               Sebelumnya baris ini juga membawa "// " di depan nama bagian dan
               tiga kotak merah/kuning/biru berdenyut di sisi kanan — hiasan
               yang tak menunjuk apa pun, di baris yang dibaca paling sering. -->
          <div v-if="title" class="mb-4">
            <p v-if="activeSection" class="text-xs text-ink-subtle">
              {{ activeSection.label }}
            </p>
            <h1 class="mt-0.5 text-xl font-semibold tracking-tight text-ink">{{ title }}</h1>
          </div>
          <slot />
        </div>
      </main>
    </div>
    <ToastContainer />
  </div>
</template>
