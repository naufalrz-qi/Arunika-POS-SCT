<script setup>
// Edit nota penjualan yang SUDAH tersimpan. Jalur tulisnya meniru aplikasi POS
// lama persis (apps/transactions/edit_nota.py): kepala di-UPDATE, baris barang
// diganti seluruhnya. Layar ini hanya menyusun isi baru + alasan; server yang
// menghitung ulang total, memeriksa penghalang, dan menolak kalau nota berubah
// sejak dibuka (`versi`).
//
// Yang sengaja TIDAK bisa diubah di sini: tanggal (nomor nota menyimpan
// tanggalnya; legacy yang memindah tanggal menomori ulang nota), divisi, dan
// status. Semuanya tampil sebagai teks, bukan isian yang dikunci, supaya tak
// ada yang mengira kotaknya sekadar macet.
import { computed, nextTick, ref, watch } from "vue";
import { Deferred, router, useForm } from "@inertiajs/vue3";
import axios from "axios";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import Banner from "@/components/ui/Banner.vue";
import Modal from "@/components/ui/Modal.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";
import SelisihNota from "@/components/audit/SelisihNota.vue";
import RiwayatNota from "@/components/audit/RiwayatNota.vue";
import { useGridNav } from "@/composables/useGridNav";
import { useSatuan } from "@/composables/useSatuan";
import { tanggalJam } from "@/utils/tanggal";

const props = defineProps({
  data: { type: Object, default: null },
  filters: { type: Object, default: () => ({}) },
  base: { type: String, default: "/admin-panel/penjualan/edit-nota" },
  kd_user: { type: String, default: "" },
  kd_pegawai: { type: String, default: "" },
  min_alasan: { type: Number, default: 10 },
});

const d = computed(() => props.data || {});
const nota = computed(() => d.value.nota || null);
const opsi = computed(() => d.value.opsi || {});
const terhalang = computed(() => (nota.value?.penghalang || []).length > 0);

// Sel angka bertipe text (lihat useGridNav), jadi koma desimal bisa terketik.
const angka = (v) => Number(String(v ?? "").replace(",", ".")) || 0;
const uang = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 });
const rupiah = (v) => `Rp ${uang.format(angka(v))}`;
const KELAS_SEL =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-right tabular-nums";
const KELAS_PILIH =
  "w-full rounded-control border border-border-default bg-surface px-2 py-1 text-sm";

// --- Cari nota ---------------------------------------------------------------
const cariNo = ref(props.filters.no || "");
function buka() {
  const no = cariNo.value.trim();
  if (!no) return;
  router.get(props.base, { no }, { preserveScroll: false });
}

// --- Isi yang sedang diedit -----------------------------------------------
const KEPALA = ["kd_customer", "kd_jenis", "kd_kas", "kd_voucher", "no_bukti", "keterangan",
  "tanggal_jatuh_tempo", "diskon_uang", "pajak"];

const form = useForm({ kepala: {}, customer_nama: "", items: [], alasan: "" });

function isiDariNota(n) {
  if (!n) return;
  const k = n.kepala;
  form.kepala = Object.fromEntries(KEPALA.map((c) => [c, c === "tanggal_jatuh_tempo"
    ? String(k[c] || "").slice(0, 10) : k[c]]));
  form.customer_nama = k.customer_nama || "";
  form.items = n.baris.map((b) => ({ ...b }));
  form.alasan = "";
}
// Prop deferred datang SESUDAH cat pertama; isi formulirnya saat ia tiba, dan
// isi ulang setiap kali nota yang dimuat berganti (mis. sesudah simpan, versi
// baru datang dari server).
watch(() => nota.value?.versi, () => isiDariNota(nota.value), { immediate: true });

// --- Pelanggan ------------------------------------------------------------
const cariCustomer = ref("");
const hasilCustomer = ref([]);
const sorotCust = ref(0);
let timerCust = null;
watch(cariCustomer, (q) => {
  clearTimeout(timerCust);
  sorotCust.value = 0;
  if (q.trim().length < 2) { hasilCustomer.value = []; return; }
  timerCust = setTimeout(async () => {
    const { data } = await axios.get(`${props.base}/cari-customer`, { params: { cari: q } });
    hasilCustomer.value = data.rows || [];
  }, 250);
});
function pilihCustomer(c) {
  if (!c) return;
  form.kepala.kd_customer = c.kd_customer;
  form.customer_nama = c.nama;
  cariCustomer.value = "";
  hasilCustomer.value = [];
}

