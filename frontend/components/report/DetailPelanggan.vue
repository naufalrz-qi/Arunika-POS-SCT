<script setup>
/**
 * Panel detail satu pelanggan: kontak, barang yang biasa ia beli, dan nota
 * terakhirnya.
 *
 * Dimuat SAAT DIKLIK, bukan ikut payload tabel. Menanam top-barang untuk semua
 * pelanggan di query utama berarti menyisir t_penjualan_detail untuk ratusan
 * orang demi kolom yang hampir selalu tak dibaca; di sini satu permintaan hanya
 * menyentuh satu kd_customer.
 *
 * Kolom nilai bisa TIDAK ADA sama sekali di respons (izin `nominal` dicabut di
 * server, bukan disembunyikan di sini), jadi tampilannya harus tahan kalau
 * `nilai` tak pernah datang — itu keadaan normal, bukan kegagalan.
 */
import { ref, watch } from "vue";
import axios from "axios";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Banner from "@/components/ui/Banner.vue";
import EmptyState from "@/components/ui/EmptyState.vue";

const props = defineProps({
  // { kd_customer, customer, segmen, ... } — baris tabel yang diklik, atau null.
  baris: { type: Object, default: null },
  // Query string periode/divisi yang sedang aktif, diteruskan apa adanya supaya
  // detail memakai rentang yang SAMA dengan tabel. Tanpa ini panel menjawab
  // pertanyaan periode lain dari yang sedang dilihat.
  params: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["close"]);

const URL = "/admin-panel/analitik/klasifikasi-pelanggan/detail";

const loading = ref(false);
const error = ref("");
const data = ref(null);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const adaNilai = (rows) => rows.some((r) => r.nilai !== undefined);

watch(
  () => props.baris?.kd_customer,
  async (kd) => {
    data.value = null;
    error.value = "";
    if (!kd) return;
    loading.value = true;
    try {
      const { data: res } = await axios.get(URL, {
        params: { ...props.params, kd_customer: kd },
      });
      if (res.error) error.value = res.error;
      else data.value = res;
    } catch {
      error.value = "Gagal memuat detail pelanggan. Coba lagi.";
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
    :title="baris ? baris.customer || baris.kd_customer : ''"
    @close="emit('close')"
  >
    <div v-if="loading" class="flex items-center justify-center gap-2 py-10 text-ink-muted">
      <Spinner /> <span class="text-sm">Mengambil riwayat pelanggan…</span>
    </div>

    <Banner v-else-if="error" variant="warning" :message="error" />

    <div v-else-if="data" class="space-y-5">
      <!-- Kontak: alasan utama panel ini dibuka. -->
      <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt class="text-xs text-ink-subtle">Kode</dt>
          <dd class="text-ink">{{ data.kd_customer }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">HP</dt>
          <dd class="text-ink">{{ (data.profil && data.profil.hp) || "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Telepon</dt>
          <dd class="text-ink">{{ (data.profil && data.profil.telepon) || "—" }}</dd>
        </div>
        <div class="col-span-2 sm:col-span-3">
          <dt class="text-xs text-ink-subtle">Alamat</dt>
          <dd class="text-ink">{{ (data.profil && data.profil.alamat) || "—" }}</dd>
        </div>
      </dl>

      <p class="text-xs text-ink-subtle">
        Riwayat {{ data.periode.dari }} sampai {{ data.periode.sampai }}.
      </p>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Barang yang sering dibeli</h4>
        <EmptyState
          v-if="!data.favorit.length"
          message="Belum ada pembelian pada rentang ini."
        />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Barang</th>
                <th class="px-2 py-1 text-right font-medium">Qty</th>
                <th v-if="adaNilai(data.favorit)" class="px-2 py-1 text-right font-medium">Nilai</th>
                <th class="px-2 py-1 text-right font-medium">Nota</th>
                <th class="px-2 py-1 text-left font-medium">Terakhir</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="b in data.favorit" :key="b.kd_barang">
                <td class="px-2 py-1 text-ink">
                  {{ b.barang || b.kd_barang }}
                  <span class="text-xs text-ink-subtle">{{ b.kd_barang }}</span>
                </td>
                <td class="px-2 py-1 text-right text-ink">{{ nf.format(b.qty) }}</td>
                <td v-if="adaNilai(data.favorit)" class="px-2 py-1 text-right text-ink">
                  {{ rp.format(b.nilai || 0) }}
                </td>
                <td class="px-2 py-1 text-right text-ink-muted">{{ b.jml_nota }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ b.terakhir }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Nota terakhir</h4>
        <EmptyState v-if="!data.nota.length" message="Belum ada nota pada rentang ini." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">No. Nota</th>
                <th class="px-2 py-1 text-left font-medium">Tanggal</th>
                <th class="px-2 py-1 text-left font-medium">Divisi</th>
                <th class="px-2 py-1 text-left font-medium">Status</th>
                <th v-if="adaNilai(data.nota)" class="px-2 py-1 text-right font-medium">Nilai</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="n in data.nota" :key="n.no_transaksi">
                <td class="px-2 py-1 text-ink">{{ n.no_transaksi }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ n.tanggal }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ n.divisi || "—" }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ n.status || "—" }}</td>
                <td v-if="adaNilai(data.nota)" class="px-2 py-1 text-right text-ink">
                  {{ rp.format(n.nilai || 0) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </Modal>
</template>
