<script setup>
/**
 * Cadangan & Pemulihan.
 *
 * TIDAK ADA TOMBOL RESTORE di layar ini, dan itu disengaja — bukan kelalaian
 * yang menunggu dilengkapi. Proses yang menjalankan restore pangkal adalah
 * proses yang sedang memegang koneksi ke database yang ditimpanya; gagal di
 * tengah berarti tak seorang pun bisa login, termasuk untuk membetulkannya.
 * Yang ada gantinya: runbook yang bisa disalin, di panel paling bawah.
 *
 * Superadmin-only lewat menus.py; penegakannya di server.
 */
import { computed, ref } from "vue";
import { Deferred, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Badge from "@/components/ui/Badge.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import CollapsibleSection from "@/components/ui/CollapsibleSection.vue";

const props = defineProps({ data: { type: Object, default: null } });
const data = computed(() => props.data || {});
const rows = computed(() => data.value.rows || []);

const columns = [
  { key: "jenis", label: "Jenis", sortable: true },
  { key: "nama_berkas", label: "Berkas", sortable: true },
  { key: "dibuat_at", label: "Dibuat", sortable: true },
  { key: "dibuat_oleh", label: "Oleh", sortable: true },
  { key: "ukuran_mb", label: "Ukuran (MB)", sortable: true, align: "right" },
  { key: "umur_hari", label: "Umur (hari)", sortable: true, align: "right" },
  { key: "verifikasi_ok", label: "Verifikasi", sortable: true },
];

const jalan = useForm({ jenis: "" });
const cek = useForm({ id: "" });

function cadangkan(jenis) {
  jalan.jenis = jenis;
  jalan.post("/admin-panel/pengaturan/cadangan/jalankan", { preserveScroll: true });
}
function verifikasi(id) {
  cek.id = String(id);
  cek.post("/admin-panel/pengaturan/cadangan/verifikasi", { preserveScroll: true });
}

const disalin = ref(false);
async function salinRunbook() {
  try {
    await navigator.clipboard.writeText(data.value.runbook || "");
    disalin.value = true;
    setTimeout(() => (disalin.value = false), 2000);
  } catch {
    // Clipboard butuh konteks aman (https/localhost). Kalau ditolak, teksnya
    // tetap ada di layar dan bisa diblok-salin manual — jadi diam saja, bukan
    // melempar galat untuk sesuatu yang tak menghalangi apa pun.
  }
}
</script>

<template>
  <AdminLayout title="Cadangan & Pemulihan">
    <div class="space-y-4">
      <!-- Di luar <Deferred> supaya tombolnya ada sejak cat pertama. -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-ink-muted">
          Cadangan basis data pangkal dan pusat AMPHOREUS. Keduanya milik kita sendiri;
          server legacy tidak dicadangkan dari sini.
        </p>
        <div class="flex gap-2">
          <Button :disabled="jalan.processing" @click="cadangkan('pangkal')">
            Cadangkan pangkal
          </Button>
          <Button variant="secondary" :disabled="jalan.processing" @click="cadangkan('amphoreus')">
            Cadangkan {{ data.hub_nama || "AMPHOREUS" }}
          </Button>
        </div>
      </div>

      <Deferred data="data">
        <template #fallback><LoadingCard message="Membaca daftar cadangan…" /></template>

        <Banner
          variant="warning"
          message="POS_FERNET_KEY TIDAK ikut di cadangan mana pun. Tanpa salinan kuncinya, 14 password koneksi di dalam cadangan tetap terenkripsi selamanya — databasenya pulih utuh tapi tak bisa menghubungi satu server pun."
        />

        <Card>
          <DataTable
            :columns="columns"
            :rows="rows"
            row-key="id"
            :per-page="25"
            empty-message="Belum ada cadangan tercatat. Jalankan sekali dengan tombol di atas, atau jadwalkan manage.py backup_db lewat Task Scheduler."
          >
            <template #cell-nama_berkas="{ row }">
              <div>{{ row.nama_berkas }}</div>
              <div class="text-xs text-ink-muted">{{ row.path }}</div>
            </template>
            <!-- 0 MB pada baris AMPHOREUS BUKAN berkas kosong: .bak ditulis di
                 mesin SQL Server, yang bisa tak terjangkau dari mesin ini. -->
            <template #cell-ukuran_mb="{ row }">
              <span v-if="row.ukuran_mb">{{ row.ukuran_mb }}</span>
              <span v-else class="text-xs text-ink-muted">tak terjangkau dari sini</span>
            </template>
            <template #cell-verifikasi_ok="{ row }">
              <div class="flex items-center gap-2">
                <!-- Tiga keadaan, bukan dua. "belum" bukan "gagal". -->
                <Badge v-if="row.verifikasi_ok === true" variant="success">utuh</Badge>
                <Badge v-else-if="row.verifikasi_ok === false" variant="danger">rusak</Badge>
                <Badge v-else variant="neutral">belum</Badge>
                <Badge v-if="row.ada === false" variant="danger">berkas hilang</Badge>
                <Button
                  variant="secondary" size="sm"
                  :disabled="cek.processing"
                  @click="verifikasi(row.id)"
                >Verifikasi</Button>
              </div>
              <div v-if="row.verifikasi_at" class="mt-0.5 text-xs text-ink-muted">
                {{ row.verifikasi_at }} — {{ row.verifikasi_pesan }}
              </div>
            </template>
          </DataTable>
          <p class="mt-2 text-xs text-ink-muted">
            Folder pangkal: <code>{{ data.folder_pangkal }}</code> ·
            folder {{ data.hub_nama }}: <code>{{ data.folder_hub }}</code>
            (diartikan oleh mesin SQL Server, bukan mesin ini).
          </p>
        </Card>

        <CollapsibleSection title="Cara memulihkan (runbook)" :default-open="false">
          <Card>
            <div class="mb-2 flex items-center justify-between gap-3">
              <p class="text-sm text-ink-muted">
                Tidak ada tombol restore di aplikasi ini. Langkahnya dijalankan manual,
                dan urutannya penting.
              </p>
              <Button variant="secondary" size="sm" @click="salinRunbook">
                {{ disalin ? "Tersalin" : "Salin" }}
              </Button>
            </div>
            <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded bg-surface-2 p-3 text-xs">{{ data.runbook }}</pre>
          </Card>
        </CollapsibleSection>
      </Deferred>
    </div>
  </AdminLayout>
</template>
