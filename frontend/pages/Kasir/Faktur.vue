<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import { router, Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Banner from "@/components/ui/Banner.vue";
import Button from "@/components/ui/Button.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import NotaCetak from "@/pages/Kasir/NotaCetak.vue";

// Cetak ulang faktur. Satu isian saja — nomor transaksi — karena itulah yang
// dipegang orang yang datang membawa lembar nota di tangan.
const props = defineProps({
  hasil: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
});

const isi = computed(() => props.hasil || {});
const no = ref(props.filters.no || "");
const kotak = ref(null);

function cari() {
  const q = no.value.trim();
  if (!q) return;
  router.get("/kasir/faktur", { no: q }, { preserveState: true, preserveScroll: true });
}

onMounted(() => nextTick(() => kotak.value?.focus?.()));
</script>

<template>
  <AdminLayout title="Cetak Faktur">
    <Card class="mb-4">
      <label class="mb-1 block text-xs font-medium text-ink-muted">
        No. Transaksi <span class="text-ink-subtle">(Enter untuk mencari)</span>
      </label>
      <div class="flex gap-2">
        <input
          ref="kotak"
          v-model="no"
          class="w-full max-w-sm rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg uppercase"
          placeholder="mis. SC2608070001"
          @keydown.enter.prevent="cari"
        />
        <Button :disabled="!no.trim()" @click="cari">Tampilkan</Button>
      </div>
    </Card>

    <Deferred data="hasil">
      <template #fallback><LoadingCard message="Mencari nota…" /></template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />
      <Banner v-else-if="isi.pesan" variant="warning" :message="isi.pesan" class="mb-4" />

      <!-- Fakturnya dirender di sini, bukan dengan membuka halaman cetak nota:
           rute itu milik menu Penjualan, jadi orang yang cuma dipegangi menu
           Cetak Faktur akan terpental darinya. `auto` mati supaya dialog cetak
           tak menyembul sendiri setiap kali hasil berganti. -->
      <Card v-if="isi.nota">
        <div class="faktur-cetak">
          <NotaCetak :nota="isi.nota" :auto="false" />
        </div>
      </Card>
    </Deferred>
  </AdminLayout>
</template>

<!-- Sengaja TIDAK scoped: yang harus disembunyikan saat mencetak adalah
     sidebar dan navbar milik AdminLayout, dan gaya ber-scope tak sampai ke
     sana. Tanpa ini lembar pertama keluar berisi menu, bukan faktur. -->
<style>
@media print {
  body * {
    visibility: hidden;
  }
  .faktur-cetak,
  .faktur-cetak * {
    visibility: visible;
  }
  .faktur-cetak {
    position: absolute;
    left: 0;
    top: 0;
  }
}
</style>
