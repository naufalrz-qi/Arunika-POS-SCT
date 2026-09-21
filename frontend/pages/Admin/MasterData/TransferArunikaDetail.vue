<script setup>
/**
 * Rincian satu run Transfer ke Arunika.
 *
 * `langkah` sudah disimpan untuk SETIAP run sejak awal, tapi sampai halaman ini
 * ada hanya run terbaru yang pernah diserialkan ke browser. Run yang gagal
 * minggu lalu menyimpan persis di tabel mana ia berhenti dan berapa baris yang
 * sempat masuk — dan tak ada satu pun layar yang mau menunjukkannya.
 */
import { computed } from "vue";
import { Link } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";

const props = defineProps({ transfer: { type: Object, required: true } });
const t = computed(() => props.transfer);

const angka = new Intl.NumberFormat("id-ID");

function durasi(detik) {
  const m = Math.floor(detik / 60);
  return m ? `${m} mnt ${detik % 60} dtk` : `${detik} dtk`;
}
function waktu(iso) {
  return iso ? new Date(iso).toLocaleString("id-ID") : "—";
}
function alasanTeks(alasan) {
  return Object.entries(alasan || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([sebab, n]) => `${angka.format(n)} × ${sebab}`)
    .join("; ");
}

const VARIAN = { selesai: "success", gagal: "danger", terputus: "warning", berjalan: "warning" };

const kolomLangkah = [
  { key: "tahap", label: "Tahap" },
  { key: "nama", label: "Tabel / entitas" },
  { key: "baris", label: "Baris", align: "right" },
  { key: "dilewati", label: "Dilewati", align: "right" },
  { key: "detik", label: "Detik", align: "right" },
];
// Urutan asli, bukan terbalik: di layar utama yang terbalik karena orang
// menonton run yang sedang berjalan dan yang terbaru paling atas. Di sini
// run-nya sudah selesai, dan yang dicari adalah DI MANA ia berhenti — itu
// dibaca dari atas ke bawah.
const langkah = computed(() => t.value.langkah || []);
const totalDetik = computed(() => langkah.value.reduce((n, l) => n + (l.detik || 0), 0));
</script>

<template>
  <AdminLayout title="Rincian Transfer">
    <div class="mb-4">
      <Link href="/admin-panel/master/transfer-arunika" class="text-sm text-brand-fg underline">
        &larr; Kembali ke Transfer ke Arunika
      </Link>
    </div>

    <Card :title="t.nama" :subtitle="`${t.sumber} · ${t.dari} s/d ${t.sampai}`">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div class="text-xs text-ink-muted">Status</div>
          <Badge :variant="VARIAN[t.status] || 'neutral'">{{ t.status_label }}</Badge>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Mulai</div>
          <div class="text-sm">{{ waktu(t.mulai_pada) }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Selesai</div>
          <div class="text-sm">{{ waktu(t.selesai_pada) }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Durasi</div>
          <div class="text-sm">{{ durasi(t.durasi_detik) }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Baris masuk Arunika</div>
          <div class="text-sm font-semibold">{{ angka.format(t.total_baris) }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Dilewati</div>
          <div class="text-sm">{{ angka.format(t.total_dilewati) }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Dijalankan oleh</div>
          <div class="text-sm">{{ t.dibuat_oleh || "—" }}</div>
        </div>
        <div>
          <div class="text-xs text-ink-muted">Tutup buku sumber</div>
          <div class="text-sm">{{ t.tutup_buku || "—" }}</div>
        </div>
      </div>

      <div class="mt-3 text-sm text-ink-muted">
        Profil yang dibuat:
        <code>{{ t.profil_legacy || "—" }}</code> (salinan legacy) ·
        <code>{{ t.profil_arunika || "—" }}</code> (Arunika)
      </div>
    </Card>

    <Banner v-if="t.pesan_galat" variant="danger" class="mt-4" :message="t.pesan_galat" />

    <!-- Peringatan yang sama dengan layar utama: stok di profil legacy hasil
         salinan hanya benar kalau rentangnya memuat tanggal tutup buku sumber. -->
    <Banner
      v-if="t.stok_benar === false"
      variant="warning"
      class="mt-4"
      :message="`Rentang transfer ini (${t.dari} s/d ${t.sampai}) tidak memuat tanggal tutup buku sumber (${t.tutup_buku}). Stok di profil salinan legacy TIDAK bisa dipercaya — mesin stok berpijak di tanggal tutup buku lalu berjalan maju/mundur dari sana. Laporan berbentuk Arunika tetap benar.`"
    />

    <Card
      class="mt-4"
      title="Langkah per tabel"
      :subtitle="`${langkah.length} langkah, total ${durasi(totalDetik)} — urut dari yang pertama dikerjakan`"
    >
      <DataTable
        :columns="kolomLangkah"
        :rows="langkah"
        :per-page="100"
        empty-message="Run ini tidak sempat mencatat satu langkah pun — ia gagal sebelum tabel pertama selesai."
      >
        <template #cell-baris="{ row }">{{ angka.format(row.baris || 0) }}</template>
        <template #cell-dilewati="{ row }">
          <span :class="row.dilewati ? 'text-warning-fg font-medium' : ''">
            {{ angka.format(row.dilewati || 0) }}
          </span>
          <div v-if="row.alasan" class="text-xs text-ink-muted">{{ alasanTeks(row.alasan) }}</div>
        </template>
      </DataTable>
    </Card>
  </AdminLayout>
</template>
