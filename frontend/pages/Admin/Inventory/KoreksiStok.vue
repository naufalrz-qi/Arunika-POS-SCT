<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { Deferred, useForm } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import { useGridNav } from "@/composables/useGridNav";

// Grid ala aplikasi desktop: seluruh sel dijelajahi dengan panah + Enter, dan
// baris baru masuk lewat kotak pindai. Mesin navigasinya useGridNav, sama
// dengan layar nota kasir.
//
// Dua keputusan tata letak yang dibayar dengan versi sebelumnya yang tak
// nyaman dipakai:
//
// 1. KOTAK PINDAI DI ATAS, dan baris baru disisipkan di ATAS pula. Di layar
//    nota kotak itu di bawah tabel dan itu benar — barisnya sedikit. Di sini
//    "Muat semua hasil" bisa menaruh 300 baris sekaligus, dan kotak yang di
//    bawah berarti menggulir 300 baris tiap kali ingin menambah satu barang,
//    dengan hasil pencarian muncul lebih jauh lagi di bawahnya.
// 2. SATUAN DATANG BERSAMA HASIL PENCARIAN (`satuan_list`), tidak diambil saat
//    dropdown-nya disentuh. `kd_satuan` wajib terisi sebelum baris bisa
//    disimpan, jadi mengambilnya belakangan membuat 300 baris mustahil
//    disimpan sampai 300 dropdown dibuka satu per satu. Karena itu layar ini
//    TIDAK memakai composable useSatuan — datanya sudah ada di baris.
const props = defineProps({
  awal: { type: Object, default: null },
  kd_user: { type: String, default: "" },
  jenis: { type: Array, default: () => [] },
  batas_muat: { type: Number, default: 300 },
});

const URL = "/admin-panel/inventory/koreksi-stok";
const data = computed(() => props.awal || {});
const divisiOptions = computed(() =>
  (data.value.divisi || []).map((d) => ({ value: d.kd_divisi, label: d.nama })),
);

// Sel angka bertipe text (lihat useGridNav soal kursor), jadi koma desimal
// benar-benar bisa terketik — dan Number("1,5") adalah NaN.
const angka = (v) => Number(String(v ?? "").replace(",", ".")) || 0;
const nf = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 });

const KELAS_SEL =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-right tabular-nums";
const KELAS_PILIH =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-sm";

const form = useForm({ kd_divisi: "", keterangan: "", items: [] });
const baris = computed(() => form.items);

// --- Konversi satuan -------------------------------------------------------
//
// Stok sistem dihitung dalam satuan DASAR. Operator boleh bekerja dalam satuan
// mana pun yang tersedia, jadi angkanya dibagi isi satuan itu: stok dasar 120
// tampil sebagai 10 kalau LUSIN (isi 12) dipilih. qty yang ditulis memakai
// satuan pilihannya, dan trigger legacy yang mengalikan kembali
// (sp_update_stok_akhir → GetKuantitasSatuanTerkecil).
const isiSatuan = (b) => {
  const s = b.satuan_list.find((x) => x.kd_satuan === b.kd_satuan);
  return s?.jumlah > 0 ? s.jumlah : 1;
};
const stokSistem = (b) => b.stok_dasar / isiSatuan(b);
const labelSatuan = (s) =>
  `${s.satuan || s.kd_satuan}${s.jumlah > 1 ? ` (isi ${s.jumlah})` : ""}`;

function gantiSatuan(b, kd) {
  b.kd_satuan = kd;
  // Stok fisik yang sudah diketik dibaca ulang dalam satuan baru; kalau
  // dibiarkan, "10" yang tadinya berarti 10 PCS mendadak berarti 10 LUSIN dan
  // selisihnya melonjak 12 kali lipat tanpa satu pun tanda di layar.
  hitungDariFisik(b);
}

// --- Fisik ↔ selisih, dua arah --------------------------------------------
function hitungDariFisik(b) {
  if (String(b.fisik).trim() === "") { b.selisih = ""; return; }
  b.selisih = Number((angka(b.fisik) - stokSistem(b)).toFixed(3));
}
function hitungDariSelisih(b) {
  if (String(b.selisih).trim() === "") { b.fisik = ""; return; }
  b.fisik = Number((stokSistem(b) + angka(b.selisih)).toFixed(3));
}

// Arah TIDAK pernah jadi pilihan terpisah — ia melekat pada jenis (trigger:
// `IF @status <> 2 SET @jumlah = @jumlah * -1`). Jenis bawaan mengikuti tanda
// selisih, tapi hanya SETELAH selesai mengetik (@change, bukan @input): kalau
// tiap ketukan tombol ikut mengubahnya, kotak jenis berkedip-kedip sepanjang
// operator mengetik angka. Ia juga berhenti ikut begitu operator memilih
// sendiri — pilihan Rusak/Hilang tak boleh ditimpa oleh tanda selisih.
const menambah = (v) => props.jenis.find((j) => j.value === v)?.menambah;
function ikutiTanda(b) {
  if (b.jenis_manual) return;
  const positif = angka(b.selisih) > 0;
  if (menambah(b.jenis) !== positif) b.jenis = positif ? "lain_plus" : "lain_minus";
}

