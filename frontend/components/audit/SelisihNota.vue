<script setup>
// Apa yang berubah pada satu edit nota: isian kepala, lalu baris barang
// (ditambah / dihapus / diubah), lalu totalnya. Dipakai pratinjau di layar
// Edit Nota DAN detail Jejak Audit — satu cara membaca selisih, supaya yang
// dilihat pengedit sebelum menyimpan sama dengan yang dibaca auditor sesudahnya.
import { LABEL_KOLOM_NOTA } from "@/utils/labels";
import { tanggalJam } from "@/utils/tanggal";

const props = defineProps({
  // { kepala: [{kolom, dari, ke}], barang: {ditambah, dihapus, diubah} }
  selisih: { type: Object, default: null },
  // { dari, ke } — opsional
  total: { type: Object, default: null },
});

const nf = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 });
const uang = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 });
const rupiah = (v) => (v === null || v === undefined || v === "" ? "—" : `Rp ${uang.format(Number(v))}`);
const nilai = (kolom, v) => {
  if (v === null || v === undefined || v === "") return "(kosong)";
  if (kolom === "tanggal_jatuh_tempo") return tanggalJam(v);
  if (kolom === "diskon_uang") return rupiah(v);
  return v;
};
const LABEL_BEDA = { qty: "qty", harga_jual: "harga", diskon1: "diskon 1", diskon2: "diskon 2", diskon3: "diskon 3", diskon4: "diskon 4" };
const angkaBeda = (k, v) => (k === "harga_jual" ? rupiah(v) : nf.format(v));
const nama = (b) => b.nama || b.kd_barang;
const kosong = () => {
  const s = props.selisih;
  if (!s) return true;
  const b = s.barang || {};
  return !(s.kepala || []).length && !(b.ditambah || []).length && !(b.dihapus || []).length && !(b.diubah || []).length;
};
</script>

<template>
  <div class="space-y-2 text-sm">
    <p v-if="kosong()" class="text-ink-subtle">Belum ada perubahan.</p>
    <template v-else>
      <ul v-if="selisih.kepala && selisih.kepala.length" class="space-y-0.5">
        <li v-for="(c, i) in selisih.kepala" :key="`k${i}`" class="text-ink-muted">
          {{ LABEL_KOLOM_NOTA[c.kolom] || c.kolom }}:
          <span class="text-ink line-through decoration-ink-subtle">{{ nilai(c.kolom, c.dari) }}</span>
          → <span class="text-ink">{{ nilai(c.kolom, c.ke) }}</span>
        </li>
      </ul>
      <div class="space-y-0.5">
        <p v-for="(b, i) in selisih.barang.ditambah" :key="`t${i}`" class="text-success-fg">
          + {{ nama(b) }} — {{ nf.format(b.qty) }} @ {{ rupiah(b.harga_jual) }}
        </p>
        <p v-for="(b, i) in selisih.barang.dihapus" :key="`h${i}`" class="text-danger-fg">
          − {{ nama(b) }} — {{ nf.format(b.qty) }} @ {{ rupiah(b.harga_jual) }}
        </p>
        <p v-for="(b, i) in selisih.barang.diubah" :key="`u${i}`" class="text-ink">
          ~ {{ nama(b) }}:
          <span v-for="(d, k, j) in b.beda" :key="k">
            <template v-if="j">, </template>{{ LABEL_BEDA[k] || k }} {{ angkaBeda(k, d.dari) }} → {{ angkaBeda(k, d.ke) }}
          </span>
        </p>
      </div>
    </template>
    <p v-if="total && total.ke !== undefined && total.ke !== null" class="text-ink-muted">
      Total: <span class="text-ink">{{ rupiah(total.dari) }}</span> →
      <span class="font-medium text-ink">{{ rupiah(total.ke) }}</span>
    </p>
  </div>
</template>
