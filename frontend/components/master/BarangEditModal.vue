<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import Modal from "@/components/ui/Modal.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import { useUiStore } from "@/stores/ui.js";

// Modal edit barang (harga per satuan + status ketersediaan) — dipakai
// Update Barang dan Pergerakan Harga supaya tampilannya sama persis.
// `item` = satu baris format list_barang_edit; null berarti modal tertutup.
const props = defineProps({
  item: { type: Object, default: null },
  isRetail: { type: Boolean, default: false },
  // Halaman tujuan redirect setelah simpan (endpoint update-barang menerima
  // `redirect_to` supaya tidak terlempar balik ke Update Barang).
  redirectTo: { type: String, default: "/admin-panel/master/update-barang" },
});
const emit = defineEmits(["close"]);

const ui = useUiStore();

const num = (n) => (n ?? 0).toLocaleString("id-ID");
const rupiah = (n) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(n || 0);

const statusOptions = [
  { value: "1", label: "Aktif" },
  { value: "0", label: "Non-aktif" },
  { value: "2", label: "Tidak dijual (sembunyikan)" },
];

const priceForm = useForm({ kd_barang: "", nama: "", prices: {}, redirect_to: props.redirectTo });
const statusSel = reactive({ m_barang: "1", m_barang_divisi: "1", m_barang_satuan: "1" });
const confirmOpen = ref(false);

watch(
  () => props.item,
  (item) => {
    confirmOpen.value = false;
    if (!item) return;
    priceForm.kd_barang = item.kd_barang;
    priceForm.nama = item.nama;
    priceForm.prices = Object.fromEntries(item.satuan.map((u) => [u.kd_satuan, u.harga_jual]));
    priceForm.redirect_to = props.redirectTo;
    statusSel.m_barang = item.status || "1";
    statusSel.m_barang_divisi = item.divisi[0]?.status || "1";
    statusSel.m_barang_satuan = item.satuan[0]?.status || "1";
  },
  { immediate: true },
);

const priceDiff = computed(() => {
  if (!props.item) return [];
  return props.item.satuan
    .map((u) => ({
      kd_satuan: u.kd_satuan,
      lama: u.harga_jual,
      baru: Number(priceForm.prices[u.kd_satuan]) || 0,
    }))
    .filter((d) => d.lama !== d.baru);
});

const liveMargin = (unit) => {
  const harga = Number(priceForm.prices[unit.kd_satuan]) || 0;
  const modal = unit.modal || 0;
  return modal > 0 ? ((harga - modal) / modal) * 100 : 0;
};

// Retail: margin -> harga (kebalikan dari liveMargin). Modal tanpa nilai
// (0/kosong) tidak punya basis hitung, jadi input margin diabaikan.
function setHargaFromMargin(unit, marginStr) {
  const margin = Number(marginStr);
  const modal = unit.modal || 0;
  if (!modal || Number.isNaN(margin)) return;
  priceForm.prices[unit.kd_satuan] = Math.round(modal * (1 + margin / 100));
}

function confirmSave() {
  confirmOpen.value = false;
  saveHarga();
}

function saveHarga() {
  priceForm.post("/admin-panel/master/update-barang/harga", {
    preserveScroll: true,
    onSuccess: () => {
      emit("close");
      ui.pushToast("Harga berhasil disimpan.", "success");
    },
  });
}

function saveStatus(table) {
  router.post(
    "/admin-panel/master/update-barang/status",
    {
      kd_barang: props.item.kd_barang,
      nama: props.item.nama,
      table,
      status: statusSel[table],
      redirect_to: props.redirectTo,
    },
    { preserveScroll: true },
  );
}
</script>