// --- Kotak pindai ----------------------------------------------------------
const entri = ref("");
const hasil = ref([]);
const sorot = ref(0);
const digeser = ref(false);
const pesan = ref("");
const terpotong = ref(false);
const memuat = ref(false);
const kotakEntri = ref(null);
const wadahTabel = ref(null);
const fokusEntri = () => nextTick(() => kotakEntri.value?.focus?.());

async function cari(q, limit) {
  const { data: d } = await axios.get(`${URL}/cari`, {
    params: { cari: q, kd_divisi: form.kd_divisi || undefined, limit },
  });
  pesan.value = d.error || "";
  terpotong.value = Boolean(d.terpotong);
  return d.rows || [];
}

let timer = null;
watch(entri, (q) => {
  clearTimeout(timer);
  sorot.value = 0;
  digeser.value = false;
  if (!q.trim()) { hasil.value = []; return; }
  timer = setTimeout(async () => { hasil.value = await cari(q, 20); }, 250);
});

function baru(b) {
  const daftar = b.satuan_list || [];
  return {
    kd_barang: b.kd_barang,
    nama: b.nama,
    satuan_list: daftar,
    // Satuan terkecil sebagai bawaan — itu satuan tempat stok dihitung, jadi
    // baris langsung bisa disimpan tanpa menyentuh dropdown sama sekali.
    kd_satuan: daftar[0]?.kd_satuan || "",
    stok_dasar: Number(b.stok_akhir ?? 0),
    fisik: "",
    selisih: "",
    jenis: "lain_minus",
    jenis_manual: false,
  };
}

function tambah(b) {
  const sudah = form.items.findIndex((x) => x.kd_barang === b.kd_barang);
  if (sudah >= 0) {
    // Barang yang sama dua kali berarti dua baris t_opname_stok yang saling
    // menimpa niat. Sorot yang sudah ada alih-alih menambah kembar.
    fokusBaris(sudah);
  } else {
    // Di ATAS: baris yang baru dimasukkan itulah yang sedang dikerjakan, jadi
    // ia harus ada di dekat kotak pindai, bukan di ujung daftar 300 baris.
    form.items.unshift(baru(b));
  }
  entri.value = "";
  hasil.value = [];
}

async function muatSekaligus() {
  const q = entri.value.trim();
  if (!q) return;
  memuat.value = true;
  try {
    const rows = await cari(q, props.batas_muat);
    const ada = new Set(form.items.map((x) => x.kd_barang));
    // Urutan hasil dipertahankan (unshift terbalik akan mengacaknya).
    form.items.unshift(...rows.filter((b) => !ada.has(b.kd_barang)).map(baru));
    entri.value = "";
    hasil.value = [];
  } finally {
    memuat.value = false;
  }
}

function entriKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!hasil.value.length) {
      if (e.key === "ArrowDown") fokusBaris(0);
      return;
    }
    digeser.value = true;
    const n = hasil.value.length;
    sorot.value = (sorot.value + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    return;
  }
  if (e.key !== "Enter") return;
  e.preventDefault();
  const q = entri.value.trim();
  if (!q) return;
  // Urutannya menjaga pemindai: ia mengetik lalu Enter dalam sekejap, sering
  // SEBELUM hasil pencarian datang. Kode persis menang atas hasil teratas.
  const sama = (b) => (b.kd_barang || "").toUpperCase() === q.toUpperCase();
  const b = (digeser.value && hasil.value[sorot.value])
    || hasil.value.find(sama)
    || hasil.value[0];
  if (b) {
    tambah(b);
    // Langsung ke kotak Stok Fisik baris itu: satu-satunya alasan barang
    // dimasukkan adalah untuk mengisi angkanya.
    fokusBaris(0);
  } else {
    pesan.value = `Barang "${q}" tak ditemukan.`;
  }
}

function fokusBaris(i) {
  nextTick(() => {
    const rows = wadahTabel.value?.querySelectorAll("tbody tr[data-baris]");
    // [data-nav] pertama adalah kotak Stok Fisik; dropdown satuan sengaja
    // dilewati karena bawaannya sudah benar untuk hampir semua baris.
    const kotak = rows?.[i]?.querySelector("[data-nav-fisik]");
    kotak?.focus();
    kotak?.select?.();
  });
}

const hapus = (i) => form.items.splice(i, 1);
const navGrid = useGridNav(wadahTabel, { keEntri: fokusEntri, hapusBaris: hapus });

