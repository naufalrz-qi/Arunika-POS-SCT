<script setup>
/**
 * Panel detail satu dokumen di Nota Tanggal Mundur: isinya sekarang dan
 * riwayat versinya, dibangun ulang dari jejak trigger legacy (tbl_log_transaksi).
 *
 * Kenapa riwayat, bukan cuma isi: saat nota diedit, legacy menimpa waktu simpan
 * dan kasir di nota dengan waktu dan akun pengedit. Isi sekarang tak bisa
 * menjawab "siapa yang membuat, siapa yang mengubah apa" — hanya log yang bisa.
 *
 * Kolom harga/subtotal/total bisa TIDAK ADA di respons (izin uang dicabut di
 * server), jadi tampilannya harus tahan kalau field itu tak pernah datang.
 */
import { computed, ref, watch } from "vue";
import { Link } from "@inertiajs/vue3";
import axios from "axios";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Banner from "@/components/ui/Banner.vue";
import Badge from "@/components/ui/Badge.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import { tanggalJam } from "@/utils/tanggal";

const props = defineProps({
  // Baris tabel yang diklik ({ jenis, no_dokumen, ... }), atau null.
  baris: { type: Object, default: null },
});
const emit = defineEmits(["close"]);

const URL = "/admin-panel/analitik/nota-mundur/detail";

const loading = ref(false);
const error = ref("");
const data = ref(null);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
const ada = (rows, key) => (rows || []).some((r) => r[key] !== undefined);

