<script setup>
/**
 * Kesehatan Sync — kondisi sinkronisasi legacy seluruh server dalam satu layar.
 *
 * Sync antar-server dikerjakan SQL Agent job di tiap server, bukan aplikasi ini,
 * dan job itu tidak melapor ke mana pun. Halaman ini menerjemahkan jejaknya
 * (antrean tbl_tmp_post, watermark tbl_waktu_get) jadi satu status per server.
 *
 * Superadmin-only lewat menus.py — penegakannya di server (middleware), bukan di
 * sini. Tidak ada apa pun di halaman ini yang boleh jadi satu-satunya penjaga.
 */
import { computed, ref, watch, onBeforeUnmount } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import CollapsibleSection from "@/components/ui/CollapsibleSection.vue";
import Select from "@/components/ui/Select.vue";

const props = defineProps({
  health: { type: Object, default: null },
  // Prop TERPISAH dari `health`, dan bukan tanpa alasan: `health` menyapu
  // sebelas server lewat WAN. Polling progres tiap 3 detik lewat prop itu
  // berarti menyapu sebelas server tiap tiga detik. Ini murni SQLite.
  progres: { type: Object, default: () => ({}) },
});

const data = computed(() => props.health || {});
const rows = computed(() => data.value.rows || []);

const VARIAN = { ok: "success", lambat: "warning", mati: "danger", offline: "neutral" };

// "Sepi" sengaja netral, bukan hijau: antrean kosong tanpa aktivitas berarti
// TIDAK TAHU, dan mewarnainya hijau justru mengulang kesalahan yang mau dihindari.
const BUKTI_LABEL = { aktif: "terkirim", sepi: "sepi — tak ada bukti", antre: "ada tunggakan" };
const BUKTI_VARIAN = { aktif: "success", sepi: "neutral", antre: "warning" };

const columns = [
  { key: "profile", label: "Server", sortable: true },
  { key: "status_label", label: "Status", sortable: true },
  { key: "antre", label: "Antre keluar", sortable: true, align: "right" },
  { key: "bukti", label: "Bukti", sortable: true },
  { key: "antre_umur_menit", label: "Tertunggak", sortable: true, align: "right" },
  { key: "watermark_umur_menit", label: "Tarik terakhir", sortable: true, align: "right" },
  { key: "feed_id", label: "Feed id", sortable: true, align: "right" },
];

const fanColumns = [
  { key: "profile", label: "Toko tujuan", sortable: true },
  { key: "status_label", label: "Status", sortable: true },
  { key: "ketinggalan", label: "Ketinggalan", sortable: true, align: "right" },
  { key: "cursor_id", label: "Posisi kita", sortable: true, align: "right" },
  { key: "dead_letter", label: "Dead-letter 24j", sortable: true, align: "right" },
];

// Pusat tidak lagi diukur dengan "ketinggalan cursor" — `hub_pull` menyapu
// rentang tanggal dan tidak punya cursor yang bisa tertinggal. Yang bisa basi
// hanyalah kapan sapuan terakhir terjadi, dan `hari_beda` (berapa hari yang
// ternyata tak cocok saat dibandingkan) adalah temuan, bukan derau.
const hubColumns = [
  { key: "profile", label: "Cabang", sortable: true },
  { key: "kode_sumber", label: "Kode", sortable: true },
  { key: "status_label", label: "Status", sortable: true },
  { key: "umur_menit", label: "Tarik terakhir", sortable: true, align: "right" },
  { key: "hari_beda", label: "Hari beda", sortable: true, align: "right" },
  { key: "arsip_selesai", label: "Arsip", sortable: true },
  { key: "tutup_buku", label: "Tutup buku", sortable: true },
];

const deadColumns = [
  { key: "waktu", label: "Waktu" },
  { key: "sumber", label: "Sumber" },
  { key: "tujuan", label: "Tujuan" },
  { key: "feed_id", label: "Feed id", align: "right" },
  { key: "table_aksi", label: "Tabel/aksi" },
  { key: "reason", label: "Alasan" },
  { key: "data", label: "Isi baris" },
];