// --- Ringkasan & kirim -----------------------------------------------------
const terisi = computed(() => form.items.filter((b) => angka(b.selisih) !== 0));
const ringkas = computed(() => {
  let tambah = 0, kurang = 0;
  terisi.value.forEach((b) => {
    const v = angka(b.selisih);
    if (v > 0) tambah += v; else kurang -= v;
  });
  return { tambah, kurang, baris: terisi.value.length };
});

// Divisi dikunci begitu ada baris: ia menentukan angka stok yang sudah tampil,
// jadi menggantinya di tengah jalan membuat seluruh selisih yang sudah diketik
// salah tanpa satu pun tanda di layar.
const divisiTerkunci = computed(() => form.items.length > 0);

const siap = computed(
  () => Boolean(props.kd_user) && Boolean(form.kd_divisi)
    && terisi.value.length > 0 && form.keterangan.trim().length > 0,
);

function simpan() {
  // Baris berselisih nol tidak dikirim: ia menghasilkan koreksi qty 0 yang
  // menambah nomor dan baris di laporan tanpa menggeser apa pun.
  form
    .transform((d) => ({
      kd_divisi: d.kd_divisi,
      keterangan: d.keterangan,
      items: terisi.value.map((b) => ({
        kd_barang: b.kd_barang,
        kd_satuan: b.kd_satuan,
        // qty selalu positif — tandanya ada di `jenis`, dan trigger yang
        // membalik. Mengirim angka negatif berarti stok bergerak dua kali
        // ke arah yang sama.
        qty: Math.abs(angka(b.selisih)),
        jenis: b.jenis,
      })),
    }))
    .post(`${URL}/save`, {
      preserveScroll: true,
      // Hanya barisnya yang dibersihkan. Divisi dan keterangan BERTAHAN: satu
      // sesi balancing disimpan bertahap, dan mengetik ulang keduanya tiap
      // batch adalah pekerjaan yang tak menghasilkan apa-apa.
      onSuccess: () => {
        form.items = [];
        entri.value = "";
        hasil.value = [];
        fokusEntri();
      },
    });
}
</script>

