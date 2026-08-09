<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";
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
import { useSatuan } from "@/composables/useSatuan";

// Grid ala aplikasi desktop: seluruh sel dijelajahi dengan panah + Enter, dan
// baris masuk lewat kotak pindai di bagian bawah tabel — bentuk yang sama
// dengan layar nota kasir, mesinnya pun sama (useGridNav).
//
// Yang diketik operator adalah STOK FISIK, bukan selisih. Itu yang benar-benar
// ia punya setelah menghitung rak; memaksanya menghitung selisih sendiri
// menambahkan satu langkah aritmetika yang tak perlu dan bisa salah. Kolom
// Selisih tetap bisa diketik langsung, karena untuk Rusak/Hilang ia tahu
// "3 rusak" tanpa menghitung ulang seluruh rak.
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
// tampil sebagai 10 kalau LUSIN (isi 12) dipilih. qty yang ditulis ke
// t_opname_stok memakai satuan pilihannya, dan trigger legacy yang mengalikan
// kembali (sp_update_stok_akhir → GetKuantitasSatuanTerkecil). Jadi operator
// tak pernah perlu mengonversi apa pun di kepalanya.
const satuan = useSatuan(URL);
const isiSatuan = (b) => {
  const s = satuan.opsi(b).find((x) => x.kd_satuan === b.kd_satuan);
  return s?.jumlah > 0 ? s.jumlah : 1;
};
const stokSistem = (b) => b.stok_dasar / isiSatuan(b);

function gantiSatuan(b, kd) {
  satuan.ganti(b, kd);
  // Stok fisik yang sudah diketik ikut dibaca ulang dalam satuan baru; kalau
  // dibiarkan, "10" yang tadinya berarti 10 PCS mendadak berarti 10 LUSIN dan
  // selisihnya melonjak 12 kali lipat tanpa satu pun tanda di layar.
  hitungDariFisik(b);
}

// --- Fisik ↔ selisih, dua arah --------------------------------------------
function hitungDariFisik(b) {
  if (b.fisik === "") { b.selisih = ""; return; }
  b.selisih = Number((angka(b.fisik) - stokSistem(b)).toFixed(3));
  ikutiTanda(b);
}
function hitungDariSelisih(b) {
  if (b.selisih === "") { b.fisik = ""; return; }
  b.fisik = Number((stokSistem(b) + angka(b.selisih)).toFixed(3));
  ikutiTanda(b);
}

// Arah TIDAK pernah jadi pilihan terpisah — ia melekat pada jenis (trigger:
// `IF @status <> 2 SET @jumlah = @jumlah * -1`). Jenis bawaan mengikuti tanda
// selisih; operator tinggal mengubahnya ke Rusak/Hilang bila itu sebabnya.
const menambah = (v) => props.jenis.find((j) => j.value === v)?.menambah;
function ikutiTanda(b) {
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
  return {
    kd_barang: b.kd_barang,
    nama: b.nama,
    // Satuan dasar sampai operator membuka dropdown-nya; saat itulah daftar
    // satuan diambil (satu round-trip per barang, hanya kalau memang dipakai).
    kd_satuan: b.kd_satuan || "",
    satuan: b.satuan || "",
    stok_dasar: Number(b.stok_akhir ?? 0),
    fisik: "",
    selisih: "",
    jenis: "lain_minus",
  };
}

