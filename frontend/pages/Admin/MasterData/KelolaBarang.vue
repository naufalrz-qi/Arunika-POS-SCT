<script setup>
import { computed, ref } from "vue";
import axios from "axios";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import DataTable from "@/components/ui/DataTable.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

// Kelola STRUKTUR barang: buat baru, dan sunting yang sudah ada — tambah satuan,
// tambah baris divisi, ubah konversi dan stok minimum. HARGA bukan urusan layar
// ini; ia punya jalurnya sendiri di Update Harga (services.update_harga), yang
// memvalidasi harga bulat, menghitung margin, dan menyebarkannya ke toko.
const props = defineProps({
  data: { type: Object, default: null },
  // Sama seperti di Update Harga: pertanyaannya memang sama — apakah server ini
  // boleh menyentuh identitas katalog yang dipakai bersama semua cabang.
  boleh_edit_identitas: { type: Boolean, default: false },
  nama_koneksi: { type: String, default: null },
});

const BASE = "/admin-panel/master/kelola-barang";

const isi = computed(() => props.data || {});
const opsi = computed(() => isi.value.opsi || {});
const terakhir = computed(() => isi.value.terakhir || []);

const LOOKUP = [
  { name: "kd_kategori", label: "Kategori" },
  { name: "kd_merk", label: "Merk" },
  { name: "kd_model", label: "Model" },
  { name: "kd_warna", label: "Warna" },
  { name: "kd_jenis_bahan", label: "Jenis Bahan" },
];
const STATUS = [
  { value: 1, label: "Aktif" },
  { value: 0, label: "Nonaktif" },
];

const kolomTerakhir = [
  { key: "kd_barang", label: "Kode", sortable: true },
  { key: "nama", label: "Nama", sortable: true },
  { key: "keterangan", label: "Keterangan" },
  { key: "tanggal_daftar", label: "Didaftarkan", sortable: true },
];

// `ada: true` menandai baris yang SUDAH tersimpan di server. Bedanya nyata:
// harga baris lama hanya dibaca di sini, dan kd_satuan/kd_divisi-nya terkunci —
// mengubah kunci merambat lewat ON UPDATE CASCADE ke belasan tabel transaksi.
const barisSatuan = () => ({ kd_satuan: "", jumlah: "1", harga_jual: "", status: 1, ada: false });
const barisDivisi = () => ({
  kd_divisi: "", stok_awal: "0", harga_beli_awal: "0", stok_min: "0", status: 1, ada: false,
});

const kosong = () => ({
  kd_barang_asal: "",
  kd_barang: "", nama: "", keterangan: "", ukuran: "1",
  kd_kategori: "", kd_merk: "", kd_model: "", kd_warna: "", kd_jenis_bahan: "",
  satuan: [barisSatuan()],
  divisi: [],
});

const form = useForm(kosong());
const tab = ref("identitas");
const menyunting = computed(() => Boolean(form.kd_barang_asal));

const TABS = computed(() => [
  { id: "identitas", label: "Identitas", jumlah: null },
  { id: "satuan", label: "Satuan", jumlah: form.satuan.length },
  { id: "divisi", label: "Divisi", jumlah: form.divisi.length },
]);

// --- Pemilih barang -------------------------------------------------------
// Cari lewat tombol/Enter, bukan tiap ketikan: m_barang 53.865 baris dan
// polanya LIKE '%…%', jadi menembaknya per huruf berarti puluhan pemindaian
// tabel penuh untuk satu kali mencari.
const cari = ref("");
const hasil = ref([]);
const sedangCari = ref(false);
const galat = ref("");

async function cariBarang() {
  const q = cari.value.trim();
  if (!q) return;
  sedangCari.value = true;
  galat.value = "";
  try {
    const { data } = await axios.get(`${BASE}/cari`, { params: { q } });
    hasil.value = data.rows || [];
    galat.value = data.error || (hasil.value.length ? "" : `Tidak ada barang cocok "${q}".`);
  } catch {
    galat.value = "Gagal mencari barang.";
  } finally {
    sedangCari.value = false;
  }
}

async function muatBarang(kd) {
  galat.value = "";
  try {
    const { data } = await axios.get(`${BASE}/muat`, { params: { kd_barang: kd } });
    if (!data.item) {
      galat.value = data.error || "Barang tidak ditemukan.";
      return;
    }
    const it = data.item;
    Object.assign(form, kosong(), {
      kd_barang_asal: it.kd_barang,
      kd_barang: it.kd_barang,
      nama: it.nama || "",
      keterangan: it.keterangan === "-" ? "" : it.keterangan || "",
      ukuran: String(it.ukuran ?? 1),
      ...Object.fromEntries(LOOKUP.map((l) => [l.name, it[l.name] || ""])),
    });
    form.satuan = (it.satuan || []).map((s) => ({
      kd_satuan: s.kd_satuan,
      jumlah: String(s.jumlah ?? 1),
      harga_jual: s.harga_jual,
      status: Number(s.status),
      ada: true,
    }));
    if (!form.satuan.length) form.satuan = [barisSatuan()];
    form.divisi = (it.divisi || []).map((d) => ({
      kd_divisi: d.kd_divisi,
      stok_awal: String(d.stok_awal ?? 0),
      harga_beli_awal: String(d.harga_beli_awal ?? 0),
      stok_min: String(d.stok_min ?? 0),
      status: Number(d.status),
      ada: true,
    }));
    hasil.value = [];
    cari.value = "";
    tab.value = "identitas";
  } catch {
    galat.value = "Gagal memuat barang.";
  }
}