// --- Baris barang ----------------------------------------------------------
const satuan = useSatuan(props.base, "harga_jual");
const pegawaiOpsi = computed(() => opsi.value.pegawai || []);
const wadahTabel = ref(null);
const kotakEntri = ref(null);
const entri = ref("");
const hasil = ref([]);
const sorot = ref(0);
const pesanCari = ref("");
const fokusEntri = () => nextTick(() => kotakEntri.value?.focus?.());

let timer = null;
watch(entri, (q) => {
  clearTimeout(timer);
  sorot.value = 0;
  if (q.trim().length < 2) { hasil.value = []; return; }
  timer = setTimeout(async () => {
    const { data } = await axios.get(`${props.base}/cari-barang`, { params: { cari: q } });
    pesanCari.value = data.error || "";
    hasil.value = data.rows || [];
  }, 250);
});

function tambah(b) {
  if (!b) return;
  form.items.push({
    kd_barang: b.kd_barang, nama: b.nama, kd_satuan: b.kd_satuan, satuan: b.satuan,
    // Pegawai baris baru: tautan akun ini, atau pegawai baris pertama nota —
    // kolomnya NOT NULL, dan server memakai urutan yang sama bila kosong.
    kd_pegawai: props.kd_pegawai || form.items[0]?.kd_pegawai || "",
    qty: 1, harga_jual: b.harga_jual ?? 0, diskon1: 0, diskon2: 0, diskon3: 0, diskon4: 0,
  });
  entri.value = "";
  hasil.value = [];
  nextTick(() => {
    const rows = wadahTabel.value?.querySelectorAll("tbody tr[data-baris]");
    rows?.[rows.length - 1]?.querySelector("[data-nav-qty]")?.select?.();
  });
}
function entriKey(e) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const n = hasil.value.length;
    if (n) sorot.value = (sorot.value + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    return;
  }
  if (e.key !== "Enter") return;
  e.preventDefault();
  tambah(hasil.value[sorot.value]);
}
const hapus = (i) => form.items.splice(i, 1);
const navGrid = useGridNav(wadahTabel, { keEntri: fokusEntri, hapusBaris: hapus });

// --- Pratinjau total & selisih ----------------------------------------------
// Cerminan pj.ghb / pj.total_nota. HANYA pratinjau: total yang tersimpan
// dihitung ulang di server dengan rumus yang sama dengan pembuatan nota.
function ghb(harga, diskon) {
  if (harga <= 0) return harga;
  let v = harga;
  for (const x of diskon) {
    const n = angka(x);
    v = n > -1 && n < 1 ? v * (1 - n) : v - n;
  }
  return v;
}
const diskonKepala = computed(() => {
  const k = nota.value?.kepala || {};
  return [k.diskon1, k.diskon2, k.diskon3, k.diskon4];
});
const subtotal = (b) =>
  ghb(ghb(angka(b.harga_jual), [b.diskon1, b.diskon2, b.diskon3, b.diskon4]), diskonKepala.value)
  * angka(b.qty);
const totalBaru = computed(() => {
  const net = form.items.reduce((s, b) => s + subtotal(b), 0);
  return net * (1 + angka(form.kepala.pajak)) - angka(form.kepala.diskon_uang);
});

