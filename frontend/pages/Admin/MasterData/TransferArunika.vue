<script setup>
import { computed, onBeforeUnmount, watch } from "vue";
import { router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";

const props = defineProps({
  transfer: { type: Object, default: null },
  sumber: { type: Array, default: () => [] },
  instans: { type: Array, default: () => [] },
});

const data = computed(() => props.transfer || {});
const aktif = computed(() => data.value.aktif || null);
const riwayat = computed(() => data.value.riwayat || []);
const berjalan = computed(() => Boolean(data.value.berjalan));

const tahunLalu = new Date().getFullYear() - 1;
const form = useForm({
  sumber: "",
  nama: "",
  dari: `${tahunLalu}-01-01`,
  sampai: `${tahunLalu}-12-31`,
  instans: props.instans[0]?.value ?? "",
});

// Pratinjau nama yang akan dibuat — rumusnya sama dengan `transfer.slug()`.
const slug = computed(() =>
  form.nama.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40).replace(/_+$/g, ""),
);

function mulai() {
  form.post("/admin-panel/master/transfer-arunika/mulai", { preserveScroll: true });
}

// Selama ada yang berjalan, muat ulang HANYA prop `transfer` (baris SQLite,
// murah). Timer dilepas begitu selesai dan saat halaman ditinggalkan.
let timer = null;
function hentikanTimer() {
  if (timer) clearInterval(timer);
  timer = null;
}
watch(
  berjalan,
  (ya) => {
    hentikanTimer();
    if (ya) timer = setInterval(() => router.reload({ only: ["transfer"] }), 3000);
  },
  { immediate: true },
);
onBeforeUnmount(hentikanTimer);

const varianStatus = { berjalan: "brand", selesai: "success", gagal: "danger", terputus: "warning" };
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

const kolomLangkah = [
  { key: "tahap", label: "Tahap" },
  { key: "nama", label: "Tabel / entitas" },
  { key: "baris", label: "Baris", align: "right" },
  { key: "dilewati", label: "Dilewati", align: "right" },
  { key: "detik", label: "Detik", align: "right" },
];
const kolomRiwayat = [
  { key: "mulai_pada", label: "Mulai" },
  { key: "nama", label: "Nama" },
  { key: "sumber", label: "Sumber" },
  { key: "rentang", label: "Rentang" },
  { key: "status", label: "Status" },
  { key: "total_baris", label: "Baris Arunika", align: "right" },
  { key: "durasi_detik", label: "Durasi", align: "right" },
];
const barisRiwayat = computed(() => riwayat.value.map((r) => ({ ...r, rentang: `${r.dari} s/d ${r.sampai}` })));
const langkahTerbalik = computed(() => [...(aktif.value?.langkah || [])].reverse());
</script>