function tambah(b) {
  const sudah = form.items.findIndex((x) => x.kd_barang === b.kd_barang);
  if (sudah >= 0) {
    // Barang yang sama dua kali berarti dua baris t_opname_stok yang saling
    // menimpa niat. Sorot yang sudah ada alih-alih menambah kembar.
    fokusBaris(sudah);
  } else {
    form.items.push(baru(b));
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
    rows.forEach((b) => { if (!ada.has(b.kd_barang)) form.items.push(baru(b)); });
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
      if (e.key === "ArrowUp") fokusBaris(form.items.length - 1);
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
  if (b) tambah(b);
  else pesan.value = `Barang "${q}" tak ditemukan.`;
}

function fokusBaris(i) {
  nextTick(() => {
    const rows = wadahTabel.value?.querySelectorAll("tbody tr[data-baris]");
    const kotak = rows?.[i]?.querySelector("[data-nav]");
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
      onSuccess: () => { form.reset(); entri.value = ""; hasil.value = []; },
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

      <Card class="mb-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <!-- Divisi WAJIB dipilih, tanpa nilai bawaan. Toko berisi satu divisi,
               tapi gudang berisi lima — dan di sana seluruh opname ada di
               PERGUDANGAN, bukan di UMUM yang kebetulan urutan pertama. Divisi
               juga menentukan awalan nomor koreksinya. -->
          <Select
            v-model="form.kd_divisi"
            label="Divisi *"
            placeholder="Pilih divisi…"
            :options="divisiOptions"
          />
          <Input
            v-model="form.keterangan"
            class="sm:col-span-2"
            label="Keterangan *"
            placeholder="sebab koreksi, mis. BALANCE STOK RETUR"
            maxlength="50"
          />
        </div>
        <p class="mt-2 text-xs text-ink-subtle">
          Keterangan maksimal 50 karakter dan berlaku untuk seluruh baris — ia
          satu-satunya tempat sebab koreksi tercatat, dan yang dibaca orang saat
          membalance selisih di Neraca Opname nanti.
        </p>
      </Card>

      <Card>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="text-sm text-ink-muted">
            <strong class="text-ink">{{ ringkas.baris }}</strong> baris berselisih
            <span v-if="ringkas.tambah" class="ml-2 text-success-fg">+{{ nf.format(ringkas.tambah) }}</span>
            <span v-if="ringkas.kurang" class="ml-2 text-danger-fg">−{{ nf.format(ringkas.kurang) }}</span>
            <span v-if="form.items.length > ringkas.baris" class="ml-2 text-ink-subtle">
              ({{ form.items.length - ringkas.baris }} baris tanpa selisih — tak akan dikirim)
            </span>
          </div>
          <Button :loading="form.processing" :disabled="!siap" @click="simpan">
            Simpan Koreksi
          </Button>
        </div>

        <p v-if="terpotong" class="mt-2 text-xs text-warning-fg">
          Hasil dipotong di {{ batas_muat }} baris. Persempit pencarian atau pilih
          divisi supaya tak ada barang yang diam-diam tertinggal.
        </p>

        <!-- Cari & isi DI DALAM tabel: baris terakhir kotak pindai/cari,
             hasilnya jadi baris di bawahnya, seluruh sel dijelajahi dengan
             panah + Enter (useGridNav). -->
        <div ref="wadahTabel" class="mt-4 overflow-x-auto" @keydown="navGrid">
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
                class="border-b border-border-default"
              >
                <td class="px-2 py-1">
                  <p class="text-ink">{{ b.nama }}</p>
                  <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                </td>
                <td class="px-2 py-1">
                  <select
                    data-nav
                    :value="b.kd_satuan"
                    :class="KELAS_PILIH"
                    @focus="satuan.muat(b)"
                    @change="gantiSatuan(b, $event.target.value)"
                  >
                    <option v-if="!satuan.opsi(b).length" :value="b.kd_satuan">
                      {{ b.satuan || b.kd_satuan }}
                    </option>
                    <option v-for="s in satuan.opsi(b)" :key="s.kd_satuan" :value="s.kd_satuan">
                      {{ satuan.label(s) }}
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
                    inputmode="decimal"
                    :class="KELAS_SEL"
                    @input="hitungDariFisik(b)"
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
                  />
                </td>
                <td class="px-2 py-1">
                  <select v-model="b.jenis" data-nav :class="KELAS_PILIH">
                    <option v-for="j in jenis" :key="j.value" :value="j.value">
                      {{ j.label }}
                    </option>
                  </select>
                </td>
                <td class="px-2 py-1 text-right">
                  <Button size="sm" variant="secondary" @click="hapus(i)">Hapus</Button>
                </td>
              </tr>

              <tr class="border-b-2 border-border-strong bg-surface-2/50">
                <td class="px-2 py-2" colspan="4">
                  <input
                    ref="kotakEntri"
                    v-model="entri"
                    class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono text-lg"
                    placeholder="Pindai / ketik kode atau nama barang…"
                    @keydown="entriKey"
                  />
                </td>
                <td class="px-2 py-2 text-right" colspan="3">
                  <Button
                    size="sm"
                    variant="secondary"
                    :loading="memuat"
                    :disabled="!entri.trim()"
                    @click="muatSekaligus"
                  >
                    Muat semua hasil
                  </Button>
                  <p class="mt-1 text-xs text-ink-subtle">
                    ↑↓ pilih · Enter masukkan · Ctrl+Del hapus baris
                  </p>
                </td>
              </tr>

              <tr
                v-for="(b, i) in hasil"
                :key="`cari-${b.kd_barang}`"
                :class="['cursor-pointer border-b border-border-default',
                         i === sorot ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                @click="tambah(b)"
              >
                <td class="px-2 py-1.5" colspan="2">
                  <p class="truncate text-ink">{{ b.nama }}</p>
                  <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                </td>
                <td class="px-2 py-1.5 text-right tabular-nums text-ink-subtle" colspan="5">
                  stok {{ nf.format(b.stok_akhir ?? 0) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="!baris.length" class="mt-3 text-sm text-ink-subtle">
          Belum ada baris. Pindai atau ketik barang di kotak di atas — daftar
          barang tidak dimuat seluruhnya karena ada puluhan ribu, dan grid dengan
          kotak isian di tiap baris tak akan sanggup menampungnya.
        </p>
      </Card>
    </Deferred>
  </AdminLayout>
</template>