<template>
  <AdminLayout title="Koreksi Stok">
    <Banner
      v-if="!kd_user"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi koreksi belum bisa disimpan. Minta pengelola aplikasi mengisinya di Kelola Tautan User."
    />
    <Banner v-if="pesan" variant="warning" :message="pesan" class="mb-4" />

    <Deferred data="awal">
      <template #fallback><LoadingCard message="Menyiapkan layar koreksi…" /></template>

      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" class="mb-4" />

      <Card>
        <!-- Satu baris alat kerja: divisi, keterangan, kotak pindai, tombol
             simpan. Semuanya di ATAS, sebelum tabel — dengan 300 baris di
             bawahnya, apa pun yang ada di bawah tabel praktis tak terjangkau. -->
        <div class="grid gap-3 sm:grid-cols-12">
          <div class="sm:col-span-3">
            <Select
              v-model="form.kd_divisi"
              label="Divisi *"
              placeholder="Pilih divisi…"
              :options="divisiOptions"
              :disabled="divisiTerkunci"
            />
          </div>
          <Input
            v-model="form.keterangan"
            class="sm:col-span-5"
            label="Keterangan *"
            placeholder="sebab koreksi, mis. BALANCE STOK RETUR"
            maxlength="50"
          />
          <div class="flex items-end sm:col-span-4">
            <Button class="w-full" :loading="form.processing" :disabled="!siap" @click="simpan">
              Simpan {{ ringkas.baris || "" }} Koreksi
            </Button>
          </div>
        </div>
        <p v-if="divisiTerkunci" class="mt-1 text-xs text-ink-subtle">
          Divisi terkunci selama masih ada baris — ia menentukan angka stok yang
          sudah tampil. Kosongkan barisnya untuk berganti divisi.
        </p>

        <div class="mt-4">
          <label class="mb-1 block text-xs font-medium text-ink-muted">
            Pindai / cari barang
          </label>
          <div class="flex gap-2">
            <input
              ref="kotakEntri"
              v-model="entri"
              :disabled="!form.kd_divisi"
              class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg disabled:opacity-50"
              :placeholder="form.kd_divisi ? 'Pindai / ketik kode atau nama barang…' : 'Pilih divisi dulu…'"
              @keydown="entriKey"
            />
            <Button
              variant="secondary"
              :loading="memuat"
              :disabled="!entri.trim()"
              @click="muatSekaligus"
            >
              Muat semua hasil
            </Button>
          </div>
          <p class="mt-1 text-xs text-ink-subtle">
            ↑↓ pilih hasil · Enter masukkan &amp; langsung isi · Ctrl+Del hapus baris
          </p>

          <!-- Hasil pencarian tepat di bawah kotaknya, bukan di bawah tabel. -->
          <ul v-if="hasil.length" class="mt-2 max-h-56 overflow-y-auto rounded-control border border-border-default">
            <li
              v-for="(b, i) in hasil"
              :key="b.kd_barang"
              :class="['flex cursor-pointer items-baseline gap-3 px-3 py-1.5 text-sm',
                       i === sorot ? 'bg-brand-bg' : 'hover:bg-surface-2']"
              @click="tambah(b)"
            >
              <span class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</span>
              <span class="flex-1 truncate text-ink">{{ b.nama }}</span>
              <span class="tabular-nums text-xs text-ink-subtle">
                stok {{ nf.format(b.stok_akhir ?? 0) }}
              </span>
            </li>
          </ul>
          <p v-if="terpotong" class="mt-2 text-xs text-warning-fg">
            Hasil dipotong di {{ batas_muat }} baris. Persempit pencarian supaya tak
            ada barang yang diam-diam tertinggal.
          </p>
        </div>
      </Card>

      <Card class="mt-4">
        <div class="mb-2 text-sm text-ink-muted">
          <strong class="text-ink">{{ ringkas.baris }}</strong> dari
          {{ baris.length }} baris berselisih
          <span v-if="ringkas.tambah" class="ml-2 text-success-fg">+{{ nf.format(ringkas.tambah) }}</span>
          <span v-if="ringkas.kurang" class="ml-2 text-danger-fg">−{{ nf.format(ringkas.kurang) }}</span>
        </div>

        <div ref="wadahTabel" class="overflow-x-auto" @keydown="navGrid">
          <table class="w-full text-sm">
            <thead class="text-xs text-ink-subtle">
              <tr class="border-b border-border-default">
                <th class="px-2 py-1 text-left font-medium">Barang</th>
                <th class="w-36 px-2 py-1 text-left font-medium">Satuan</th>
                <th class="w-28 px-2 py-1 text-right font-medium">Stok Sistem</th>
                <th class="w-28 px-2 py-1 text-right font-medium">Stok Fisik</th>
                <th class="w-28 px-2 py-1 text-right font-medium">Selisih</th>
                <th class="w-40 px-2 py-1 text-left font-medium">Jenis</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(b, i) in baris"
                :key="b.kd_barang"
                data-baris
                :class="['border-b border-border-default',
                         angka(b.selisih) !== 0 ? '' : 'text-ink-muted']"
              >
                <td class="px-2 py-1">
                  <p class="text-ink">{{ b.nama }}</p>
                  <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                </td>
                <td class="px-2 py-1">
                  <!-- Terisi sejak baris dibuat: daftarnya ikut hasil pencarian,
                       bukan diambil saat dropdown disentuh. -->
                  <select
                    data-nav
                    :value="b.kd_satuan"
                    :class="KELAS_PILIH"
                    @change="gantiSatuan(b, $event.target.value)"
                  >
                    <option v-for="s in b.satuan_list" :key="s.kd_satuan" :value="s.kd_satuan">
                      {{ labelSatuan(s) }}
                    </option>
                  </select>
                </td>
                <td class="px-2 py-1 text-right tabular-nums text-ink-muted">
                  {{ nf.format(stokSistem(b)) }}
                </td>
                <td class="px-2 py-1">
                  <input
                    v-model="b.fisik"
                    data-nav
                    data-nav-fisik
                    inputmode="decimal"
                    :class="KELAS_SEL"
                    @input="hitungDariFisik(b)"
                    @change="ikutiTanda(b)"
                  />
                </td>
                <td class="px-2 py-1">
                  <input
                    v-model="b.selisih"
                    data-nav
                    inputmode="decimal"
                    :class="[KELAS_SEL, angka(b.selisih) > 0 ? 'text-success-fg'
                             : angka(b.selisih) < 0 ? 'text-danger-fg' : '']"
                    @input="hitungDariSelisih(b)"
                    @change="ikutiTanda(b)"
                  />
                </td>
                <td class="px-2 py-1">
                  <select
                    v-model="b.jenis"
                    data-nav
                    :class="KELAS_PILIH"
                    @change="b.jenis_manual = true"
                  >
                    <option v-for="j in jenis" :key="j.value" :value="j.value">
                      {{ j.label }}
                    </option>
                  </select>
                </td>
                <td class="px-2 py-1 text-right">
                  <Button size="sm" variant="ghost" @click="hapus(i)">Hapus</Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="!baris.length" class="py-6 text-center text-sm text-ink-subtle">
          Belum ada baris. Pindai atau ketik barang di kotak di atas — daftar
          barang tidak dimuat seluruhnya karena ada puluhan ribu, dan grid
          dengan kotak isian di tiap baris tak akan sanggup menampungnya.
        </p>
      </Card>
    </Deferred>
  </AdminLayout>
</template>