const trenColumns = [
  { key: "profile", label: "Server", sortable: true },
  { key: "sekarang", label: "Antre kini", sortable: true, align: "right" },
  { key: "min_antre", label: "Terendah 7h", sortable: true, align: "right" },
  { key: "max_antre", label: "Tertinggi 7h", sortable: true, align: "right" },
  { key: "mati", label: "Sampel mati", sortable: true, align: "right" },
  { key: "arah", label: "Arah", sortable: true },
];

const jobColumns = [
  { key: "nama", label: "Job" },
  { key: "terakhir", label: "Terakhir jalan" },
  { key: "durasi_ms", label: "Durasi", align: "right" },
  { key: "status", label: "Status" },
];

const ARAH_VARIAN = { naik: "danger", turun: "success", datar: "neutral" };

// --- Tugas latar ---------------------------------------------------------
const penjadwal = computed(() => data.value.penjadwal || {});
const flagList = computed(() =>
  Object.entries(penjadwal.value.flag || {}).map(([nama, on]) => ({ nama, on })),
);
const daftarTugas = computed(() => props.progres?.daftar_tugas || []);
const aktif = computed(() => props.progres?.aktif || null);
const berjalan = computed(() => !!aktif.value);

const form = useForm({ tugas: "segar", profil: "" });
const tugasTerpilih = computed(() => daftarTugas.value.find((t) => t.nama === form.tugas));
const butuhCabang = computed(() => !!tugasTerpilih.value?.butuh_cabang);
const cabangOptions = computed(() => [
  { value: "", label: "— pilih cabang —" },
  ...(data.value.hub_cabang || []).map((c) => ({ value: String(c.id), label: c.nama })),
]);
const tugasOptions = computed(() =>
  daftarTugas.value.map((t) => ({ value: t.nama, label: t.label })),
);
const bisaJalan = computed(
  () => !berjalan.value && !form.processing && (!butuhCabang.value || !!form.profil),
);

function jalankan() {
  form.post("/admin-panel/master/sync-health/jalankan", { preserveScroll: true });
}

// Polling hanya selama ada tugas berjalan, dan hanya prop `progres`.
//
// TANPA `immediate`: watcher yang menyala saat mount akan memuat ulang `health`
// di SETIAP kali halaman dibuka, dan `health` menyapu sebelas server lewat WAN.
// Yang dicari di sini adalah PERPINDAHAN berjalan -> selesai.
let timer = null;
watch(berjalan, (on, sebelumnya) => {
  clearInterval(timer);
  timer = null;
  if (on) {
    timer = setInterval(() => router.reload({ only: ["progres"] }), 3000);
  } else if (sebelumnya) {
    // Sekali, saat tugas baru saja selesai: angka di `health` (tarik terakhir,
    // hari beda, arsip sampai) baru berubah sesudah tugasnya beres.
    router.reload({ only: ["health"] });
  }
});
onBeforeUnmount(() => clearInterval(timer));

/**
 * Umur dalam menit -> teks yang bisa dibaca sekilas.
 *
 * Satuannya naik sampai bulan dengan sengaja: selisih antara "3 hari" dan "21
 * bulan" itulah beda antara tersendat dan terbengkalai bertahun-tahun, dan
 * "15.480 jam" tidak menyampaikan apa pun.
 */
function umur(menit) {
  if (menit === null || menit === undefined) return "—";
  if (menit < 0) return `${Math.round(-menit)} mnt di depan`;
  if (menit < 60) return `${Math.round(menit)} mnt`;
  const jam = menit / 60;
  if (jam < 48) return `${Math.round(jam)} jam`;
  const hari = jam / 24;
  if (hari < 60) return `${Math.round(hari)} hari`;
  return `${Math.round(hari / 30)} bln`;
}

const angka = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("id-ID"));

// Detak job selalu hari ini (hilang saat restart), jadi jam saja sudah cukup.
const jam = (v) =>
  !v ? "—" : new Date(v).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

// Tanggal saja, tanpa jam: tutup buku selalu jatuh di 23:59:59 dan menampilkan
// jamnya cuma menambah tujuh karakter yang sama di setiap baris.
const tanggal = (v) =>
  !v ? "—" : new Date(v).toLocaleDateString("id-ID", { year: "numeric", month: "short", day: "numeric" });

const ringkas = computed(() => {
  const total = data.value.total || 0;
  const bermasalah = data.value.bermasalah || 0;
  if (!total) return "";
  return bermasalah
    ? `${bermasalah} dari ${total} server bermasalah.`
    : `Semua ${total} server sehat.`;
});

