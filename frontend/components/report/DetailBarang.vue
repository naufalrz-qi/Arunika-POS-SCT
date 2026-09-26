<script setup>
/**
 * Panel detail satu barang di Deadstock: stok per divisi dan gerakan terakhirnya.
 *
 * Stok per divisi sudah ikut di baris tabel (dihitung dari data yang sama, tanpa
 * query tambahan). Gerakan dimuat SAAT DIKLIK, satu kd_barang per permintaan —
 * pola DetailPelanggan.vue — dan selalu SEMUA divisi, sama seperti kolom Jual
 * Terakhir (lihat _deadstock_rows di apps/monitoring/views.py).
 *
 * `harga` bisa TIDAK ADA di respons (salah satu izin harga dicabut — disaring di
 * server), begitu pula `nilai_stok` di baris; keduanya keadaan normal.
 */
import { computed, ref, watch } from "vue";
import axios from "axios";
import Modal from "@/components/ui/Modal.vue";
import Spinner from "@/components/ui/Spinner.vue";
import Banner from "@/components/ui/Banner.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import { useUserStore } from "@/stores/user";
import { tanggal, tanggalJam } from "@/utils/tanggal.js";

const props = defineProps({
  // Baris tabel Deadstock yang diklik, atau null.
  baris: { type: Object, default: null },
});
const emit = defineEmits(["close"]);

const URL = "/admin-panel/analitik/deadstock/detail";

const loading = ref(false);
const error = ref("");
const data = ref(null);

const nf = new Intl.NumberFormat("id-ID");
const rp = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
const adaHarga = computed(() => (data.value?.gerakan || []).some((g) => g.harga !== undefined));
// Satu divisi saja (toko grosir, atau tabel sedang disaring per divisi) = kolomnya
// cuma mengulang nama yang sama di setiap baris.
const adaDivisi = computed(() => new Set((data.value?.gerakan || []).map((g) => g.divisi)).size > 1);

const userStore = useUserStore();
const bolehHistori = computed(() => userStore.allowedMenus.some((m) => m.key === "barang_histori"));
const hrefHistori = computed(
  () => `/admin-panel/inventory/histori?${new URLSearchParams({ kd_barang: props.baris?.kd_barang || "" })}`,
);

watch(
  () => props.baris?.kd_barang,
  async (kd) => {
    data.value = null;
    error.value = "";
    if (!kd) return;
    loading.value = true;
    try {
      const { data: res } = await axios.get(URL, { params: { kd_barang: kd } });
      if (res.error) error.value = res.error;
      else data.value = res;
    } catch (e) {
      error.value = e.response?.data?.error || "Gagal memuat detail barang. Coba lagi.";
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);
</script>

<template>
  <Modal :show="!!baris" size="lg" :title="baris ? baris.barang || baris.kd_barang : ''" @close="emit('close')">
    <div v-if="baris" class="space-y-5">
      <dl class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt class="text-xs text-ink-subtle">Kode</dt>
          <dd class="text-ink">{{ baris.kd_barang }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Kategori</dt>
          <dd class="text-ink">{{ baris.kategori || "—" }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Stok</dt>
          <dd class="text-ink">{{ nf.format(baris.qty_stok) }}</dd>
        </div>
        <div v-if="baris.nilai_stok !== undefined">
          <dt class="text-xs text-ink-subtle">Nilai Stok</dt>
          <dd class="text-ink">{{ rp.format(baris.nilai_stok) }}</dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Jual Terakhir</dt>
          <dd class="text-ink">
            <template v-if="baris.jual_terakhir">
              {{ tanggal(baris.jual_terakhir) }}
              <span class="text-xs text-ink-subtle">({{ nf.format(baris.hari_tak_laku) }} hari)</span>
            </template>
            <template v-else>Belum pernah laku</template>
          </dd>
        </div>
        <div>
          <dt class="text-xs text-ink-subtle">Beli Terakhir</dt>
          <dd class="text-ink">{{ baris.beli_terakhir ? tanggal(baris.beli_terakhir) : "—" }}</dd>
        </div>
      </dl>

      <section>
        <h4 class="mb-2 text-sm font-semibold text-ink">Stok per divisi</h4>
        <EmptyState v-if="!(baris.per_divisi || []).length" message="Tidak ada rincian divisi." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Divisi</th>
                <th class="px-2 py-1 text-right font-medium">Stok</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border-default">
              <tr v-for="d in baris.per_divisi" :key="d.divisi">
                <td class="px-2 py-1 text-ink">{{ d.divisi }}</td>
                <td class="px-2 py-1 text-right text-ink">{{ nf.format(d.stok) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div class="mb-2 flex items-baseline justify-between gap-2">
          <h4 class="text-sm font-semibold text-ink">
            Gerakan terakhir
            <span v-if="data" class="font-normal text-ink-subtle">
              ({{ data.gerakan.length }} dari {{ nf.format(data.jml_gerakan) }})
            </span>
          </h4>
          <a
            v-if="bolehHistori"
            :href="hrefHistori"
            class="text-xs text-brand-fg underline underline-offset-2 hover:no-underline"
          >
            Buka di Barang Histori
          </a>
        </div>

        <div v-if="loading" class="flex items-center justify-center gap-2 py-8 text-ink-muted">
          <Spinner /> <span class="text-sm">Mengambil gerakan barang…</span>
        </div>
        <Banner v-else-if="error" variant="warning" :message="error" />
        <template v-else-if="data">
          <EmptyState v-if="!data.gerakan.length" message="Belum ada gerakan tercatat." />
          <div v-else class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="text-xs text-ink-subtle">
                <tr class="border-b border-border-default">
                  <th class="px-2 py-1 text-left font-medium">Tanggal</th>
                  <th class="px-2 py-1 text-left font-medium">Transaksi</th>
                  <th class="px-2 py-1 text-left font-medium">No.</th>
                  <th v-if="adaDivisi" class="px-2 py-1 text-left font-medium">Divisi</th>
                  <th class="px-2 py-1 text-right font-medium">Masuk</th>
                  <th class="px-2 py-1 text-right font-medium">Keluar</th>
                  <th class="px-2 py-1 text-left font-medium">Satuan</th>
                  <th v-if="adaHarga" class="px-2 py-1 text-right font-medium">Harga</th>
                  <th class="px-2 py-1 text-right font-medium">Saldo</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border-default">
                <tr v-for="(g, i) in data.gerakan" :key="i">
                  <td class="whitespace-nowrap px-2 py-1 text-ink-muted">{{ tanggalJam(g.tanggal) }}</td>
                  <td class="px-2 py-1 text-ink">{{ g.transaksi }}</td>
                  <td class="whitespace-nowrap px-2 py-1 text-ink-muted">{{ g.no_transaksi || "—" }}</td>
                  <td v-if="adaDivisi" class="whitespace-nowrap px-2 py-1 text-ink-muted">{{ g.divisi || "—" }}</td>
                  <td class="px-2 py-1 text-right text-ink">{{ g.debet ? nf.format(g.debet) : "" }}</td>
                  <td class="px-2 py-1 text-right text-ink">{{ g.kredit ? nf.format(g.kredit) : "" }}</td>
                  <td class="px-2 py-1 text-ink-muted">{{ g.satuan }}</td>
                  <td v-if="adaHarga" class="px-2 py-1 text-right text-ink">
                    {{ g.harga !== undefined ? rp.format(g.harga) : "" }}
                  </td>
                  <td class="px-2 py-1 text-right text-ink">{{ nf.format(g.saldo) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>
    </div>
  </Modal>
</template>
