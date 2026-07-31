<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useForm, router } from "@inertiajs/vue3";
import Modal from "@/components/ui/Modal.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import { useUiStore } from "@/stores/ui.js";
import { suggestFor } from "@/utils/priceSuggestion.js";

// Modal edit barang (harga per satuan + status ketersediaan) — dipakai
// Update Barang dan Pergerakan Harga supaya tampilannya sama persis.
// `item` = satu baris format list_barang_edit; null berarti modal tertutup.
const props = defineProps({
  item: { type: Object, default: null },
  isRetail: { type: Boolean, default: false },
  // Nama & keterangan = identitas katalog yang dipakai bersama seluruh cabang,
  // jadi hanya server gudang yang boleh mengubahnya. Ini SEMATA tampilan —
  // penjaga penulisannya di master.update_nama_keterangan (server-side).
  bolehEditIdentitas: { type: Boolean, default: false },
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

// Identitas (nama & keterangan) — form sendiri, tak dicampur priceForm: keduanya
// menulis ke endpoint berbeda dan boleh disimpan terpisah.
const identitasForm = useForm({ kd_barang: "", nama: "", keterangan: "", redirect_to: props.redirectTo });
const identitasConfirmOpen = ref(false);
const MAX_IDENTITAS = 50;  // varchar(50) di m_barang, diverifikasi di server

watch(
  () => props.item,
  (item) => {
    confirmOpen.value = false;
    if (!item) return;
    priceForm.kd_barang = item.kd_barang;
    priceForm.nama = item.nama;
    priceForm.prices = Object.fromEntries(item.satuan.map((u) => [u.kd_satuan, u.harga_jual]));
    priceForm.redirect_to = props.redirectTo;
    identitasForm.kd_barang = item.kd_barang;
    identitasForm.nama = item.nama || "";
    identitasForm.keterangan = item.keterangan || "";
    identitasForm.redirect_to = props.redirectTo;
    identitasConfirmOpen.value = false;
    statusSel.m_barang = item.status || "1";
    statusSel.m_barang_divisi = item.divisi[0]?.status || "1";
    statusSel.m_barang_satuan = item.satuan[0]?.status || "1";
  },
  { immediate: true },
);

// Saran harga dari kolom keterangan (mis. "ECER 3.450.000(50%)") untuk satuan
// dasar barang ini — cuma hint, user tetap harus klik untuk isi lalu Simpan.
const suggestion = computed(() => suggestFor(props.item));

function applySuggestion() {
  const s = suggestion.value;
  if (!s) return;
  priceForm.prices[s.kd_satuan] = s.harga_baru;
}

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

// Harga wajib bilangan bulat rupiah. Nilai seperti 3000.001 diterima kolom
// pecahan di DB tapi tampil "Rp3.000,001" dan merusak pembulatan di kasir.
// Backend (update_harga) tetap penjaga terakhir; ini supaya user tahu lebih awal.
const hargaBulat = (v) => {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 && Number.isInteger(n);
};

// Satuan yang harga BARU-nya (hasil ketikan) belum bulat — memblokir Simpan.
const hargaInvalid = computed(() => {
  if (!props.item) return [];
  return props.item.satuan
    .filter((u) => !hargaBulat(priceForm.prices[u.kd_satuan]))
    .map((u) => u.satuan || u.kd_satuan);
});

// Satuan yang harga TERSIMPAN-nya sudah berpecahan — pengecekan data lama.
const hargaLamaPecahan = computed(() => {
  if (!props.item) return [];
  return props.item.satuan
    .filter((u) => !Number.isInteger(Number(u.harga_jual)))
    .map((u) => `${u.satuan || u.kd_satuan}: ${rupiah(u.harga_jual)}`);
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

const identitasDiff = computed(() => {
  if (!props.item) return [];
  const pasangan = [
    { label: "Nama", lama: props.item.nama || "", baru: (identitasForm.nama || "").trim() },
    { label: "Keterangan", lama: props.item.keterangan || "", baru: (identitasForm.keterangan || "").trim() },
  ];
  return pasangan.filter((d) => d.lama !== d.baru);
});

// Nama kosong ditolak: barang tanpa nama tak bisa dikenali di nota maupun laporan.
const identitasInvalid = computed(() => !(identitasForm.nama || "").trim());

function simpanIdentitas() {
  identitasConfirmOpen.value = false;
  identitasForm
    .transform((d) => ({ ...d, nama: (d.nama || "").trim(), keterangan: (d.keterangan || "").trim() }))
    .post("/admin-panel/master/update-barang/identitas", {
      preserveScroll: true,
      onSuccess: () => emit("close"),
    });
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
      <!-- Identitas barang. Nama & keterangan dipakai bersama seluruh cabang
           (nota, laporan, layar kasir tiap server) dan menyebar lewat
           Sinkronisasi Master Data, jadi hanya gudang yang boleh mengubahnya.
           Di server lain field-nya dikunci DAN alasannya ditulis — field mati
           tanpa penjelasan cuma terlihat seperti aplikasi yang rusak. -->
      <div>
        <h4 class="mb-1 text-xs font-semibold text-ink">Identitas Barang</h4>
        <Banner
          v-if="!bolehEditIdentitas"
          variant="info"
          message="Nama dan keterangan barang hanya bisa diubah dari server gudang. Gudang yang memegang katalog; cabang lain menerimanya lewat Sinkronisasi Master Data. Ganti koneksi ke server gudang untuk mengubahnya."
          class="mb-1.5"
        />
        <Banner
          v-else
          variant="warning"
          message="Perubahan di sini ikut ke SEMUA cabang saat Sinkronisasi Master Data dijalankan, dan nama barang muncul di nota serta laporan lama."
          class="mb-1.5"
        />
        <div class="grid gap-1.5 sm:grid-cols-2">
          <Input
            v-model="identitasForm.nama"
            label="Nama Barang"
            size="sm"
            :disabled="!bolehEditIdentitas"
            :maxlength="MAX_IDENTITAS"
            :error="bolehEditIdentitas && identitasInvalid ? 'Nama tidak boleh kosong.' : ''"
          />
          <Input
            v-model="identitasForm.keterangan"
            label="Keterangan"
            size="sm"
            :disabled="!bolehEditIdentitas"
            :maxlength="MAX_IDENTITAS"
          />
        </div>
        <div v-if="bolehEditIdentitas" class="mt-1.5 flex items-center gap-2">
          <Button
            variant="success"
            size="sm"
            :loading="identitasForm.processing"
            :disabled="!identitasDiff.length || identitasInvalid"
            @click="identitasConfirmOpen = true"
          >
            Simpan Identitas
          </Button>
          <span v-if="!identitasDiff.length" class="text-[11px] text-ink-subtle">Belum ada perubahan.</span>
          <span v-else class="text-[11px] text-ink-subtle">
            {{ identitasDiff.length }} perubahan menunggu konfirmasi.
          </span>
        </div>
      </div>

      <!-- Harga per satuan -->
      <div>
        <h4 class="mb-1 text-xs font-semibold text-ink">Harga Jual per Satuan</h4>
        <Banner
          v-if="hargaLamaPecahan.length"
          variant="warning"
          :message="`Harga tersimpan mengandung pecahan rupiah — ${hargaLamaPecahan.join('; ')}. Bulatkan lalu Simpan.`"
          class="mb-1.5"
        />
        <Banner
          v-if="hargaInvalid.length"
          variant="danger"
          :message="`Harga harus bilangan bulat rupiah (tanpa koma) dan tidak negatif — cek satuan: ${hargaInvalid.join(', ')}.`"
          class="mb-1.5"
        />
        <div class="space-y-1.5">
          <div
            v-for="u in item.satuan"
            :key="u.kd_satuan"
            class="flex flex-col gap-1.5 rounded-control border border-border-default bg-surface-2 p-2 sm:flex-row sm:items-end sm:gap-1.5"
          >
            <div class="min-w-max text-xs font-medium text-ink">
              {{ u.satuan || u.kd_satuan }}
              <span class="text-ink-muted">×{{ num(u.jumlah) }}</span>
            </div>
            <div class="sm:w-32">
              <Input v-model="priceForm.prices[u.kd_satuan]" type="number" label="Harga" size="sm" />
              <button
                v-if="suggestion && suggestion.kd_satuan === u.kd_satuan"
                type="button"
                class="mt-1 inline-flex items-center gap-1 rounded-full bg-warning-bg px-2 py-0.5 text-[10px] font-semibold text-warning-fg hover:brightness-95"
                :title="`Dari keterangan: ${item.keterangan}`"
                @click="applySuggestion"
              >
                ✨ Saran: {{ rupiah(suggestion.harga_baru) }}
              </button>
            </div>

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
              :disabled="hargaInvalid.length > 0"
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

  <Modal
    :show="identitasConfirmOpen"
    title="Konfirmasi Perubahan Identitas Barang"
    @close="identitasConfirmOpen = false"
  >
    <div class="space-y-2">
      <Banner
        variant="warning"
        message="Nama & keterangan ikut ke semua cabang saat Sinkronisasi Master Data dijalankan. Periksa sebelum menyimpan."
      />
      <p class="text-xs text-ink-muted">{{ item ? item.kd_barang : "" }}</p>
      <div
        v-for="d in identitasDiff"
        :key="d.label"
        class="rounded border border-border-default bg-surface-2 px-3 py-2"
      >
        <p class="text-[11px] font-semibold text-ink-muted">{{ d.label }}</p>
        <p class="mt-0.5 break-words text-sm text-ink-muted line-through decoration-danger-500/60">
          {{ d.lama || "(kosong)" }}
        </p>
        <p class="break-words text-sm font-semibold text-ink">{{ d.baru || "(kosong)" }}</p>
      </div>
    </div>
    <template #footer>
      <Button variant="ghost" @click="identitasConfirmOpen = false">Batal</Button>
      <Button
        variant="primary"
        :disabled="!identitasDiff.length || identitasInvalid"
        @click="simpanIdentitas"
      >
        Simpan
      </Button>
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
      <Button variant="primary" :disabled="!priceDiff.length || hargaInvalid.length > 0" @click="confirmSave">Simpan</Button>
    </template>
  </Modal>
</template>