<template>
  <Modal :show="!!item" :title="item ? `${item.kd_barang} — ${item.nama}` : ''" size="md" @close="emit('close')">
    <div v-if="item" class="max-h-[70vh] space-y-2 overflow-y-auto scroll-slim">
      <!-- Harga per satuan -->
      <div>
        <h4 class="mb-1 text-xs font-semibold text-ink">Harga Jual per Satuan</h4>
        <div class="space-y-1.5">
          <div
            v-for="u in item.satuan"
            :key="u.kd_satuan"
            class="flex flex-col gap-1.5 rounded border-l-4 border-l-brand-600 bg-surface-2 p-2 sm:flex-row sm:items-end sm:gap-1.5"
          >
            <div class="min-w-max text-xs font-medium text-ink">
              {{ u.satuan || u.kd_satuan }}
              <span class="text-ink-muted">×{{ num(u.jumlah) }}</span>
            </div>
            <Input v-model="priceForm.prices[u.kd_satuan]" type="number" label="Harga" size="sm" class="sm:w-32" />

            <!-- Margin untuk grosir (locked) -->
            <div v-if="!isRetail" class="text-xs">
              <p class="text-[0.65rem] text-ink-muted">Margin</p>
              <input
                type="text"
                disabled
                :value="u.margin.toFixed(2) + '%'"
                class="rounded border border-border-default bg-surface-3 px-1.5 py-1 text-xs text-ink-muted cursor-not-allowed"
              />
            </div>

            <!-- Margin untuk retail: harga & margin saling mengikuti -->
            <template v-if="isRetail">
              <div class="text-xs">
                <p class="text-[0.65rem] text-ink-muted">Modal</p>
                <p class="font-medium text-ink text-xs">{{ rupiah(u.modal) }}</p>
              </div>
              <Input
                :model-value="liveMargin(u).toFixed(2)"
                @update:model-value="(v) => setHargaFromMargin(u, v)"
                type="number"
                label="Margin (%)"
                size="sm"
                class="sm:w-24"
              />
            </template>

            <!-- Save button aligned -->
            <Button
              v-if="item.satuan.indexOf(u) === item.satuan.length - 1"
              variant="success"
              size="sm"
              :loading="priceForm.processing"
              @click="confirmOpen = true"
            >
              Simpan
            </Button>
          </div>
        </div>
      </div>

      <!-- Status Ketersediaan -->
      <div>
        <h4 class="mb-1 text-xs font-semibold text-ink">Status Ketersediaan</h4>
        <div class="grid gap-1.5 sm:grid-cols-3">
          <div class="rounded border border-border-default p-2">
            <Select v-model="statusSel.m_barang" label="Barang" :options="statusOptions" />
            <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang')">Simpan</Button>
          </div>
          <div class="rounded border border-border-default p-2">
            <Select v-model="statusSel.m_barang_divisi" label="Divisi" :options="statusOptions" />
            <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang_divisi')">Simpan</Button>
          </div>
          <div class="rounded border border-border-default p-2">
            <Select v-model="statusSel.m_barang_satuan" label="Satuan" :options="statusOptions" />
            <Button variant="danger" size="sm" class="mt-1 w-full" @click="saveStatus('m_barang_satuan')">Simpan</Button>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <Button variant="ghost" @click="emit('close')">Tutup</Button>
    </template>
  </Modal>

  <Modal :show="confirmOpen" title="Konfirmasi Perubahan Harga" @close="confirmOpen = false">
    <Banner
      v-if="priceDiff.length"
      variant="warning"
      message="Perubahan harga langsung tersimpan ke database aktif dan berlaku untuk transaksi berikutnya. Pastikan nilai sudah benar."
      class="mb-3"
    />
    <table class="w-full text-sm">
      <thead>
        <tr class="text-ink-muted">
          <th class="py-1 text-left">Satuan</th>
          <th class="py-1 text-right">Harga Lama</th>
          <th class="py-1 text-right">Harga Baru</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in priceDiff" :key="d.kd_satuan" class="border-t border-border-default">
          <td class="py-1">{{ d.kd_satuan }}</td>
          <td class="py-1 text-right text-ink-muted">{{ d.lama }}</td>
          <td class="py-1 text-right font-semibold text-ink">{{ d.baru }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!priceDiff.length" class="text-sm text-ink-muted">Tidak ada perubahan harga.</p>
    <template #footer>
      <Button variant="ghost" @click="confirmOpen = false">Batal</Button>
      <Button variant="primary" :disabled="!priceDiff.length" @click="confirmSave">Simpan</Button>
    </template>
  </Modal>
</template>
