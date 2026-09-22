<script setup>
/**
 * Pembaruan Database — menggantikan `manage.py migrate` di rilis rutin.
 *
 * Setup awal tetap lewat terminal: migrasi pertama membuat tabel login itu
 * sendiri. Aturan sasarannya (pangkal penuh, DB Arunika hanya `bisnis`, DB yang
 * belum ada bukan galat) ada di apps/core/migrasi.py.
 *
 * Superadmin-only lewat menus.py; penegakannya di server.
 */
import { computed } from "vue";
import { Deferred, Link, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  data: { type: Object, default: null },
  hasil: { type: Array, default: null },
});
const rows = computed(() => props.data?.rows || []);
const total = computed(() => rows.value.reduce((s, r) => s + r.tertunda.length, 0));

const KEADAAN = {
  ok: { label: "terhubung", variant: "success" },
  belum_ada: { label: "belum dibuat", variant: "neutral" },
  galat: { label: "tak terjangkau", variant: "danger" },
};

const jalan = useForm({});
function terapkan() {
  // Konfirmasi, tidak seperti tombol Cadangan: cadangan tak merusak apa pun,
  // sedangkan ini mengubah skema database produksi dan tak punya tombol batal.
  const n = total.value;
  if (!window.confirm(`Terapkan ${n} migrasi ke database sekarang?\n\n`
    + "Sarannya: cadangkan pangkal dulu di Cadangan & Pemulihan."))
    return;
  jalan.post("/admin-panel/pengaturan/migrasi/jalankan", { preserveScroll: true });
}
</script>

<template>
  <AdminLayout title="Pembaruan Database">
    <div class="space-y-4">
      <!-- Di luar <Deferred> supaya tombolnya ada sejak cat pertama. -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="max-w-3xl text-sm text-ink-muted">
          Sesudah kode baru ditarik dan server dijalankan ulang, skema database-nya
          diterapkan dari sini — pengganti <code>manage.py migrate</code>. Terminal hanya
          perlu untuk pemasangan pertama.
        </p>
        <Button :disabled="jalan.processing || (!!data && total === 0)" @click="terapkan">
          {{ jalan.processing ? "Menerapkan…" : "Terapkan migrasi" }}
        </Button>
      </div>

      <Banner variant="info">
        Migrasi tak punya tombol batal. Sebelum menerapkan,
        <Link href="/admin-panel/pengaturan/cadangan" class="font-medium underline">cadangkan pangkal</Link>
        dulu. Indeks laporan di server legacy bukan migrasi — itu tombol
        <Link href="/admin-panel/connections" class="font-medium underline">Cek Indexing</Link>
        di Kelola Koneksi, sebaiknya di luar jam toko karena membuat indeks mengunci tabelnya.
      </Banner>

      <!-- Hasil klik terakhir. Tampil sekali; muat ulang menghapusnya. -->
      <Card v-if="hasil" title="Hasil penerapan terakhir">
        <ul class="space-y-2 text-sm">
          <li v-for="r in hasil" :key="r.sasaran">
            <!-- Spasi pemisahnya di SINI, bukan di awal tiap cabang: compiler Vue
                 membuang simpul spasi yang jadi anak pertama sebuah elemen, jadi
                 `> {{ n }} diterapkan` tercetak "Pangkal:1 diterapkan". -->
            <span class="font-medium text-ink">{{ r.sasaran }}: </span>
            <span v-if="r.keadaan === 'galat'" class="text-danger-fg">gagal — {{ r.pesan }}</span>
            <span v-else-if="r.keadaan === 'belum_ada'" class="text-ink-muted">dilewati, database belum dibuat</span>
            <span v-else-if="r.diterapkan.length" class="text-ink">{{ r.diterapkan.length }} diterapkan</span>
            <span v-else class="text-ink-muted">tak ada yang tertunda</span>
            <div v-if="r.diterapkan.length" class="mt-0.5 font-mono text-xs text-ink-muted">
              {{ r.diterapkan.join(", ") }}
            </div>
            <!-- Gagal di tengah: sebagian sudah jadi, sisanya tampil apa adanya. -->
            <div v-if="r.keadaan === 'galat' && r.tertunda.length" class="mt-0.5 font-mono text-xs text-danger-fg">
              masih tertunda: {{ r.tertunda.join(", ") }}
            </div>
          </li>
        </ul>
      </Card>

      <Deferred data="data">
        <template #fallback><LoadingCard message="Memeriksa migrasi di tiap database…" /></template>

        <Card>
          <ul class="divide-y divide-border-default">
            <li v-for="r in rows" :key="r.sasaran" class="py-3 first:pt-0 last:pb-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-ink">{{ r.sasaran }}</span>
                <code class="text-xs text-ink-muted">{{ r.db }}</code>
                <Badge :variant="KEADAAN[r.keadaan].variant">{{ KEADAAN[r.keadaan].label }}</Badge>
                <Badge v-if="r.keadaan === 'ok' && r.tertunda.length" variant="warning">
                  {{ r.tertunda.length }} tertunda
                </Badge>
                <Badge v-else-if="r.keadaan === 'ok'" variant="success">mutakhir</Badge>
              </div>
              <p v-if="r.pesan" class="mt-1 text-sm text-ink-muted">{{ r.pesan }}</p>
              <ul v-if="r.tertunda.length" class="mt-1 font-mono text-xs text-ink-muted">
                <li v-for="m in r.tertunda" :key="m">{{ m }}</li>
              </ul>
            </li>
          </ul>
        </Card>
      </Deferred>
    </div>
  </AdminLayout>
</template>
