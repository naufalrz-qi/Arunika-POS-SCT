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

// Satu layar untuk SEMUA entitas master: Kelola Pelanggan, Kelola Supplier, dan
// kesebelas tabel referensi. Yang berbeda datang sebagai prop dari _MASTER di
// apps/master_data/master_crud.py — satu sumber kebenaran untuk kolom apa yang
// ada, bukan beberapa daftar yang pelan-pelan berbeda.
const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  entitas: { type: String, required: true },
  aksi_url: { type: String, required: true },
  label: { type: String, required: true },
  kunci: { type: String, required: true },
  teks: { type: Array, default: () => [] },
  angka: { type: Array, default: () => [] },
  lookup_fields: { type: Array, default: () => [] },
  wajib: { type: Array, default: () => [] },
  // Kolom tambahan di tabel daftar, di luar Kode + nama. Tanpa ini layar Merk
  // merender Alamat/Telepon/HP yang tabelnya memang tak punya.
  kolom_tabel: { type: Array, default: () => [] },
  // m_kas tak punya kolom `nama`; yang manusiawi di sana `cabang`.
  kolom_nama: { type: String, default: "nama" },
  // field → [{value,label}]. Dirender Select, dan opsi pertama jadi bawaan.
  pilihan: { type: Object, default: () => ({}) },
  // Daftar entitas untuk dropdown Kelola Data Referensi. Kosong = layar entitas
  // tunggal (Pelanggan/Supplier), dropdown-nya tidak dirender sama sekali.
  pemilih: { type: Array, default: () => [] },
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
  jenis: "Jenis", kd_telp: "Kode Area", kd_negara: "Negara",
  kd_index: "Kode Akun", no_rekening: "No. Rekening", cabang: "Nama / Cabang",
  saldo_awal: "Saldo Awal", nominal: "Nominal",
};
const labelKolom = (k) => LABEL[k] || k;

const columns = computed(() => [
  { key: props.kunci, label: "Kode", sortable: true },
  { key: props.kolom_nama, label: labelKolom(props.kolom_nama), sortable: true },
  ...props.kolom_tabel.map((k) => ({ key: k, label: labelKolom(k) })),
  // Status selalu ikut kalau entitasnya punya: menonaktifkan adalah satu-satunya
  // pembatalan yang ada di layar ini, jadi hasilnya harus terlihat di daftar.
  ...(props.pilihan.status ? [{ key: "status", label: "Status", sortable: true }] : []),
  { key: "aksi", label: "", align: "right" },
]);

function submitCari() {
  router.get(props.aksi_url, { cari: cari.value },
    { preserveState: true, preserveScroll: true });
}

function gantiEntitas(e) {
  // Rutenya berpindah halaman penuh, bukan preserveState: kolom, form, dan
  // lookup entitas berikutnya sama sekali berbeda dari yang sedang tampil.
  router.get(`/admin-panel/master/referensi/${e}`);
}

// Kolom berkunci-asing dirender sebagai pilihan, bukan isian bebas: database
// menolak nilai yang bukan kode nyata, jadi mengetiknya sendiri selalu gagal.
const lookups = computed(() => isi.value.lookups || {});
const semuaField = computed(() => [...props.teks, ...props.lookup_fields, ...props.angka]);
const wajibkan = (k) => (props.wajib.includes(k) ? " *" : "");

// Angka yang punya daftar pilihan (status) dirender Select, bukan kotak angka.
// "Nonaktifkan" adalah satu-satunya pembatalan yang ada — tak ada tombol hapus,
// karena DELETE di tabel-tabel ini merambat sampai menghapus barang.
const angkaBebas = computed(() => props.angka.filter((k) => !(k in props.pilihan)));
const fieldPilihan = computed(() => props.angka.filter((k) => k in props.pilihan));

// Baris baru mengikuti opsi PERTAMA tiap pilihan, bukan string kosong. Kosong
// dibaca server sebagai 0 = nonaktif, jadi bawaan yang salah di sini membuat
// setiap baris baru lahir dalam keadaan mati.
const kosong = () => Object.fromEntries(semuaField.value.map(
  (k) => [k, props.pilihan[k] ? props.pilihan[k][0].value : ""]));

const labelPilihan = (k, nilai) => {
  const opsi = (props.pilihan[k] || []).find((o) => String(o.value) === String(nilai));
  return opsi ? opsi.label : nilai;
};

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
  form.post(`${props.aksi_url}/save`, {
    preserveScroll: true,
    onSuccess: () => (buka.value = false),
  });
}
</script>

<template>
  <AdminLayout :title="label">
    <!-- Pemilih entitas & form cari di LUAR <Deferred> supaya langsung bisa dipakai. -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <Select
          v-if="pemilih.length"
          :model-value="entitas"
          label="Data"
          :options="pemilih"
          class="min-w-[12rem]"
          @update:model-value="gantiEntitas"
        />
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
          <template #cell-status="{ row }">
            {{ labelPilihan("status", row.status) }}
          </template>
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
      :show="buka"
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
          v-for="k in angkaBebas"
          :key="k"
          v-model="form[k]"
          type="number"
          :label="labelKolom(k)"
          :error="form.errors[k]"
        />
        <!-- Status: Select, bukan kotak angka. Tak ada tombol Hapus di layar ini
             dan itu disengaja — DELETE di tabel referensi merambat sampai
             menghapus barang, jadi "Nonaktif" adalah pembatalannya. -->
        <Select
          v-for="k in fieldPilihan"
          :key="k"
          v-model="form[k]"
          :label="labelKolom(k)"
          :options="pilihan[k]"
          :error="form.errors[k]"
        />
      </div>
      <p v-if="pilihan.status" class="mt-3 text-xs text-ink-subtle">
        Data yang tak dipakai lagi diset <strong>Nonaktif</strong>, tidak dihapus — baris
        lama yang menunjuk ke sini tetap utuh.
      </p>
      <template #footer>
        <Button variant="secondary" @click="buka = false">Batal</Button>
        <Button :loading="form.processing" @click="simpan">Simpan</Button>
      </template>
    </Modal>
  </AdminLayout>
</template>