watch(
  () => props.baris && `${props.baris.jenis}|${props.baris.no_dokumen}`,
  async (kunci) => {
    data.value = null;
    error.value = "";
    if (!kunci) return;
    loading.value = true;
    try {
      const { data: res } = await axios.get(URL, {
        params: { jenis: props.baris.jenis, no: props.baris.no_dokumen },
      });
      if (res.error) error.value = res.error;
      else data.value = res;
    } catch (e) {
      error.value = e?.response?.data?.error || "Nota gagal dimuat. Coba lagi.";
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

const WARNA_AKSI = { Dibuat: "success", "Dibuat ulang": "warning", Diedit: "brand" };
// Bandingkan bagian TANGGAL dari string "YYYY-MM-DD HH:MM" kiriman server —
// bukan lewat Date, supaya zona waktu peramban tak menggeser harinya.
const bedaHari = (t) => !!t.tanggal_server && !!t.tanggal && t.tanggal.slice(0, 10) !== t.tanggal_server.slice(0, 10);
const adaBarangBerubah = (b) => b && ((b.ditambah || []).length || (b.dihapus || []).length || (b.diubah || []).length);
const judul = computed(() => (props.baris ? `${props.baris.jenis} ${props.baris.no_dokumen}` : ""));
</script>

<template>
  <Modal :show="!!baris" size="lg" :title="judul" @close="emit('close')">
    <div v-if="loading" class="flex items-center justify-center gap-2 py-10 text-ink-muted">
      <Spinner /> <span class="text-sm">Memuat nota…</span>
    </div>

    <Banner v-else-if="error" variant="warning" :message="error" />

    <div v-else-if="data" class="space-y-5">
      <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt class="text-xs text-ink-subtle">Tanggal nota</dt>
          <dd class="text-ink">{{ data.header.tanggal ? tanggalJam(data.header.tanggal) : "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Terakhir disimpan</dt>
          <dd class="text-ink">{{ data.header.tanggal_server ? tanggalJam(data.header.tanggal_server) : "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Divisi</dt>
          <dd class="text-ink">{{ data.header.divisi || "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Pelanggan / Supplier</dt>
          <dd class="text-ink">{{ data.header.pihak || "—" }}</dd>
        </div>
        <div>
          <!-- Pembuat ATAU pengedit terakhir — riwayat di bawah yang membedakan. -->
          <dt class="text-xs text-ink-subtle">Nama kasir di nota</dt>
          <dd class="text-ink">{{ data.header.kasir_nota }}</dd>
        </div>
        <div v-if="data.total_bersih !== undefined && data.total_bersih !== null">
          <dt class="text-xs text-ink-subtle">Total</dt>
          <dd class="text-ink">{{ rp.format(data.total_bersih) }}</dd>
        </div>
        <div class="col-span-2 sm:col-span-3">
          <dt class="text-xs text-ink-subtle">Keterangan</dt>
          <dd class="text-ink">{{ data.header.keterangan || "—" }}</dd>
        </div>
      </dl>

      <section v-if="data.barang">
        <h4 class="mb-2 text-sm font-semibold text-ink">Barang saat ini</h4>
        <EmptyState v-if="!data.barang.length" message="Nota ini tidak berisi barang." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Barang</th>
                <th class="px-2 py-1 text-left font-medium">Satuan</th>
                <th class="px-2 py-1 text-right font-medium">Qty</th>
                <th v-if="ada(data.barang, 'harga_jual')" class="px-2 py-1 text-right font-medium">Harga</th>
                <th v-if="ada(data.barang, 'subtotal')" class="px-2 py-1 text-right font-medium">Subtotal</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="(b, i) in data.barang" :key="i">
                <td class="px-2 py-1 text-ink">
                  {{ b.barang || b.kd_barang }} <span class="text-xs text-ink-subtle">{{ b.kd_barang }}</span>
                </td>
                <td class="px-2 py-1 text-ink-muted">{{ b.satuan }}</td>
                <td class="px-2 py-1 text-right text-ink">{{ nf.format(b.qty) }}</td>
                <td v-if="ada(data.barang, 'harga_jual')" class="px-2 py-1 text-right text-ink">{{ rp.format(b.harga_jual || 0) }}</td>
                <td v-if="ada(data.barang, 'subtotal')" class="px-2 py-1 text-right text-ink">{{ rp.format(b.subtotal || 0) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Cara auditor mengenali nota bertanggal salah: nomornya menyambung
           urutan hari itu, tapi waktu simpannya tak nyambung dengan tetangganya. -->
      <section v-if="data.tetangga && data.tetangga.length">
        <h4 class="mb-1 text-sm font-semibold text-ink">Nota lain di tanggal yang sama</h4>
        <p class="mb-2 text-xs text-ink-subtle">
          Ada {{ nf.format(data.jumlah_hari_itu) }} nota bernomor tanggal ini<template v-if="data.terakhir_hari_itu">,
          dan nota ini yang terakhir</template>. Jam yang ditandai berarti nota itu disimpan di hari lain.
        </p>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">No. Nota</th>
                <th class="px-2 py-1 text-left font-medium">Tanggal nota</th>
                <th class="px-2 py-1 text-left font-medium">Disimpan</th>
                <th class="px-2 py-1 text-left font-medium">Kasir</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="t in data.tetangga" :key="t.no" :class="t.ini ? 'bg-brand-bg font-medium' : ''">
                <td class="px-2 py-1 text-ink">{{ t.no }}</td>
                <td class="px-2 py-1 text-ink-muted">{{ tanggalJam(t.tanggal) }}</td>
                <td class="px-2 py-1" :class="bedaHari(t) ? 'font-semibold text-warning-fg' : 'text-ink-muted'">
                  {{ t.tanggal_server ? tanggalJam(t.tanggal_server) : "—" }}
                </td>
                <td class="px-2 py-1 text-ink-muted">{{ t.kasir }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Riwayat</h4>
        <Banner v-if="!data.log_siap" variant="info">
          Riwayat nota belum bisa ditampilkan di server ini.
          <Link href="/admin-panel/bantuan#nota-mundur" class="underline underline-offset-2 hover:no-underline">Cara mengaktifkannya</Link>
        </Banner>
        <EmptyState
          v-else-if="!data.riwayat || !data.riwayat.length"
          message="Tidak ada catatan riwayat untuk nota ini. Biasanya karena notanya sudah terlalu lama."
        />
        <template v-else>
          <Banner
            v-if="data.barang_cocok === false"
            variant="warning"
            class="mb-3"
            message="Riwayat barang untuk nota ini mungkin tidak lengkap. Siapa yang mengedit dan kapan tetap benar."
          />
          <ol class="space-y-3">
            <li v-for="(p, i) in data.riwayat" :key="i" class="rounded-lg border border-border-default p-3">
              <div class="flex flex-wrap items-center gap-2 text-sm">
                <Badge :variant="WARNA_AKSI[p.aksi] || 'neutral'">{{ p.aksi }}</Badge>
                <span class="text-ink">{{ tanggalJam(p.waktu) }}</span>
                <span class="text-ink-muted">oleh</span>
                <span class="font-medium text-ink">{{ p.oleh }}</span>
                <span v-if="p.aksi !== 'Diedit'" class="text-xs text-ink-subtle">· tanggal nota {{ tanggalJam(p.tanggal_nota) }}</span>
              </div>

              <ul v-if="p.perubahan.length" class="mt-2 space-y-0.5 text-sm">
                <li v-for="(c, j) in p.perubahan" :key="j" class="text-ink-muted">
                  {{ c.label }}: <span class="text-ink line-through decoration-ink-subtle">{{ tanggalJam(c.dari) || "(kosong)" }}</span>
                  → <span class="text-ink">{{ tanggalJam(c.ke) || "(kosong)" }}</span>
                </li>
              </ul>

              <div v-if="p.barang && p.barang.isi" class="mt-2 text-sm text-ink-muted">
                Isi awal: {{ p.barang.isi.length }} barang
                <details class="mt-1">
                  <summary class="cursor-pointer text-xs text-brand-fg">lihat</summary>
                  <ul class="mt-1 space-y-0.5">
                    <li v-for="(b, j) in p.barang.isi" :key="j">
                      {{ b.barang || b.kd_barang }} — {{ nf.format(b.qty) }} {{ b.satuan }}
                      <template v-if="b.harga_jual !== undefined"> @ {{ rp.format(b.harga_jual || 0) }}</template>
                    </li>
                  </ul>
                </details>
              </div>

              <div v-else-if="adaBarangBerubah(p.barang)" class="mt-2 space-y-0.5 text-sm">
                <p v-for="(b, j) in p.barang.ditambah" :key="`t${j}`" class="text-success-fg">
                  + {{ b.barang || b.kd_barang }} — {{ nf.format(b.qty) }} {{ b.satuan }}
                  <template v-if="b.harga_jual !== undefined"> @ {{ rp.format(b.harga_jual || 0) }}</template>
                </p>
                <p v-for="(b, j) in p.barang.dihapus" :key="`h${j}`" class="text-danger-fg">
                  − {{ b.barang || b.kd_barang }} — {{ nf.format(b.qty) }} {{ b.satuan }}
                </p>
                <p v-for="(b, j) in p.barang.diubah" :key="`u${j}`" class="text-ink">
                  ~ {{ b.barang || b.kd_barang }}: qty {{ nf.format(b.qty_dari) }} → {{ nf.format(b.qty) }}
                  <template v-if="b.harga_jual !== undefined && b.harga_jual !== b.harga_jual_dari">
                    , harga {{ rp.format(b.harga_jual_dari || 0) }} → {{ rp.format(b.harga_jual || 0) }}
                  </template>
                </p>
              </div>
              <p v-else-if="p.aksi === 'Diedit' && !p.perubahan.length && p.barang" class="mt-2 text-sm text-ink-subtle">
                Disimpan ulang tanpa ada yang berubah.
              </p>
            </li>
          </ol>
        </template>
      </section>
    </div>
  </Modal>
</template>