// Selisih versi layar — bentuknya sama dengan `edit_nota.selisih` supaya
// SelisihNota merender pratinjau dan jejak audit dengan cara yang sama.
const NILAI = ["qty", "harga_jual", "diskon1", "diskon2", "diskon3", "diskon4"];
const norm = (v) => String(v ?? "").trim().toUpperCase();
function berkunci(daftar) {
  const hitung = {}, out = new Map();
  for (const b of daftar) {
    const dasar = `${norm(b.kd_barang)}|${norm(b.kd_satuan)}|${norm(b.kd_pegawai)}`;
    hitung[dasar] = (hitung[dasar] || 0) + 1;
    out.set(`${dasar}|${hitung[dasar]}`, b);
  }
  return out;
}
const selisih = computed(() => {
  if (!nota.value) return null;
  const lama = nota.value.kepala;
  const kepala = KEPALA.filter((c) => {
    if (c === "tanggal_jatuh_tempo") return String(lama[c] || "").slice(0, 10) !== form.kepala[c];
    if (c === "diskon_uang" || c === "pajak") return angka(lama[c]) !== angka(form.kepala[c]);
    return String(lama[c] ?? "").trim() !== String(form.kepala[c] ?? "").trim();
  }).map((c) => ({ kolom: c, dari: lama[c], ke: form.kepala[c] }));
  const a = berkunci(nota.value.baris), b = berkunci(form.items);
  const diubah = [];
  for (const [k, x] of a) {
    const y = b.get(k);
    if (!y) continue;
    const beda = {};
    for (const c of NILAI) if (angka(x[c]) !== angka(y[c])) beda[c] = { dari: angka(x[c]), ke: angka(y[c]) };
    if (Object.keys(beda).length) diubah.push({ ...y, beda });
  }
  return {
    kepala,
    barang: {
      ditambah: [...b].filter(([k]) => !a.has(k)).map(([, v]) => v),
      dihapus: [...a].filter(([k]) => !b.has(k)).map(([, v]) => v),
      diubah,
    },
  };
});
const adaPerubahan = computed(() => {
  const s = selisih.value;
  return Boolean(s && (s.kepala.length || s.barang.ditambah.length
    || s.barang.dihapus.length || s.barang.diubah.length));
});
const alasanCukup = computed(() => form.alasan.trim().length >= props.min_alasan);
const barisSah = computed(() => form.items.length > 0
  && form.items.every((b) => angka(b.qty) > 0 && b.kd_satuan && b.kd_pegawai));
const siap = computed(() => Boolean(props.kd_user) && !terhalang.value && adaPerubahan.value
  && alasanCukup.value && barisSah.value);

// --- Simpan ----------------------------------------------------------------
const konfirmasi = ref(false);
const muatUlangRiwayat = ref(0);
function simpan() {
  form
    .transform((f) => ({
      no_transaksi: nota.value.kepala.no_transaksi,
      versi: nota.value.versi,
      alasan: f.alasan,
      ...f.kepala,
      diskon_uang: angka(f.kepala.diskon_uang),
      pajak: angka(f.kepala.pajak),
      items: f.items.map((b) => ({
        kd_barang: b.kd_barang, kd_satuan: b.kd_satuan, kd_pegawai: b.kd_pegawai,
        qty: angka(b.qty), harga_jual: angka(b.harga_jual),
        diskon1: angka(b.diskon1), diskon2: angka(b.diskon2),
        diskon3: angka(b.diskon3), diskon4: angka(b.diskon4),
      })),
    }))
    .post(`${props.base}/save`, {
      preserveScroll: true,
      // Kalau server menolak (penghalang, versi berubah), isian yang sudah
      // diketik bertahan. Kalau berhasil, versi baru datang dari server dan
      // `watch(versi)` di atas mengisi ulang formulir dari isi yang tersimpan.
      preserveState: true,
      onFinish: () => {
        konfirmasi.value = false;
        muatUlangRiwayat.value += 1;
      },
    });
}
</script>

