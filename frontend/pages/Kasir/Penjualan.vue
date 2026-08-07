<script setup>
import { computed, ref } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import EmptyState from "@/components/ui/EmptyState.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

// Sama dengan formatter di BaseTable.vue; tak ada util bersama untuk ini.
const rp = new Intl.NumberFormat("id-ID", {
  style: "currency", currency: "IDR", maximumFractionDigits: 0,
});
const formatRupiah = (v) => rp.format(Number(v) || 0);

const props = defineProps({
  nota: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  kd_user: { type: String, default: "" },
  kd_divisi: { type: String, default: "" },
});

const isi = computed(() => props.nota || {});
const opsi = computed(() => isi.value.opsi || {});
const hasilCari = computed(() => isi.value.hasil_cari || []);

const cari = ref(props.filters.cari || "");
function cariBarang() {
  router.get("/kasir/penjualan", { cari: cari.value },
    { preserveState: true, preserveScroll: true });
}

// --- Baris nota (hanya di layar sampai disimpan) ---------------------------
const baris = ref([]);
function tambah(b) {
  const ada = baris.value.find(
    (x) => x.kd_barang === b.kd_barang && x.kd_satuan === b.kd_satuan);
  if (ada) {
    ada.qty = Number(ada.qty) + 1;
    return;
  }
  baris.value.push({
    kd_barang: b.kd_barang, nama: b.nama, kd_satuan: b.kd_satuan,
    satuan: b.satuan, harga_jual: b.harga_jual, qty: 1,
    diskon1: 0, diskon2: 0, diskon3: 0, diskon4: 0,
  });
}
function hapus(i) {
  baris.value.splice(i, 1);
}

// Cerminan ghb() di apps/transactions/penjualan.py — dual-mode: nilai di (-1,1)
// berarti persen, selebihnya rupiah. HANYA untuk pratinjau; angka yang disimpan
// dihitung ulang di server, dan server yang berwenang.
function ghb(harga, diskon) {
  if (harga <= 0) return harga;
  let v = harga;
  for (const d of diskon) {
    const n = Number(d) || 0;
    v = n > -1 && n < 1 ? v * (1 - n) : v - n;
  }
  return v;
}
const diskonUang = ref(0);
const pajak = ref(0);
const subtotal = (b) => ghb(Number(b.harga_jual), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]) * Number(b.qty || 0);
const total = computed(() => {
  const net = baris.value.reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + (Number(pajak.value) || 0)) - (Number(diskonUang.value) || 0);
});

// --- Simpan ----------------------------------------------------------------
const form = useForm({
  kd_customer: "", kd_jenis: "", kd_kas: "", kd_voucher: "", kd_pegawai: "",
  keterangan: "", diskon_uang: 0, pajak: 0, status: 1, items: [],
});
const siap = computed(
  () => Boolean(props.kd_user && props.kd_divisi) && baris.value.length > 0
    && form.kd_customer && form.kd_jenis && form.kd_kas && form.kd_voucher && form.kd_pegawai,
);
function simpan() {
  form.items = baris.value.map((b) => ({
    kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, qty: Number(b.qty),
    harga_jual: Number(b.harga_jual), diskon1: Number(b.diskon1) || 0,
    diskon2: Number(b.diskon2) || 0, diskon3: Number(b.diskon3) || 0,
    diskon4: Number(b.diskon4) || 0,
  }));
  form.diskon_uang = Number(diskonUang.value) || 0;
  form.pajak = Number(pajak.value) || 0;
  form.post("/kasir/penjualan/save", {
    preserveScroll: true,
    onSuccess: () => {
      baris.value = [];
      diskonUang.value = 0;
      pajak.value = 0;
    },
  });
}
</script>