function barangBaru() {
  Object.assign(form, kosong());
  form.satuan = [barisSatuan()];
  form.divisi = [];
  form.clearErrors();
  hasil.value = [];
  galat.value = "";
  tab.value = "identitas";
}

const rupiah = (v) =>
  new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 })
    .format(Number(v) || 0);

function simpan() {
  form.post(`${BASE}/save`, {
    preserveScroll: true,
    onSuccess: () => {
      barangBaru();
      // Muat ulang supaya daftar "barang terbaru didaftarkan" memuat yang baru.
      router.reload({ only: ["data"] });
    },
  });
}
</script>

<template>
  <AdminLayout title="Kelola Barang">
    <Banner
      v-if="!boleh_edit_identitas"
      variant="warning"
      class="mb-4"
      :message="`Koneksi aktif (${nama_koneksi || '—'}) bukan server gudang. Struktur barang hanya diatur di gudang lalu menyebar sendiri ke seluruh toko — yang dibuat atau diubah di sini akan tertimpa sapuan berikutnya.`"
    />

    <!-- Pemilih barang di LUAR tab: tab dipakai untuk bagian data, bukan untuk
         berpindah antara "barang baru" dan "barang lama". -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-end gap-3">
        <form class="flex flex-1 items-end gap-3" @submit.prevent="cariBarang">
          <Input
            v-model="cari"
            label="Cari barang yang sudah ada"
            placeholder="Kode atau nama barang…"
            class="min-w-[16rem] flex-1"
          />
          <Button type="submit" variant="secondary" :loading="sedangCari">Cari</Button>
        </form>
        <Button variant="secondary" @click="barangBaru">Barang Baru</Button>
      </div>

      <Banner v-if="galat" variant="warning" :message="galat" class="mt-3" />

      <div v-if="hasil.length" class="mt-3 max-h-56 overflow-y-auto rounded-control border border-border-strong">
        <button
          v-for="b in hasil"
          :key="b.kd_barang"
          type="button"
          class="block w-full px-3 py-2 text-left text-sm text-ink hover:bg-surface-3"
          @click="muatBarang(b.kd_barang)"
        >
          <span class="font-mono text-xs text-ink-muted">{{ b.kd_barang }}</span>
          — {{ b.nama }}
          <span v-if="Number(b.status) === 0" class="ml-1 text-xs text-danger-fg">(nonaktif)</span>
        </button>
      </div>

      <p v-if="menyunting" class="mt-3 text-sm text-ink-muted">
        Sedang menyunting <strong class="font-mono">{{ form.kd_barang_asal }}</strong>.
        Tekan <em>Barang Baru</em> untuk mengosongkan formulir.
      </p>
    </Card>

    <!-- Tab: v-show, bukan v-if — isian tab yang tak terlihat harus tetap ada.
         Satuan wajib minimal satu, jadi menghapus isian orang saat ia mengecek
         tab Identitas tak bisa diterima. -->
    <div class="mb-4 flex gap-1 border-b border-border-default">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        :class="[
          '-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors',
          tab === t.id
            ? 'border-brand-500 text-ink'
            : 'border-transparent text-ink-muted hover:text-ink',
        ]"
        @click="tab = t.id"
      >
        {{ t.label }}
        <span
          v-if="t.jumlah !== null"
          class="ml-1 rounded-full bg-surface-3 px-1.5 text-[10px] font-semibold text-ink-muted"
        >{{ t.jumlah }}</span>
      </button>
    </div>

    <!-- Tab 1: Identitas -->
    <Card v-show="tab === 'identitas'" class="mb-4">
      <div class="grid gap-3 sm:grid-cols-2">
        <Input
          v-model="form.kd_barang"
          label="Kode Barang *"
          placeholder="mis. OCT6555 atau barcode pabrik"
          maxlength="30"
          :disabled="menyunting"
        />
        <Input v-model="form.nama" label="Nama Barang *" maxlength="50" />
        <Select
          v-for="l in LOOKUP"
          :key="l.name"
          v-model="form[l.name]"
          :label="l.label + ' *'"
          :options="opsi[l.name] || []"
          placeholder="Pilih…"
        />
        <Input v-model="form.ukuran" label="Ukuran" placeholder="mis. 1" />
        <Input
          v-model="form.keterangan"
          label="Keterangan"
          maxlength="50"
          class="sm:col-span-2"
        />
      </div>
      <p class="mt-3 text-xs text-ink-subtle">
        Kode barang <strong>tidak bisa diubah</strong> setelah tersimpan — setiap nota,
        stok, dan mutasi yang menunjuk ke sini memakainya. Salah kode berarti membuat
        barang baru dan menonaktifkan yang lama.
      </p>
    </Card>

    <!-- Tab 2: Satuan -->
    <Card v-show="tab === 'satuan'" class="mb-4">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold text-ink">Satuan</h2>
        <Button size="sm" variant="secondary" @click="form.satuan.push(barisSatuan())">
          Tambah satuan
        </Button>
      </div>
      <div v-for="(s, i) in form.satuan" :key="i" class="mb-3 grid gap-3 sm:grid-cols-5">
        <Select
          v-model="s.kd_satuan"
          label="Satuan *"
          :options="opsi.kd_satuan || []"
          placeholder="Pilih…"
          :disabled="s.ada"
        />
        <Input v-model="s.jumlah" label="Isi" placeholder="1" />
        <!-- Harga baris LAMA hanya dibaca. Menulisnya dari sini melewati
             services.update_harga — validasi harga bulat, hitung ulang margin,
             batalkan cache, catat riwayat, sebar ke 8 toko. Kelimanya hilang
             tanpa gejala apa pun di layar. -->
        <div v-if="s.ada">
          <span class="mb-1 block text-xs font-medium text-ink-muted">Harga Jual</span>
          <div class="flex h-9 items-center text-sm tabular-nums text-ink-muted">
            {{ rupiah(s.harga_jual) }}
          </div>
        </div>
        <Input v-else v-model="s.harga_jual" label="Harga Jual" placeholder="0" />
        <Select v-model="s.status" label="Status" :options="STATUS" />
        <div class="flex items-end">
          <Button
            v-if="!s.ada && form.satuan.length > 1"
            size="sm"
            variant="secondary"
            @click="form.satuan.splice(i, 1)"
          >
            Hapus baris
          </Button>
        </div>
      </div>
      <p class="text-xs text-ink-subtle">
        Isi = berapa satuan dasar per satu satuan ini (PCS biasanya 1, LUSIN 12).
        <strong>Harga satuan yang sudah tersimpan diubah di menu Update Harga</strong>,
        bukan di sini — di sana margin ikut dihitung ulang dan harganya disebar ke
        seluruh toko. Satuan yang tak dipakai lagi diset Nonaktif, tidak dihapus.
      </p>
    </Card>

    <!-- Tab 3: Divisi -->
    <Card v-show="tab === 'divisi'" class="mb-4">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-semibold text-ink">Divisi</h2>
        <Button size="sm" variant="secondary" @click="form.divisi.push(barisDivisi())">
          Tambah divisi
        </Button>
      </div>
      <div v-for="(d, i) in form.divisi" :key="i" class="mb-3 grid gap-3 sm:grid-cols-6">
        <Select
          v-model="d.kd_divisi"
          label="Divisi"
          :options="opsi.kd_divisi || []"
          placeholder="Pilih…"
          :disabled="d.ada"
        />
        <Input v-model="d.stok_awal" label="Stok Awal" />
        <Input v-model="d.harga_beli_awal" label="Harga Beli Awal" />
        <Input v-model="d.stok_min" label="Stok Min" />
        <Select v-model="d.status" label="Status" :options="STATUS" />
        <div class="flex items-end">
          <Button
            v-if="!d.ada"
            size="sm"
            variant="secondary"
            @click="form.divisi.splice(i, 1)"
          >
            Hapus baris
          </Button>
        </div>
      </div>
      <Banner
        v-if="form.divisi.some((d) => d.ada)"
        variant="warning"
        class="mb-3"
        message="Mengubah Stok Awal mengubah angka stok yang dilaporkan, bukan cuma catatan: mesin stok memakainya sebagai jangkar, dan periode yang dimulai sebelum tutup buku terakhir mengembalikan stok awal apa adanya."
      />
      <p class="text-xs text-ink-subtle">
        Boleh dikosongkan — baris divisi hanya perlu kalau barang ini punya stok awal
        atau batas stok minimum. Isinya milik server ini sendiri dan tidak ikut
        disebarkan ke toko.
      </p>
    </Card>

    <div class="mb-4 flex justify-end">
      <Button :disabled="!boleh_edit_identitas" :loading="form.processing" @click="simpan">
        {{ menyunting ? "Simpan Perubahan" : "Simpan Barang Baru" }}
      </Button>
    </div>

    <Deferred data="data">
      <template #fallback>
        <LoadingCard message="Mengambil pilihan kategori, merk, dan satuan…" />
      </template>

      <Banner v-if="isi.conn_error" variant="warning" :message="isi.conn_error" class="mb-4" />

      <Card>
        <h2 class="mb-3 text-sm font-semibold text-ink">Barang terbaru didaftarkan</h2>
        <DataTable
          :rows="terakhir"
          :columns="kolomTerakhir"
          empty-message="Belum ada barang berdata tanggal daftar di server ini."
        />
      </Card>
    </Deferred>
  </AdminLayout>
</template>
