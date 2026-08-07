<script setup>
import { computed, ref } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import Modal from "@/components/ui/Modal.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

// Satu layar untuk Pelanggan dan Supplier. Bentuk keduanya nyaris sama, jadi
// yang berbeda datang sebagai prop dari _MASTER di apps/master_data/master_crud.py
// — satu sumber kebenaran untuk kolom apa yang ada, bukan dua daftar yang
// pelan-pelan berbeda.
const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  entitas: { type: String, required: true },
  label: { type: String, required: true },
  kunci: { type: String, required: true },
  teks: { type: Array, default: () => [] },
  angka: { type: Array, default: () => [] },
  lookup_fields: { type: Array, default: () => [] },
  wajib: { type: Array, default: () => [] },
});

const isi = computed(() => props.data || {});
const rows = computed(() => isi.value.rows || []);
const cari = ref(props.filters.cari || "");

const LABEL = {
  nama: "Nama", alamat: "Alamat", telepon: "Telepon", fax: "Faks",
  kontak: "Kontak", hp: "HP", email: "Email", kd_kota: "Kota",
  kd_bank: "Bank", rekening: "Rekening", keterangan: "Keterangan",
  parent: "Induk", npwp_no: "No. NPWP", nppkp_no: "No. NPPKP",
  npwp_nama: "Nama NPWP", npwp_alamat: "Alamat NPWP", point: "Poin",
  limit_kredit: "Limit Kredit", disc: "Diskon", status: "Status",
  jenis: "Jenis",
};
const labelKolom = (k) => LABEL[k] || k;

const columns = computed(() => [
  { key: props.kunci, label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "alamat", label: "Alamat" },
  { key: "telepon", label: "Telepon" },
  { key: "hp", label: "HP" },
  { key: "aksi", label: "", align: "right" },
]);

function submitCari() {
  router.get(`/kasir/${props.entitas}`, { cari: cari.value },
    { preserveState: true, preserveScroll: true });
}

// Kolom berkunci-asing dirender sebagai pilihan, bukan isian bebas: database
// menolak nilai yang bukan kode nyata, jadi mengetiknya sendiri selalu gagal.
const lookups = computed(() => isi.value.lookups || {});
const semuaField = computed(() => [...props.teks, ...props.lookup_fields, ...props.angka]);
const wajibkan = (k) => (props.wajib.includes(k) ? " *" : "");
const kosong = () => Object.fromEntries(semuaField.value.map((k) => [k, ""]));

const form = useForm({ ...kosong(), [props.kunci]: "" });
const buka = ref(false);
const sedangEdit = computed(() => Boolean(form[props.kunci]));

function openCreate() {
  Object.assign(form, kosong(), { [props.kunci]: "" });
  form.clearErrors();
  buka.value = true;
}
function openEdit(row) {
  Object.assign(form, kosong());
  semuaField.value.forEach((k) => { form[k] = row[k] ?? ""; });
  form[props.kunci] = row[props.kunci];
  form.clearErrors();
  buka.value = true;
}
function simpan() {
  form.post(`/kasir/${props.entitas}/save`, {
    preserveScroll: true,
    onSuccess: () => (buka.value = false),
  });
}
</script>

<template>
  <AdminLayout :title="label">
    <!-- Form cari di LUAR <Deferred> supaya langsung bisa diketik. -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <form class="flex flex-1 items-end gap-3" @submit.prevent="submitCari">
          <Input
            v-model="cari"
            label="Cari"
            :placeholder="`Kode atau nama ${label.toLowerCase()}…`"
            class="min-w-[16rem] flex-1"
          />
          <Button type="submit" variant="secondary">Cari</Button>
        </form>
        <Button @click="openCreate">Tambah {{ label }}</Button>
      </div>
    </Card>

    <Deferred data="data">
      <template #fallback>
        <LoadingCard :message="`Mengambil ${label.toLowerCase()}…`" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <Card>
        <DataTable :rows="rows" :columns="columns" :empty-message="`Belum ada ${label.toLowerCase()}.`">
          <template #cell-aksi="{ row }">
            <Button size="sm" variant="secondary" @click="openEdit(row)">Ubah</Button>
          </template>
        </DataTable>
        <p class="mt-2 text-xs text-ink-subtle">
          Menampilkan maksimal 200 baris. Pakai kotak cari untuk mempersempit.
        </p>
      </Card>
    </Deferred>

    <Modal
      :open="buka"
      :title="sedangEdit ? `Ubah ${label}` : `Tambah ${label}`"
      @close="buka = false"
    >
      <div class="grid gap-3 sm:grid-cols-2">
        <p v-if="sedangEdit" class="text-sm text-ink-subtle sm:col-span-2">
          Kode <strong>{{ form[kunci] }}</strong> — tidak bisa diubah, karena setiap
          nota yang menunjuk ke sini memakainya.
        </p>
        <Input
          v-for="k in teks"
          :key="k"
          v-model="form[k]"
          :label="labelKolom(k) + wajibkan(k)"
          :error="form.errors[k]"
          :class="k === 'alamat' || k.startsWith('npwp') ? 'sm:col-span-2' : ''"
        />
        <Select
          v-for="k in lookup_fields"
          :key="k"
          v-model="form[k]"
          :label="labelKolom(k) + wajibkan(k)"
          :options="lookups[k] || []"
          placeholder="Pilih…"
          :error="form.errors[k]"
        />
        <Input
          v-for="k in angka"
          :key="k"
          v-model="form[k]"
          type="number"
          :label="labelKolom(k)"
          :error="form.errors[k]"
        />
      </div>
      <template #footer>
        <Button variant="secondary" @click="buka = false">Batal</Button>
        <Button :loading="form.processing" @click="simpan">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