const ambang = computed(() => data.value.ambang || {});

function muatUlang() {
  router.reload({ only: ["health"] });
}
</script>

<template>
  <AdminLayout title="Kesehatan Sync">
    <div class="space-y-4">
      <!-- Di luar <Deferred> supaya tombolnya ada sejak cat pertama. -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-ink-muted">
          Kondisi job sinkronisasi legacy di tiap server. Angkanya dibaca langsung
          dari server, bukan dari cache.
        </p>
        <Button variant="secondary" @click="muatUlang">Muat ulang</Button>
      </div>

      <!-- Panel tugas di LUAR <Deferred>: tombolnya harus bisa dipakai sebelum
           sapuan sebelas server selesai, dan progresnya datang dari prop lain. -->
      <Card>
        <div class="flex flex-wrap items-end gap-3">
          <div class="min-w-[200px]">
            <Select v-model="form.tugas" label="Jalankan tugas" :options="tugasOptions" />
          </div>
          <div v-if="butuhCabang" class="min-w-[200px]">
            <Select v-model="form.profil" label="Cabang" :options="cabangOptions" />
          </div>
          <Button :disabled="!bisaJalan" @click="jalankan">
            {{ berjalan ? "Ada tugas berjalan…" : "Jalankan" }}
          </Button>
        </div>
        <p class="mt-2 text-xs text-ink-muted">
          Tugas berjalan di latar; halaman boleh ditutup. Satu tugas dalam satu waktu.
          <b>Tarik arsip</b> bisa berjam-jam, tapi bisa dilanjutkan: potongan yang
          sudah selesai tidak diulang. Semua tugas ini hanya <em>membaca</em> server
          legacy — yang ditulis cuma AMPHOREUS dan toko tujuan, sama persis dengan
          yang dikerjakan penjadwal sendiri.
        </p>

        <div v-if="aktif" class="mt-3 rounded border border-border-default p-3">
          <div class="flex items-center gap-2">
            <Badge variant="warning">berjalan</Badge>
            <span class="text-sm font-medium">{{ aktif.label }}</span>
            <span class="text-sm text-ink-muted">{{ aktif.cabang }}</span>
            <span class="text-xs text-ink-muted">mulai {{ aktif.mulai }}</span>
          </div>
          <div v-if="aktif.baris.length" class="mt-2 max-h-56 overflow-auto font-mono text-xs">
            <div v-for="(b, i) in aktif.baris" :key="i" class="whitespace-pre-wrap">
              <span class="text-ink-muted">{{ b.waktu }}</span> {{ b.teks }}
            </div>
          </div>
          <p v-else class="mt-2 text-xs text-ink-muted">Menunggu laporan pertama…</p>
        </div>
      </Card>

      <Deferred data="health">
        <template #fallback>
          <LoadingCard message="Menghubungi semua server…" />
        </template>

        <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />

        <Banner
          v-if="data.bermasalah"
          variant="warning"
          :message="`${ringkas} Server yang antrean keluarnya menumpuk berarti trigger masih menulis tapi pengirimnya berhenti.`"
        />
        <!-- Banner hanya punya danger|warning|info; sehat pakai info. -->
        <Banner v-else-if="data.total" variant="info" :message="ringkas" />

        <Card>
          <DataTable
            :columns="columns"
            :rows="rows"
            row-key="profile_id"
            :per-page="25"
            empty-message="Belum ada server terdaftar."
          >
            <template #cell-status_label="{ row }">
              <Badge :variant="VARIAN[row.status] || 'neutral'">{{ row.status_label }}</Badge>
              <span v-if="row.penyebab" class="ml-2 text-xs text-ink-muted">via {{ row.penyebab }}</span>
              <span v-if="row.error" class="ml-2 text-xs text-ink-muted">{{ row.error }}</span>
            </template>
            <template #cell-antre="{ row }">{{ angka(row.antre) }}</template>
            <!-- Antrean dihapus begitu terkirim, jadi "kosong" tidak membuktikan
                 apa pun sendirian. Kolom ini yang membedakan sehat dari tak tahu. -->
            <template #cell-bukti="{ row }">
              <Badge :variant="BUKTI_VARIAN[row.bukti] || 'neutral'">
                {{ BUKTI_LABEL[row.bukti] || "—" }}
              </Badge>
            </template>
            <template #cell-antre_umur_menit="{ row }">{{ umur(row.antre_umur_menit) }}</template>
            <template #cell-watermark_umur_menit="{ row }">{{ umur(row.watermark_umur_menit) }}</template>
            <template #cell-feed_id="{ row }">{{ angka(row.feed_id) }}</template>
          </DataTable>
        </Card>

        <!-- Fan-out master data gudang -> toko. Satu sumber banyak tujuan,
             kebalikan tabel pusat di bawahnya. -->
        <template v-if="data.fan_rows && data.fan_rows.length">
          <div class="flex items-center justify-between gap-3 pt-2">
            <h2 class="text-sm font-semibold">Fan-out master data dari {{ data.fan_sumber }}</h2>
            <Badge :variant="data.fan_bermasalah ? 'warning' : 'success'">
              {{ data.fan_bermasalah ? `${data.fan_bermasalah} toko tertinggal` : "semua toko terkejar" }}
            </Badge>
          </div>
          <Card>
            <DataTable
              :columns="fanColumns"
              :rows="data.fan_rows"
              row-key="profile_id"
              :per-page="25"
              empty-message="Belum ada toko tujuan."
            >
              <template #cell-status_label="{ row }">
                <Badge :variant="VARIAN[row.status] || 'neutral'">{{ row.status_label }}</Badge>
                <span v-if="row.error" class="ml-2 text-xs text-ink-muted">{{ row.error }}</span>
              </template>
              <template #cell-ketinggalan="{ row }">{{ angka(row.ketinggalan) }}</template>
              <template #cell-cursor_id="{ row }">{{ angka(row.cursor_id) }}</template>
              <template #cell-dead_letter="{ row }">
                <span :class="row.dead_letter ? 'text-danger-fg font-medium' : ''">
                  {{ angka(row.dead_letter) }}
                </span>
              </template>
            </DataTable>
          </Card>
        </template>

        <!-- Pusat AMPHOREUS. Ukurannya berbeda dari job legacy DAN dari versi
             sebelumnya: bukan antrean yang menumpuk, bukan pula ketinggalan
             cursor feed. `hub_pull` menyapu rentang tanggal, jadi tak ada yang
             bisa tertinggal — yang bisa basi hanyalah kapan sapuan terakhir
             terjadi, dan berapa hari yang ternyata tak cocok saat dibandingkan. -->
        <template v-if="data.hub_rows && data.hub_rows.length">
          <div class="flex items-center justify-between gap-3 pt-2">
            <h2 class="text-sm font-semibold">Pusat {{ data.hub_nama }}</h2>
            <Badge :variant="data.hub_bermasalah ? 'warning' : 'success'">
              {{ data.hub_bermasalah ? `${data.hub_bermasalah} cabang bermasalah` : "semua cabang tersapu" }}
            </Badge>
          </div>
          <Card>
            <DataTable
              :columns="hubColumns"
              :rows="data.hub_rows"
              row-key="profile_id"
              :per-page="25"
              empty-message="Belum ada cabang ber-kode sumber."
            >
              <template #cell-status_label="{ row }">
                <Badge :variant="VARIAN[row.status] || 'neutral'">{{ row.status_label }}</Badge>
                <span v-if="row.error" class="ml-2 text-xs text-ink-muted">{{ row.error }}</span>
              </template>
              <template #cell-umur_menit="{ row }">{{ umur(row.umur_menit) }}</template>
              <template #cell-hari_beda="{ row }">
                <span :class="row.hari_beda ? 'text-warning-fg font-medium' : ''">
                  {{ angka(row.hari_beda) }}
                </span>
              </template>
              <!-- "belum" sendirian tak bisa membedakan run yang belum pernah
                   dimulai dari run yang sudah tiga jam berjalan di potongan
                   ke-32. `arsip_sampai` yang membedakannya. Tanpa persen:
                   tanggal data tertua tak pernah disimpan, jadi tak ada titik
                   nol untuk membaginya. -->
              <template #cell-arsip_selesai="{ row }">
                <Badge :variant="row.arsip_selesai ? 'success' : 'neutral'">
                  {{ row.arsip_selesai ? "selesai" : "belum" }}
                </Badge>
                <span v-if="!row.arsip_selesai && row.arsip_sampai" class="ml-2 text-xs text-ink-muted">
                  s/d {{ tanggal(row.arsip_sampai) }}
                </span>
              </template>
              <template #cell-tutup_buku="{ row }">{{ tanggal(row.tutup_buku) }}</template>
            </DataTable>
          </Card>
        </template>

        <!-- Penjadwal. Dibaca dari PROSES YANG SEDANG BERJALAN, bukan dari
             .env — flag yang sudah diedit tapi belum direstart adalah persis
             kebingungan yang panel ini hapus. -->
        <div class="flex items-center justify-between gap-3 pt-2">
          <h2 class="text-sm font-semibold">Penjadwal</h2>
          <div class="flex gap-2">
            <Badge :variant="penjadwal.utama_hidup ? 'success' : 'danger'">
              tick utama {{ penjadwal.utama_hidup ? "hidup" : "mati" }} ({{ penjadwal.interval }}s)
            </Badge>
            <Badge :variant="penjadwal.harga_hidup ? 'success' : 'neutral'">
              sebar harga {{ penjadwal.harga_hidup ? "hidup" : "mati" }} ({{ penjadwal.interval_harga }}s)
            </Badge>
          </div>
        </div>
        <Card>
          <div class="grid gap-4 md:grid-cols-2">
            <div>
              <h3 class="mb-2 text-xs font-semibold text-ink-muted">Flag aktif</h3>
              <div class="flex flex-wrap gap-1.5">
                <Badge v-for="f in flagList" :key="f.nama" :variant="f.on ? 'success' : 'neutral'">
                  {{ f.nama }}={{ f.on ? 1 : 0 }}
                </Badge>
              </div>
            </div>
            <div>
              <h3 class="mb-2 text-xs font-semibold text-ink-muted">Detak job</h3>
              <DataTable
                :columns="jobColumns"
                :rows="penjadwal.job || []"
                row-key="nama"
                :per-page="25"
                empty-message="Belum ada job yang jalan di proses ini. Wajar sesudah restart — tick pertama menunggu 60 detik."
              >
                <template #cell-terakhir="{ row }">{{ jam(row.terakhir) }}</template>
                <template #cell-durasi_ms="{ row }">{{ angka(row.durasi_ms) }} ms</template>
                <template #cell-status="{ row }">
                  <Badge :variant="row.status === 'ok' ? 'success' : 'danger'">{{ row.status }}</Badge>
                  <span v-if="row.error" class="ml-2 text-xs text-ink-muted">{{ row.error }}</span>
                </template>
              </DataTable>
              <p class="mt-1 text-xs text-ink-muted">
                Job yang flag-nya mati tidak muncul di sini — lihat daftar flag di samping.
                Detak hilang saat server restart; ia menjawab “hidup sekarang”, bukan riwayat.
              </p>
            </div>
          </div>
        </Card>

        <!-- Tren antrean. Tabel SyncHealthSample sudah ditulis tiap tick sejak
             lama dan sampai sekarang tak pernah dibaca satu layar pun. -->
        <template v-if="data.tren && data.tren.length">
          <h2 class="pt-2 text-sm font-semibold">Tren antrean 7 hari</h2>
          <Card>
            <DataTable :columns="trenColumns" :rows="data.tren" row-key="profile" :per-page="25">
              <template #cell-sekarang="{ row }">{{ angka(row.sekarang) }}</template>
              <template #cell-min_antre="{ row }">{{ angka(row.min_antre) }}</template>
              <template #cell-max_antre="{ row }">{{ angka(row.max_antre) }}</template>
              <template #cell-arah="{ row }">
                <Badge :variant="ARAH_VARIAN[row.arah] || 'neutral'">{{ row.arah }}</Badge>
              </template>
            </DataTable>
            <p class="mt-1 text-xs text-ink-muted">
              “Naik” berarti antrean sekarang berada di puncak rentang seminggu terakhir —
              satu angka besar itu wajar, yang perlu ditindak adalah yang bertahan naik.
            </p>
          </Card>
        </template>

        <!-- Dead-letter: isinya, bukan cuma jumlahnya. Tabel ini idealnya
             kosong, jadi ia menumpang halaman ini alih-alih punya rute sendiri. -->
        <CollapsibleSection
          v-if="data.dead"
          :title="`Baris yang tak bisa diterapkan (${angka(data.dead.total)})`"
          :default-open="data.dead.total > 0"
          class="pt-2"
        >
          <Card>
            <DataTable
              :columns="deadColumns"
              :rows="data.dead.rows"
              row-key="id"
              :per-page="25"
              empty-message="Tidak ada — ini keadaan yang benar."
            >
              <template #cell-data="{ row }">
                <pre class="max-w-md whitespace-pre-wrap break-all text-xs">{{ row.data }}</pre>
              </template>
            </DataTable>
            <p v-if="data.dead.total > data.dead.rows.length" class="mt-1 text-xs text-ink-muted">
              Menampilkan {{ data.dead.rows.length }} terbaru dari {{ angka(data.dead.total) }}.
            </p>
          </Card>
        </CollapsibleSection>

        <Card>
          <h2 class="mb-2 text-sm font-semibold">Cara membaca</h2>
          <ul class="space-y-1 text-sm text-ink-muted">
            <li>
              <b>Antre keluar</b> — baris di <code>tbl_tmp_post</code> yang belum terkirim
              ke pusat. Menumpuk berarti trigger jalan tapi pengirimnya mati.
            </li>
            <li>
              <b>Bukti</b> — baris antrean <em>dihapus</em> begitu terkirim, jadi
              antrean kosong sendirian tidak membuktikan apa pun. Kolom ini memakai
              <code>tbl_log_transaksi</code> (tidak dihapus job legacy) untuk memisahkan
              <em>terkirim</em> dari <em>sepi</em>. “Sepi” bukan kabar buruk, tapi juga
              bukan kabar baik: server itu memang tidak sedang mencatat perubahan
              apa pun, jadi kondisi pengirimnya belum teruji.
            </li>
            <li>
              <b>Tertunggak</b> — umur baris antrean tertua. Sehat &lt;
              {{ ambang.antre_ok }} mnt, lambat &lt; {{ ambang.antre_lambat }} mnt,
              lebih dari itu dianggap mati.
            </li>
            <li>
              <b>Tarik terakhir</b> — kapan server ini terakhir berhasil menarik data
              dari pusat (<code>tbl_waktu_get</code>). Sehat &lt; {{ ambang.watermark_ok }} mnt,
              lambat &lt; {{ ambang.watermark_lambat }} mnt.
            </li>
            <li>
              <b>via ...</b> — sumbu yang sebenarnya memicu badge status: <em>tertunggak</em>,
              <em>tarik terakhir</em>, atau <em>macet</em> (antrean tak bergerak walau
              <code>tbl_log_transaksi</code> terus bertambah — tidak ada kolom angka
              tersendiri untuk ini). Bisa lebih dari satu kalau dua sumbu sama buruknya.
            </li>
            <li>
              <b>Feed id</b> — ujung <code>tbl_log_transaksi</code>. Bukan penanda
              kesehatan job legacy; ini posisi yang dipakai sync internal.
            </li>
            <li>
              <b>Ketinggalan</b> (tabel pusat &amp; fan-out) — jarak antara ujung feed
              cabang dan posisi yang sudah kita tarik. Angka besar sesaat itu wajar;
              yang jadi masalah adalah angka yang terus naik tiap kali halaman dibuka.
            </li>
            <li>
              <b>Ketinggalan negatif</b> — posisi kita <em>melewati</em> ujung feed.
              Itu berarti feed cabang dipangkas: <code>tbl_log_transaksi</code> memang
              tidak dihapus job legacy, tapi pemeliharaan database bisa memangkasnya,
              dan itu sudah pernah terjadi (1.469.155 baris lenyap semalam 15–16 Mei
              2024 saat database dipisah). Akibatnya cabang itu <em>berhenti mengirim
              selamanya</em> — tak ada baris ber-id lebih besar yang bisa terbaca lagi.
              Ditandai <b>Mati</b>; perlu penetapan ulang posisi secara sadar.
            </li>
            <li>
              <b>Dead-letter</b> — baris yang gagal diterapkan dalam 24 jam terakhir.
              Idealnya nol. Baris dari tabel yang memang tidak ditarik ke pusat
              tidak dihitung di sini.
            </li>
          </ul>
        </Card>
      </Deferred>
    </div>
  </AdminLayout>
</template>
