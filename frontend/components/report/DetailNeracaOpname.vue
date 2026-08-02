<script setup>
/**
 * Panel detail satu keluarga barang di Neraca Opname.
 *
 * Menjawab pertanyaan yang jadi alasan halaman ini ada: "dua barang mana yang
 * harus saya pasangkan?" Tabel utama hanya bilang keluarga ini punya 3 lebih
 * dan 3 kurang; di sini terlihat barang mana yang plus dan mana yang minus.
 *
 * `keterangan` sengaja ditampilkan apa adanya. Di data nyata kolom itu terisi
 * hampir selalu dan memuat alasan yang ditulis operator sendiri ("tertukar dg
 * 206-2", "BALANCE SO GLOBAL", "BASAH", "DIBAWA KE H5") — sering kali jawaban
 * yang dicari sudah ada di situ, dan tak pernah muncul di laporan mana pun.
 *
 * Dimuat SAAT DIKLIK, bukan ikut payload tabel: menanam baris opname mentah
 * untuk semua keluarga berarti mengirim seluruh isi t_opname_stok ke browser.
 */
import { ref, watch } from "vue";
import axios from "axios";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Banner from "@/components/ui/Banner.vue";
import EmptyState from "@/components/ui/EmptyState.vue";

const props = defineProps({
  // Baris tabel yang diklik ({ grup, contoh, lebih, kurang, ... }), atau null.
  baris: { type: Object, default: null },
  // Periode/divisi/grup yang sedang aktif, diteruskan apa adanya supaya panel
  // memakai rentang dan pengelompokan YANG SAMA dengan tabel.
  params: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["close"]);

const URL = "/admin-panel/inventory/opname-neraca/detail";

const loading = ref(false);
const error = ref("");
const data = ref(null);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
// Kolom nilai bisa TIDAK ADA sama sekali di respons (izin `nominal` dicabut di
// server, bukan disembunyikan di sini), jadi tampilannya harus tahan kalau
// `nilai` tak pernah datang — itu keadaan normal, bukan kegagalan.
const adaNilai = (rows) => rows.some((r) => r.nilai !== undefined);

watch(
  () => props.baris?.grup,
  async (grup) => {
    data.value = null;
    error.value = "";
    if (!grup) return;
    loading.value = true;
    try {
      const { data: res } = await axios.get(URL, {
        params: { ...props.params, grup_nilai: grup },
      });
      if (res.error) error.value = res.error;
      else data.value = res;
    } catch {
      error.value = "Gagal memuat detail keluarga. Coba lagi.";
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);
</script>

<template>
  <Modal
    :show="!!baris"
    size="lg"
    :title="baris ? baris.contoh || baris.grup : ''"
    @close="emit('close')"
  >
    <div v-if="loading" class="flex items-center justify-center gap-2 py-10 text-ink-muted">
      <Spinner /> <span class="text-sm">Mengambil rincian opname…</span>
    </div>

    <Banner v-else-if="error" variant="warning" :message="error" />

    <div v-else-if="data" class="space-y-5">
      <p class="text-xs text-ink-subtle">
        Keluarga <span class="font-mono">{{ data.grup }}</span> — opname
        {{ data.periode.dari }} sampai {{ data.periode.sampai }}.
      </p>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Barang dalam keluarga ini</h4>
        <p class="mb-2 text-xs text-ink-subtle">
          Barang bertanda merah kekurangan stok, hijau kelebihan. Pasangan dengan
          angka berlawanan yang sama besar kemungkinan tertukar saat pencatatan.
        </p>
        <EmptyState v-if="!data.anggota.length" message="Tak ada barang berselisih pada rentang ini." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Barang</th>
                <th class="px-2 py-1 text-left font-medium">Warna</th>
                <th class="px-2 py-1 text-left font-medium">Ukuran</th>
                <th class="px-2 py-1 text-right font-medium">Selisih</th>
                <th v-if="adaNilai(data.anggota)" class="px-2 py-1 text-right font-medium">Nilai</th>
                <th class="px-2 py-1 text-right font-medium">Baris</th>
                <th class="px-2 py-1 text-left font-medium">Catatan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="b in data.anggota" :key="b.kd_barang">
                <td class="px-2 py-1 text-ink">
                  {{ b.barang || b.kd_barang }}
                  <span class="text-xs text-ink-subtle">{{ b.kd_barang }}</span>
                </td>
                <td class="px-2 py-1 text-ink-muted">{{ b.warna || "—" }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ b.ukuran || "—" }}</td>
                <td
                  class="px-2 py-1 text-right tabular-nums"
                  :class="b.selisih < 0 ? 'text-danger-fg' : 'text-success-fg'"
                >
                  {{ nf.format(b.selisih) }}
                </td>
                <td
                  v-if="adaNilai(data.anggota)"
                  class="px-2 py-1 text-right tabular-nums"
                  :class="b.nilai < 0 ? 'text-danger-fg' : 'text-success-fg'"
                >
                  {{ rp.format(b.nilai || 0) }}
                </td>
                <td class="px-2 py-1 text-right tabular-nums text-ink-muted">{{ b.n_baris }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ b.catatan || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Baris opname</h4>
        <EmptyState v-if="!data.kejadian.length" message="Tak ada baris opname pada rentang ini." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">No. Opname</th>
                <th class="px-2 py-1 text-left font-medium">Tanggal</th>
                <th class="px-2 py-1 text-left font-medium">Divisi</th>
                <th class="px-2 py-1 text-left font-medium">Barang</th>
                <th class="px-2 py-1 text-left font-medium">Arah</th>
                <th class="px-2 py-1 text-right font-medium">Qty</th>
                <th class="px-2 py-1 text-left font-medium">Keterangan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="(k, i) in data.kejadian" :key="`${k.no_transaksi}-${k.kd_barang}-${i}`">
                <td class="px-2 py-1 text-ink">{{ k.no_transaksi }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ k.tanggal }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ k.divisi || "—" }}</td>
                <td class="px-2 py-1 text-ink">
                  {{ k.barang || k.kd_barang }}
                  <span class="text-xs text-ink-subtle">{{ k.kd_barang }}</span>
                </td>
                <td
                  class="px-2 py-1"
                  :class="k.arah === 'Kurang' ? 'text-danger-fg' : 'text-success-fg'"
                >
                  {{ k.arah }}
                </td>
                <td class="px-2 py-1 text-right tabular-nums text-ink">{{ nf.format(k.qty) }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ k.keterangan || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </Modal>
</template>