<template>
  <AdminLayout title="Buat Nota">
    <!-- Akun tanpa tautan legacy tak bisa membuat nota sama sekali (kd_user
         NOT NULL). Dikatakan di awal, bukan setelah kasir mengisi sekeranjang. -->
    <Banner
      v-if="!kd_user || !kd_divisi"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan ke user legacy dan divisi, jadi nota belum bisa dibuat. Minta pengelola aplikasi mengisinya di Manajemen User."
    />

    <Card class="mb-4">
      <form class="flex flex-wrap items-end gap-3" @submit.prevent="cariBarang">
        <Input
          v-model="cari"
          label="Cari barang"
          placeholder="Kode atau nama barang…"
          class="min-w-[18rem] flex-1"
        />
        <Button type="submit" variant="secondary">Cari</Button>
      </form>
    </Card>

    <Deferred data="nota">
      <template #fallback>
        <LoadingCard message="Menyiapkan layar nota…" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <div class="grid gap-4 lg:grid-cols-3">
        <!-- Hasil cari -->
        <Card class="lg:col-span-1" title="Hasil pencarian">
          <EmptyState v-if="!hasilCari.length" message="Ketik kode atau nama barang, lalu tekan Cari." />
          <ul v-else class="divide-y divide-border-default">
            <li
              v-for="b in hasilCari"
              :key="`${b.kd_barang}-${b.kd_satuan}`"
              class="flex items-center justify-between gap-2 py-2"
            >
              <div class="min-w-0">
                <p class="truncate text-sm text-ink">{{ b.nama }}</p>
                <p class="text-xs text-ink-subtle">
                  {{ b.kd_barang }} · {{ b.satuan }} · {{ formatRupiah(b.harga_jual) }}
                </p>
              </div>
              <Button size="sm" @click="tambah(b)">Tambah</Button>
            </li>
          </ul>
        </Card>

        <!-- Nota -->
        <Card class="lg:col-span-2" title="Nota">
          <div class="grid gap-3 sm:grid-cols-2">
            <Select v-model="form.kd_customer" label="Pelanggan *" :options="opsi.pelanggan || []" placeholder="Pilih…" />
            <Select v-model="form.kd_jenis" label="Jenis Bayar *" :options="opsi.jenis_bayar || []" placeholder="Pilih…" />
            <Select v-model="form.kd_kas" label="Kas *" :options="opsi.kas || []" placeholder="Pilih…" />
            <Select v-model="form.kd_voucher" label="Voucher *" :options="opsi.voucher || []" placeholder="Pilih…" />
            <Select v-model="form.kd_pegawai" label="Pegawai *" :options="opsi.pegawai || []" placeholder="Pilih…" />
            <Input v-model="form.keterangan" label="Keterangan" placeholder="-" />
          </div>

          <div class="mt-4 overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="text-xs text-ink-subtle">
                <tr class="border-b border-border-default">
                  <th class="px-2 py-1 text-left font-medium">Barang</th>
                  <th class="px-2 py-1 text-right font-medium">Qty</th>
                  <th class="px-2 py-1 text-right font-medium">Harga</th>
                  <th class="px-2 py-1 text-right font-medium">Diskon</th>
                  <th class="px-2 py-1 text-right font-medium">Subtotal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!baris.length">
                  <td colspan="6" class="px-2 py-4 text-center text-ink-subtle">
                    Belum ada barang di nota ini.
                  </td>
                </tr>
                <tr v-for="(b, i) in baris" :key="i" class="border-b border-border-default">
                  <td class="px-2 py-1">
                    <p class="text-ink">{{ b.nama }}</p>
                    <p class="text-xs text-ink-subtle">{{ b.kd_barang }} · {{ b.satuan }}</p>
                  </td>
                  <td class="px-2 py-1 text-right">
                    <input v-model="b.qty" type="number" min="0" step="any" class="w-20 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
                  </td>
                  <td class="px-2 py-1 text-right">
                    <input v-model="b.harga_jual" type="number" min="0" step="any" class="w-28 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
                  </td>
                  <td class="px-2 py-1 text-right">
                    <input v-model="b.diskon1" type="number" step="any" class="w-24 rounded-control border border-border-default bg-surface-1 px-2 py-1 text-right" />
                  </td>
                  <td class="px-2 py-1 text-right tabular-nums">{{ formatRupiah(subtotal(b)) }}</td>
                  <td class="px-2 py-1 text-right">
                    <Button size="sm" variant="secondary" @click="hapus(i)">Hapus</Button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <Input v-model="diskonUang" type="number" label="Diskon Rupiah" />
            <Input v-model="pajak" type="number" step="any" label="Pajak (fraksi, 0.05 = 5%)" />
          </div>

          <div class="mt-4 flex items-center justify-between border-t border-border-default pt-3">
            <div>
              <p class="text-xs text-ink-subtle">Total</p>
              <p class="text-xl font-semibold tabular-nums text-ink">{{ formatRupiah(total) }}</p>
              <p class="text-xs text-ink-subtle">
                Angka ini pratinjau; nilai yang disimpan dihitung ulang di server.
              </p>
            </div>
            <Button :disabled="!siap" :loading="form.processing" @click="simpan">
              Simpan Nota
            </Button>
          </div>
        </Card>
      </div>
    </Deferred>
  </AdminLayout>
</template>