<template>
  <AdminLayout title="Edit Nota Penjualan">
    <Banner
      v-if="!kd_user"
      variant="warning"
      class="mb-4"
      message="Akun Anda belum ditautkan ke user legacy untuk koneksi ini, jadi edit belum bisa disimpan. Minta pengelola aplikasi mengisinya di Kelola Tautan User."
    />

    <!-- Kotak nomor nota di LUAR Deferred: tampil seketika, sebelum isi nota. -->
    <Card class="mb-4">
      <form class="flex flex-wrap items-end gap-2" @submit.prevent="buka">
        <div class="min-w-64 flex-1">
          <Input v-model="cariNo" label="Nomor nota" placeholder="mis. SC2609250001" autofocus />
        </div>
        <Button type="submit" :disabled="!cariNo.trim()">Buka nota</Button>
      </form>
      <p class="mt-2 text-xs text-ink-subtle">
        Setiap edit tercatat di Jejak Audit bersama isi nota sebelum dan sesudahnya, alasan
        Anda, dan akun Anda — dan di server tercatat seperti edit dari aplikasi lama.
      </p>
    </Card>

    <Deferred data="data">
      <template #fallback><LoadingCard message="Membuka nota…" /></template>

      <Banner v-if="d.conn_error" variant="warning" :message="d.conn_error" class="mb-4" />
      <Banner v-if="d.ditolak" variant="danger" :message="d.ditolak" class="mb-4" />
      <Banner v-if="d.pesan" variant="info" :message="d.pesan" class="mb-4" />

      <template v-if="nota">
        <Banner
          v-for="(p, i) in nota.penghalang"
          :key="i"
          variant="danger"
          class="mb-2"
          :message="p"
        />

        <div class="grid gap-4 lg:grid-cols-3">
          <Card class="lg:col-span-2">
            <div class="mb-4 grid gap-3 text-sm sm:grid-cols-4">
              <div>
                <p class="text-xs text-ink-subtle">Nomor</p>
                <p class="font-mono text-ink">{{ nota.kepala.no_transaksi }}</p>
              </div>
              <div>
                <p class="text-xs text-ink-subtle">Tanggal nota (tetap)</p>
                <p class="text-ink">{{ tanggalJam(nota.kepala.tanggal) }}</p>
              </div>
              <div>
                <p class="text-xs text-ink-subtle">Terakhir disimpan</p>
                <p class="text-ink">{{ tanggalJam(nota.kepala.tanggal_server) }}</p>
              </div>
              <div>
                <p class="text-xs text-ink-subtle">Oleh (user legacy)</p>
                <p class="text-ink">{{ nota.kepala.user_nama || nota.kepala.kd_user }}</p>
              </div>
            </div>

            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <p class="mb-1 text-xs font-medium text-ink-muted">Pelanggan</p>
                <p class="mb-1 text-sm text-ink">
                  {{ form.customer_nama || "—" }}
                  <span class="font-mono text-xs text-ink-subtle">{{ form.kepala.kd_customer }}</span>
                </p>
                <input
                  v-model="cariCustomer"
                  :disabled="terhalang"
                  class="w-full rounded-control border border-border-strong bg-surface px-2.5 py-1.5 text-sm disabled:opacity-50"
                  placeholder="Ganti pelanggan: ketik nama… ↑↓ lalu Enter"
                  @keydown.down.prevent="sorotCust = Math.min(sorotCust + 1, hasilCustomer.length - 1)"
                  @keydown.up.prevent="sorotCust = Math.max(sorotCust - 1, 0)"
                  @keydown.enter.prevent="pilihCustomer(hasilCustomer[sorotCust])"
                />
                <ul v-if="hasilCustomer.length" class="mt-1 max-h-48 overflow-y-auto rounded-control border border-border-default">
                  <li
                    v-for="(c, i) in hasilCustomer"
                    :key="c.kd_customer"
                    :class="['cursor-pointer px-2 py-1.5 text-sm', i === sorotCust ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                    @click="pilihCustomer(c)"
                  >
                    <p class="text-ink">{{ c.nama }}</p>
                    <p class="truncate font-mono text-xs text-ink-subtle">{{ c.kd_customer }}</p>
                  </li>
                </ul>
              </div>
              <Input v-model="form.kepala.tanggal_jatuh_tempo" type="date" label="Jatuh tempo" :disabled="terhalang" />
              <Select v-model="form.kepala.kd_jenis" label="Jenis bayar" :options="opsi.jenis_bayar || []" :disabled="terhalang" />
              <Select v-model="form.kepala.kd_kas" label="Kas" :options="opsi.kas || []" :disabled="terhalang" />
              <Select v-model="form.kepala.kd_voucher" label="Voucher" :options="opsi.voucher || []" :disabled="terhalang" />
              <Input v-model="form.kepala.no_bukti" label="No. bukti" maxlength="30" :disabled="terhalang" />
              <Input v-model="form.kepala.keterangan" label="Keterangan" maxlength="100" :disabled="terhalang" />
              <div class="grid grid-cols-2 gap-2">
                <Input v-model="form.kepala.diskon_uang" type="number" inputmode="numeric" step="1" min="0" label="Diskon (Rp)" :disabled="terhalang" />
                <Input v-model="form.kepala.pajak" type="number" inputmode="decimal" step="any" min="0" max="1" label="Pajak (0.05 = 5%)" :disabled="terhalang" />
              </div>
            </div>
          </Card>

          <Card>
            <h3 class="mb-2 text-sm font-semibold text-ink">Pratinjau perubahan</h3>
            <SelisihNota :selisih="selisih" :total="{ dari: nota.total_tersimpan ?? nota.total, ke: totalBaru }" />
            <p v-if="nota.total_tersimpan === null" class="mt-2 text-xs text-ink-subtle">
              Nota lama ini belum punya baris total di server; baris itu dibuatkan saat disimpan.
            </p>

            <div class="mt-4">
              <label class="mb-1 block text-xs font-medium text-ink-muted">Alasan edit *</label>
              <textarea
                v-model="form.alasan"
                rows="3"
                maxlength="255"
                :disabled="terhalang"
                class="w-full rounded-control border border-border-strong bg-surface px-2.5 py-1.5 text-sm disabled:opacity-50"
                placeholder="mis. salah ketik qty; pelanggan minta ganti barang"
              />
              <p class="text-xs text-ink-subtle">
                Minimal {{ min_alasan }} huruf. Tersimpan di Jejak Audit dan tak bisa diubah.
              </p>
            </div>
            <Button class="mt-3 w-full" :disabled="!siap" @click="konfirmasi = true">
              Simpan perubahan…
            </Button>
            <p v-if="!barisSah && form.items.length" class="mt-1 text-xs text-danger-fg">
              Setiap baris butuh qty lebih dari nol, satuan, dan pegawai.
            </p>
          </Card>
        </div>

        <Card class="mt-4">
          <div class="mb-3 flex items-center justify-between">
            <h3 class="text-sm font-semibold text-ink">Barang ({{ form.items.length }})</h3>
            <p class="text-sm text-ink-muted">Total baru: <strong class="text-ink">{{ rupiah(totalBaru) }}</strong></p>
          </div>
          <div ref="wadahTabel" class="overflow-x-auto" @keydown="navGrid">
            <table class="w-full text-sm">
              <thead class="text-xs text-ink-subtle">
                <tr class="border-b border-border-default">
                  <th class="px-2 py-1 text-left font-medium">Barang</th>
                  <th class="w-36 px-2 py-1 text-left font-medium">Satuan</th>
                  <th class="w-40 px-2 py-1 text-left font-medium">Pegawai</th>
                  <th class="w-24 px-2 py-1 text-right font-medium">Qty</th>
                  <th class="w-32 px-2 py-1 text-right font-medium">Harga</th>
                  <th class="w-24 px-2 py-1 text-right font-medium">Diskon</th>
                  <th class="w-32 px-2 py-1 text-right font-medium">Subtotal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(b, i) in form.items" :key="i" data-baris class="border-b border-border-default">
                  <td class="px-2 py-1">
                    <p class="text-ink">{{ b.nama || b.kd_barang }}</p>
                    <p class="font-mono text-xs text-ink-subtle">{{ b.kd_barang }}</p>
                  </td>
                  <td class="px-2 py-1">
                    <select
                      data-nav
                      :value="b.kd_satuan"
                      :disabled="terhalang"
                      :class="KELAS_PILIH"
                      @focus="satuan.muat(b)"
                      @change="satuan.ganti(b, $event.target.value)"
                    >
                      <option v-if="!satuan.opsi(b).length" :value="b.kd_satuan">{{ b.satuan || b.kd_satuan }}</option>
                      <option v-for="s in satuan.opsi(b)" :key="s.kd_satuan" :value="s.kd_satuan">{{ satuan.label(s) }}</option>
                    </select>
                  </td>
                  <td class="px-2 py-1">
                    <select v-model="b.kd_pegawai" data-nav :disabled="terhalang" :class="KELAS_PILIH">
                      <option v-if="!pegawaiOpsi.some((p) => p.value === b.kd_pegawai)" :value="b.kd_pegawai">
                        {{ b.pegawai || b.kd_pegawai || "(pilih)" }}
                      </option>
                      <option v-for="p in pegawaiOpsi" :key="p.value" :value="p.value">{{ p.label }}</option>
                    </select>
                  </td>
                  <td class="px-2 py-1">
                    <input v-model="b.qty" data-nav data-nav-qty inputmode="decimal" :disabled="terhalang" :class="KELAS_SEL" @blur="b.qty = angka(b.qty)" />
                  </td>
                  <td class="px-2 py-1">
                    <input v-model="b.harga_jual" data-nav inputmode="decimal" :disabled="terhalang" :class="KELAS_SEL" @blur="b.harga_jual = angka(b.harga_jual)" />
                  </td>
                  <td class="px-2 py-1">
                    <input v-model="b.diskon1" data-nav inputmode="decimal" :disabled="terhalang" :class="KELAS_SEL" title="Di bawah 1 = persen (0,1 = 10%), selebihnya rupiah" @blur="b.diskon1 = angka(b.diskon1)" />
                  </td>
                  <td class="px-2 py-1 text-right tabular-nums">{{ rupiah(subtotal(b)) }}</td>
                  <td class="px-2 py-1 text-right">
                    <Button size="sm" variant="ghost" :disabled="terhalang" @click="hapus(i)">Hapus</Button>
                  </td>
                </tr>
                <tr v-if="!terhalang" class="bg-surface-2/50">
                  <td class="px-2 py-2" colspan="8">
                    <input
                      ref="kotakEntri"
                      v-model="entri"
                      class="w-full rounded-control border border-border-strong bg-surface px-3 py-2 font-mono"
                      placeholder="Tambah barang: ketik kode atau nama… ↑↓ lalu Enter"
                      @keydown="entriKey"
                    />
                    <p v-if="pesanCari" class="mt-1 text-xs text-warning-fg">{{ pesanCari }}</p>
                    <ul v-if="hasil.length" class="mt-2 max-h-56 overflow-y-auto rounded-control border border-border-default">
                      <li
                        v-for="(h, j) in hasil"
                        :key="`${h.kd_barang}-${h.kd_satuan}`"
                        :class="['flex cursor-pointer items-baseline gap-3 px-3 py-1.5 text-sm', j === sorot ? 'bg-brand-bg' : 'hover:bg-surface-2']"
                        @click="tambah(h)"
                      >
                        <span class="font-mono text-xs text-ink-subtle">{{ h.kd_barang }}</span>
                        <span class="flex-1 truncate text-ink">{{ h.nama }}</span>
                        <span class="text-xs text-ink-subtle">{{ h.satuan }}</span>
                        <span class="tabular-nums text-xs text-ink-subtle">{{ rupiah(h.harga_jual) }}</span>
                      </li>
                    </ul>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-2 text-xs text-ink-subtle">
            ↑↓ pindah baris · Enter sel berikutnya · Ctrl+Del hapus baris. Diskon kepala nota
            (bila ada) tetap berlaku dan ikut dihitung di subtotal.
          </p>
        </Card>

        <Card class="mt-4">
          <h3 class="mb-3 text-sm font-semibold text-ink">Riwayat nota ini</h3>
          <RiwayatNota :url="`${base}/riwayat`" :no="nota.kepala.no_transaksi" :muat-ulang="muatUlangRiwayat" />
        </Card>

        <Modal :show="konfirmasi" title="Simpan edit nota?" size="lg" @close="konfirmasi = false">
          <p class="mb-3 text-sm text-ink-muted">
            Nota <span class="font-mono text-ink">{{ nota.kepala.no_transaksi }}</span> akan ditulis ulang di
            server atas nama <span class="font-mono text-ink">{{ kd_user }}</span>, seperti edit dari aplikasi lama.
          </p>
          <SelisihNota :selisih="selisih" :total="{ dari: nota.total_tersimpan ?? nota.total, ke: totalBaru }" />
          <p class="mt-3 text-sm text-ink">Alasan: “{{ form.alasan.trim() }}”</p>
          <div class="mt-4 flex justify-end gap-2">
            <Button variant="secondary" @click="konfirmasi = false">Batal</Button>
            <Button :loading="form.processing" @click="simpan">Ya, simpan</Button>
          </div>
        </Modal>
      </template>
    </Deferred>
  </AdminLayout>
</template>