<template>
  <AdminLayout title="Transfer ke Arunika">
    <Banner
      variant="info"
      class="mb-4"
      message="Menyalin data legacy sebuah server ke database Arunika BARU di instans lokal. Server sumber hanya dibaca — tak ada objek yang dibuat di sana. Tiap transfer membuat dua profil ber-lingkungan Uji Coba dan tiga database; tak ada yang ditimpa."
    />

    <Card title="Transfer baru" subtitle="Master data selalu disalin penuh; rentang tanggal hanya berlaku untuk dokumen transaksi.">
      <div class="grid gap-3 md:grid-cols-2">
        <Select v-model="form.sumber" label="Server sumber" :options="sumber" placeholder="Pilih server…" />
        <Input v-model="form.nama" label="Nama transfer" placeholder="mis. Arunika Pusat 2025" maxlength="80" />
        <Input v-model="form.dari" type="date" label="Dokumen dari" />
        <Input v-model="form.sampai" type="date" label="Dokumen sampai" />
        <Select v-model="form.instans" label="Instans lokal tujuan" :options="instans" placeholder="Pilih instans…" />
      </div>

      <div v-if="slug" class="mt-3 rounded-control bg-surface-2 p-3 text-xs text-ink-muted">
        Akan dibuat — profil <strong>{{ form.nama.trim() }}</strong> dan
        <strong>{{ form.nama.trim() }} (legacy)</strong>; database
        <code>legacy_{{ slug }}</code>, <code>arunika_{{ slug }}_sumber</code>, <code>arunika_{{ slug }}</code>.
      </div>
      <p class="mt-3 text-xs text-ink-muted">
        Laporan bentuk Arunika benar untuk rentang apa pun. <strong>Stok</strong> di profil legacy-nya
        hanya benar kalau rentangnya mencakup tanggal <strong>tutup buku terakhir</strong> server sumber,
        karena hitungan stok berjangkar di tanggal itu.
      </p>
      <Banner
        v-if="!instans.length"
        variant="warning"
        class="mt-3"
        message="Belum ada profil ber-lingkungan Uji Coba. Buat satu di Kelola Koneksi (mis. SQL Server lokal) supaya kredensialnya bisa dipakai."
      />

      <div class="mt-4 flex items-center gap-3">
        <Button :loading="form.processing" :disabled="berjalan || !instans.length" @click="mulai">
          Mulai transfer
        </Button>
        <span v-if="berjalan" class="text-sm text-ink-muted">Masih ada transfer yang berjalan.</span>
      </div>
    </Card>

    <Card v-if="aktif" :title="`${berjalan ? 'Sedang berjalan' : 'Transfer terakhir'}: ${aktif.nama}`">
      <div class="mb-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <Badge :variant="varianStatus[aktif.status] || 'neutral'">{{ aktif.status_label }}</Badge>
        <span>Sumber <strong>{{ aktif.sumber }}</strong>, dokumen {{ aktif.dari }} s/d {{ aktif.sampai }}</span>
        <span>{{ angka.format(aktif.total_baris) }} baris Arunika</span>
        <span v-if="aktif.total_dilewati" class="text-warning-fg">{{ angka.format(aktif.total_dilewati) }} dilewati</span>
        <span class="text-ink-muted">{{ durasi(aktif.durasi_detik) }}</span>
      </div>
      <p class="mb-3 text-sm text-ink-muted">{{ aktif.tahap }}</p>
      <Banner v-if="aktif.pesan_galat" variant="danger" class="mb-3" :message="aktif.pesan_galat" />
      <Banner
        v-if="aktif.stok_benar === false"
        variant="warning"
        class="mb-3"
        :message="`Stok di profil ${aktif.profil_legacy || '(legacy)'} TIDAK bisa dipercaya: tutup buku terakhir ${aktif.sumber} (${aktif.tutup_buku}) di luar rentang ${aktif.dari} s/d ${aktif.sampai}, dan hitungan stok berjangkar di tanggal itu. Laporan bentuk Arunika tetap benar. Untuk stok yang benar, ulangi dengan rentang yang mencakup ${aktif.tutup_buku}.`"
      />
      <p v-if="aktif.status === 'selesai'" class="mb-3 text-sm">
        Pilih profil <strong>{{ aktif.profil_arunika }}</strong> dari navbar untuk laporan bentuk Arunika,
        atau <strong>{{ aktif.profil_legacy }}</strong> untuk layar legacy (stok, dll).
      </p>

      <DataTable :rows="langkahTerbalik" :columns="kolomLangkah" empty-message="Belum ada langkah selesai.">
        <template #cell-baris="{ value }">{{ angka.format(value) }}</template>
        <template #cell-dilewati="{ row }">
          <span v-if="row.dilewati" class="text-warning-fg" :title="alasanTeks(row.alasan)">
            {{ angka.format(row.dilewati) }}
          </span>
          <span v-else class="text-ink-subtle">0</span>
        </template>
      </DataTable>
    </Card>

    <Card title="Riwayat transfer">
      <DataTable :rows="barisRiwayat" :columns="kolomRiwayat" empty-message="Belum pernah ada transfer.">
        <template #cell-mulai_pada="{ value }">{{ waktu(value) }}</template>
        <template #cell-status="{ row }">
          <Badge :variant="varianStatus[row.status] || 'neutral'">{{ row.status_label }}</Badge>
        </template>
        <template #cell-total_baris="{ value }">{{ angka.format(value) }}</template>
        <template #cell-durasi_detik="{ value }">{{ durasi(value) }}</template>
      </DataTable>
    </Card>
  </AdminLayout>
</template>
