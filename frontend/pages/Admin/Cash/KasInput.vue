<script setup>
import { computed } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

// Satu layar untuk Input Biaya Operasional, Penambahan Kas, dan Mutasi Kas.
// Kolom apa yang ada dan dari mana pilihannya datang ditentukan FORM/SPEC di
// apps/transactions/kas.py — satu sumber kebenaran dengan kolom yang benar-benar
// ditulis ke database, bukan daftar kedua yang pelan-pelan berbeda.
const props = defineProps({
  data: { type: Object, default: null },
  jenis: { type: String, required: true },
  label: { type: String, required: true },
  aksi_url: { type: String, required: true },
  form: { type: Array, default: () => [] },
  kolom_riwayat: { type: Array, default: () => [] },
  kd_user: { type: String, default: "" },
  kd_divisi_tautan: { type: String, default: "" },
});

const isi = computed(() => props.data || {});
const lookups = computed(() => isi.value.lookups || {});
const riwayat = computed(() => isi.value.riwayat || []);

const LABEL = {
  no_transaksi: "No. Transaksi", tanggal: "Tanggal", kd_divisi: "Divisi",
  kd_biaya: "Jenis Biaya", kd_pendapatan: "Jenis Pendapatan",
  kd_jenis: "Cara Bayar", kd_kas: "Kas",
  kd_kas_sumber: "Kas Sumber", kd_kas_tujuan: "Kas Tujuan", nominal: "Nominal",
  no_bukti: "No. Bukti", no_bukti_sumber: "Bukti Sumber",
  no_bukti_tujuan: "Bukti Tujuan", keterangan: "Keterangan", kd_user: "Petugas",
};

const columns = computed(() =>
  props.kolom_riwayat.map((k) => ({
    key: k,
    label: LABEL[k] || k,
    align: k === "nominal" ? "right" : undefined,
  })));

const kosong = () => Object.fromEntries(props.form.map((f) => [f.name, ""]));
const formData = useForm(kosong());

// Tautan wajib: tanpa kd_user transaksi ini tak bisa tercatat atas nama siapa
// pun. Dikatakan di muka — bukan sesudah nominalnya diketik — dengan menutup
// tombol Simpan sekalian, karena penolakannya toh pasti datang di server.
const bisaSimpan = computed(() => Boolean(props.kd_user) && !formData.processing);

function simpan() {
  formData.post(`${props.aksi_url}/save`, {
    preserveScroll: true,
    onSuccess: () => {
      formData.defaults(kosong());
      formData.reset();
      // Muat ulang supaya riwayat di bawah form memuat baris yang baru ditulis.
      router.reload({ only: ["data"] });
    },
  });
}
</script>

<template>
  <AdminLayout :title="label">
    <Banner
      v-if="!kd_user"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan ke user legacy untuk koneksi yang sedang aktif, jadi transaksi ini belum bisa dicatat atas nama Anda. Minta pengelola aplikasi mengisinya di Kelola Tautan User."
    />

    <!-- Form di LUAR <Deferred>: kerangkanya tampil seketika, isian pilihan
         menyusul. Yang berupa Select menunggu lookups, yang berupa teks tidak. -->
    <Card class="mb-4">
      <h2 class="mb-3 text-sm font-semibold text-ink">{{ label }} baru</h2>
      <div class="grid gap-3 sm:grid-cols-2">
        <template v-for="f in form" :key="f.name">
          <Select
            v-if="f.tipe === 'pilih'"
            v-model="formData[f.name]"
            :label="f.label"
            :options="lookups[f.opsi] || []"
            placeholder="Pilih…"
          />
          <!-- Nominal tetap type="text": servernya menerima "250.000" maupun
               "250000" (pemisah ribuan Indonesia), dan input[type=number] justru
               menolak bentuk pertama tanpa mengatakan apa-apa. -->
          <Input
            v-else
            v-model="formData[f.name]"
            :label="f.label"
            :placeholder="f.tipe === 'uang' ? 'mis. 250000' : ''"
            :class="f.name === 'keterangan' ? 'sm:col-span-2' : ''"
          />
        </template>
      </div>
      <div class="mt-4 flex items-center justify-between gap-3">
        <p class="text-xs text-ink-subtle">
          Nomor transaksi dibuat otomatis dari kode nota divisi. Tersimpan berarti
          <strong>uang sudah tercatat berpindah</strong> — tak ada layar yang bisa
          membatalkannya.
        </p>
        <Button :disabled="!bisaSimpan" :loading="formData.processing" @click="simpan">
          Simpan
        </Button>
      </div>
    </Card>

    <Deferred data="data">
      <template #fallback>
        <LoadingCard :message="`Mengambil data ${label.toLowerCase()}…`" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <Card>
        <h2 class="mb-3 text-sm font-semibold text-ink">Transaksi terakhir</h2>
        <DataTable
          :rows="riwayat"
          :columns="columns"
          :empty-message="`Belum ada ${label.toLowerCase()} di server ini.`"
        />
      </Card>
    </Deferred>
  </AdminLayout>
</template>
