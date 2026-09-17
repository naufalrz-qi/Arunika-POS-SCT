<script setup>
import { computed } from "vue";
import { Head, Link } from "@inertiajs/vue3";
import TopNav from "@/components/nav/TopNav.vue";
import SideNav from "@/components/nav/SideNav.vue";
import ToastContainer from "@/components/ui/ToastContainer.vue";
import { useNav } from "@/composables/useNav";

const props = defineProps({
  title: { type: String, default: "" },
});

// Halaman yang menunya dilipat di sidebar (lihat LIPATAN di useNav.js) memakai
// nama lipatannya sebagai judul, dan anggota lain yang diberikan tampil sebagai
// tab. <title> tetap judul halaman itu sendiri, supaya tab peramban tetap
// membedakan "Penjualan per Nota" dari "Penjualan per User".
const { lipatanAktif } = useNav();
const tabHalaman = computed(() => (lipatanAktif.value && !lipatanAktif.value.hub ? lipatanAktif.value : null));
const judul = computed(() => (tabHalaman.value ? tabHalaman.value.label : props.title));
</script>

<template>
  <!-- Judul tab mengikuti judul halaman; formatnya diatur sekali di main.js.
       AdminLayout satu-satunya pemilik judul (lihat <h1> di bawah), jadi di
       sini pula tempatnya diteruskan ke <title>. -->
  <Head v-if="title" :title="title" />
  <!-- 100dvh, bukan 100vh: di browser ponsel 100vh termasuk area yang tertutup
       toolbar, jadi baris terbawah (footer tabel: pemilih per-halaman dan
       paginasi) tersembunyi di balik chrome browser. -->
  <div class="flex h-[100dvh] overflow-hidden bg-surface-2">
    <SideNav />
    <div class="flex min-w-0 flex-1 flex-col">
      <TopNav />
      <main class="scroll-slim min-h-0 flex-1 overflow-y-auto">
        <div class="page-enter mx-auto max-w-[1600px] px-3 py-4 sm:px-5 lg:px-8 lg:py-6">
          <!-- Nama bagian tidak lagi ditulis di atas judul: sudah ada di jejak
               header, tepat di atasnya. -->
          <h1 v-if="judul" :class="['text-xl font-semibold tracking-tight text-ink sm:text-2xl', tabHalaman ? 'mb-3' : 'mb-5']">
            {{ judul }}
          </h1>
          <nav
            v-if="tabHalaman"
            :aria-label="`Tampilan ${tabHalaman.label}`"
            class="scroll-slim mb-5 flex overflow-x-auto border-b border-border-default"
          >
            <Link
              v-for="t in tabHalaman.anggota"
              :key="t.key"
              :href="t.href"
              :aria-current="t.aktif ? 'page' : undefined"
              :class="[
                'shrink-0 whitespace-nowrap px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-500',
                t.aktif
                  ? 'font-medium text-ink shadow-[inset_0_-2px_0_var(--color-brand-500)]'
                  : 'text-ink-muted hover:text-ink',
              ]"
            >
              {{ t.keterangan }}
            </Link>
          </nav>
          <slot />
        </div>
      </main>
    </div>
    <ToastContainer />
  </div>
</template>
