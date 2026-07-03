# Rencana Implementasi Frontend — Arunika POS

> **Status:** Draft v1 — 2026-07-04
> **Pendamping:** `planing/prd.md` (dokumen ini mengeksekusi sisi frontend-nya). Referensi silang: PRD §6 (standar UX read), §7 (spesifikasi modul), §11 (perombakan frontend), §12 (fase).
> **Prioritas (permintaan user):** **utamakan fungsi & fitur (Bagian A), baru kenyamanan penggunaan (Bagian B).**
> **Stack tetap:** Vue 3 (Composition API) + Inertia-Django + Tailwind v4 + Pinia + Vite. **Tanpa TypeScript.** Tema **Gundam RX-78-2 dipertahankan** (`frontend/css/main.css`).

---

## 0. Konteks & Referensi

Perombakan frontend menyeluruh: semua halaman mock jadi real, UX read diseragamkan (advanced filter, search, sort, export XLSX), semua berat via **deferred**, dan navigasi/IA dirapikan. Prinsip utama: **reuse-first** — perkuat komponen yang sudah ada (`DataTable`, `ReportView`), jangan bikin varian tandingan.

**Aturan main:**
- Halaman Inertia di `frontend/pages/Admin/**`, dibungkus `AdminLayout.vue`, alias `@` → `frontend/`.
- Semua teks UI **Bahasa Indonesia**.
- Angka/mata uang format `id-ID` / Rupiah.
- Tema RX (token oklch, aksen merah/kuning, `panel-strip`, `vfin`, `page-enter`, `scroll-slim`) dipertahankan; dark mode wajib paritas.

---

## 1. Kondisi Sekarang (basis rencana)

### 1.1 Halaman yang masih mock (17) — target konversi

| Modul | File | Impor mock |
|-------|------|-----------|
| Reports | `PenjualanAll.vue`, `PenjualanNota.vue`, `PenjualanCustomer.vue`, `PenjualanUser.vue`, `PenjualanPeriode.vue`, `ReturPenjualan.vue`, `Pembelian.vue`, `ReturPembelian.vue` | `@/mock/penjualan`, `@/mock/pembelian` |
| Inventory | `Opname.vue`, `StokAkhir.vue`, `StokDivisi.vue` | `@/mock/inventory` |
| Cash | `Kas.vue`, `Shift.vue` | `@/mock/kas` |
| Promo | `Promo.vue`, `Voucher.vue` | `@/mock/promo` |
| Analytics | `FmiPenjualan.vue`, `FmiStok.vue` | `@/mock/analitik` |

> Catatan: `StokAkhir`/`StokDivisi`/`Opname` **masih mock** (bukan "mixed" seperti dugaan awal). `Stock.vue` (Monitoring) & `BarangHistori.vue` sudah real.

### 1.2 Halaman sudah real (dirapikan, bukan dibangun ulang)
`Dashboard`, `Stock`, `BarangHistori`, `MasterData/Products`, `MasterData/Customers`, `MasterData/UpdateBarang` (write), `MasterData/SyncHarga` (write), `Connections/Index`, `Menus/Index`, `ActivityLogs`, `Profile`.

### 1.3 Komponen reusable existing (API ringkas)

| Komponen | API inti | Catatan |
|----------|----------|---------|
| `ui/DataTable.vue` | props `columns, rows, rowKey, loading, perPage, emptyMessage`; slot `cell-{key}` `{row,value}`; kolom `{key,label,sortable?,align?,format?}` (`format`: `number`\|`rupiah`) | **client-only** (sort + paginasi internal) |
| `report/ReportView.vue` | props `title, subtitle, columns, rows, rowKey, perPage, searchKeys, searchPlaceholder, exportName, sheetName, emptyMessage, connError`; slot `filters, summary, cell-*` | search + export client; pakai `CollapsibleSection` |
| `ui/Pagination.vue` | props `page, total, perPage`; emit `update:page` | client-only |
| `ui/Card, Button, Input, Select, Modal, Badge, Banner, LoadingCard, ToastContainer` | (lihat kode) | dipakai ulang apa adanya |
| `utils/xlsx.js` | `downloadXlsx(filename, columns, rows, sheetName)`, `stamp()` | export client |
| stores | `user` (user/role/allowedMenus), `ui` (sidebar/toasts/theme + `pushToast`), `connection` (active/list + `switchConnection`) | hydrate dari `inertia_share` |
| `composables/useNav.js` | `SECTION_LABELS`, `NAV_GROUPS` (5 tab), `sections/tabs/activeTab/isActive` | sinkron manual dengan `apps/core/menus.py` |

**Kesenjangan utama:** tidak ada dukungan **server-side pagination** di komponen mana pun. Ini fondasi Bagian A.

---

## 2. Prinsip Frontend

1. **Deferred everywhere** — bundle berat via `<Deferred data="x">` + `LoadingCard` fallback; filter/toolbar di luar `<Deferred>`; `conn_error` dirender `Banner` di dalam.
2. **Standar UX read (PRD §6)** diterapkan seragam, menyesuaikan modul.
3. **Reuse-first** — extend `DataTable`/`ReportView`, jangan duplikat.
4. **Pagination hybrid** — tabel besar server-side, kecil client-side.
5. **Kontrak backend** — frontend mengasumsikan backend (per PRD) mengirim: bundle deferred `{ rows, total, page, per_page, sort, sort_dir, summary, conn_error }` untuk laporan besar; `filters` echo untuk restore form; endpoint `…/export` untuk unduh besar.

---

# BAGIAN A — FUNGSI & FITUR (prioritas 1)

## A1. Fondasi Komponen Bersama

Dibangun/di-extend lebih dulu (Fase FF1). Semua halaman memakainya — tidak boleh bikin varian sendiri.

### A1.1 `DataTable` — tambah **mode server** (backward-compatible)
Props baru (mode client existing tetap jalan bila `serverSide=false`):

```
serverSide  Boolean  default false   // aktifkan mode server
total       Number   default 0       // total baris (untuk hitung halaman)
page        Number   default 1        // controlled (mode server)
perPage     Number   default 10
sortKey     String   default null     // controlled
sortDir     String   default "asc"    // "asc" | "desc"
```
Emit (mode server): `@page-change(page)`, `@sort-change({ key, dir })`. Di mode server, DataTable **tidak** mengurut/memotong sendiri — hanya render `rows` apa adanya dan pancarkan intent; parent (halaman) yang `router.get` ulang.

### A1.2 `FilterPanel` (baru)
Kerangka panel filter kolaps (pakai `CollapsibleSection`), kelola state field, tombol **Tampilkan** + **Reset**.

```
props:  modelValue Object   // state filter { date_from, date_to, kd_divisi, ... }
        loading    Boolean
        collapsible Boolean default true
emits:  update:modelValue, submit(params), reset
slot:   default → field-field (DateRangeField, SelectSearch, dll.)
```
`submit` mengeluarkan params bersih (buang nilai kosong), halaman meneruskan ke `router.get`.

### A1.3 `ExportButton` (baru)
Dua mode:
```
props:  mode "client" | "server"  default "client"
        // client:
        filename, columns, rows, sheetName
        // server:
        href           // "/admin-panel/laporan/penjualan/export?<query aktif>"
        disabled, loading
```
Mode client memanggil `downloadXlsx`. Mode server = anchor unduh (membawa filter aktif), untuk dataset besar hasil filter penuh.

### A1.4 `ReportView` v2
Perkuat sebagai kerangka generik semua laporan: dukung **deferred + server pagination + summary + filter**. Tambahan di atas API existing:
```
serverSide Boolean   // teruskan ke DataTable
total, page, sortKey, sortDir   // controlled
loading    Boolean
emits: page-change, sort-change, (filter via slot #filters + FilterPanel)
```
Mode client existing (mock lama) tetap didukung selama transisi.

### A1.5 Field filter reusable
- `DateRangeField` — dua `input[type=date]` + **preset**: Hari ini, Kemarin, 7 Hari, Bulan Ini, Bulan Lalu, Custom. Default halaman transaksi = **Bulan Ini** (wajib ada rentang tanggal, PRD §6/§10).
- `SelectSearch` — dropdown dengan kotak cari, untuk divisi/kategori/customer/supplier/kas/user (opsi dari bundle deferred atau prop terpisah non-deferred bila ringan).
- `StatusSelect` — enum status (0/1/2 → Non-aktif/Aktif/Tidak dijual) sesuai modul.

### A1.6 Penyaji
- `SummaryStrip`/`StatCard` — kartu ringkasan di atas tabel (total baris, total nilai, dsb.), bagian bundle deferred.
- `EmptyState` — bedakan "belum difilter" vs "0 hasil".
- `TableSkeleton` — placeholder baris saat loading non-blocking.

### A1.7 Reuse tanpa ubah
`Card, Button, Input, Select, Modal, Badge, Banner, LoadingCard, Pagination, ToastContainer`, `useNav`, stores, `utils/xlsx`.

---

## A2. Kontrak Data & Pola Halaman Standar

Pola halaman laporan besar (server-side). Semua halaman baru mengikuti bentuk ini (referensi existing: `BarangHistori.vue`):

```vue
<script setup>
import { reactive, computed } from "vue";
import { Deferred, router } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import ReportView from "@/components/report/ReportView.vue";
import FilterPanel from "@/components/ui/FilterPanel.vue";
import DateRangeField from "@/components/ui/DateRangeField.vue";
import SelectSearch from "@/components/ui/SelectSearch.vue";

const props = defineProps({
  report: { type: Object, default: null },   // deferred: { rows, total, page, per_page, sort, sort_dir, summary, conn_error, options }
  filters: { type: Object, default: () => ({}) },
});
const data = computed(() => props.report || {});
const URL = "/admin-panel/laporan/penjualan";

const form = reactive({
  date_from: props.filters.date_from || "",   // default diisi backend = bulan berjalan
  date_to: props.filters.date_to || "",
  kd_divisi: props.filters.kd_divisi || "",
  search: props.filters.search || "",
  sort: props.filters.sort || "tanggal",
  sort_dir: props.filters.sort_dir || "desc",
  page: props.filters.page || 1,
});

function apply(extra = {}) {
  const params = { ...form, ...extra };
  Object.keys(params).forEach((k) => params[k] === "" && delete params[k]);
  router.get(URL, params, { preserveState: true, preserveScroll: true });
}
</script>

<template>
  <AdminLayout title="Penjualan (Detail)">
    <FilterPanel :loading="false" @submit="apply({ page: 1 })" @reset="/* reset form + apply */">
      <DateRangeField v-model:from="form.date_from" v-model:to="form.date_to" />
      <SelectSearch v-model="form.kd_divisi" :options="data.options?.divisi || []" label="Divisi" />
    </FilterPanel>

    <Deferred data="report">
      <template #fallback><TableSkeleton /></template>
      <Banner v-if="data.conn_error" variant="warning" :message="data.conn_error" />
      <ReportView
        title="Penjualan (Detail)"
        :columns="columns" :rows="data.rows || []" row-key="_rid"
        server-side :total="data.total || 0" :page="form.page"
        :sort-key="form.sort" :sort-dir="form.sort_dir"
        :summary="data.summary"
        @page-change="(p) => apply({ page: p })"
        @sort-change="(s) => apply({ sort: s.key, sort_dir: s.dir, page: 1 })"
      >
        <template #export>
          <ExportButton mode="server" :href="`${URL}/export?` + new URLSearchParams(form)" />
        </template>
      </ReportView>
    </Deferred>
  </AdminLayout>
</template>
```

Halaman kecil (master, stok akhir, promo, voucher): tetap **client-side** — fetch hasil filter penuh sebagai bundle deferred, `ReportView` mode client existing + `downloadXlsx`.

---

## A3. Konversi Halaman per Modul

Legenda: **Pg** = pagination (S=server, C=client). Semua = deferred + `conn_error` + export.

### Penjualan (Reports) — server-side, tanggal wajib (PRD §7.2)

| Halaman / File | Sumber | Kolom inti | Filter | Search | Sort | Pg | Export |
|---|---|---|---|---|---|---|---|
| Detail / `PenjualanAll.vue` | `t_penjualan⋈detail⋈m_barang⋈m_customer` | no_transaksi, tanggal, customer, barang, qty, harga, subtotal | tanggal, divisi, customer, kasir, barang, jenis bayar | server (no/barang/customer) | server | S | server |
| Per Nota / `PenjualanNota.vue` | `t_penjualan`+agg detail | no_transaksi, tanggal, customer, total kotor, potongan, pajak, total bersih | tanggal, divisi, customer, kasir | server | server | S | server |
| Per Customer / `PenjualanCustomer.vue` | agg per `kd_customer` | customer, kota, jml nota, total | tanggal, divisi | client | server | S | server |
| Per User / `PenjualanUser.vue` | agg per `kd_user⋈m_userx` | user, jml nota, total | tanggal, divisi | client | server | S | server |
| Per Periode / `PenjualanPeriode.vue` | agg per hari/bulan | periode, jml nota, total (+ `BarChart`) | rentang, granularitas, divisi | — | server | S | server |
| Retur / `ReturPenjualan.vue` | `t_penjualan_retur(_detail)` | no_retur, tanggal, customer, barang, qty, nilai | tanggal, divisi, customer | server | server | S | server |

### Pembelian (Reports) — server-side (PRD §7.3)

| Halaman / File | Sumber | Filter |
|---|---|---|
| `Pembelian.vue` | `t_pembelian(_detail)⋈m_supplier⋈m_barang` | tanggal, divisi, supplier, barang |
| `ReturPembelian.vue` | `t_pembelian_retur(_detail)` | tanggal, divisi, supplier |

### Stok (Inventory) — PRD §7.4

| Halaman / File | Aksi | Sumber | Pg |
|---|---|---|---|
| `Opname.vue` (mock→real) | bangun real | `t_opname_stok⋈t_opname_proses` | S (tanggal, divisi, barang, status; kolom selisih qty) |
| `StokAkhir.vue` (mock→real) | bangun real | movement engine per tanggal cutoff | C (validasi silang `m_barang_stok_akhir`) |
| `StokDivisi.vue` (mock→real) | bangun real | `inv.stock_levels`+`m_barang_divisi` | C (filter kategori/status, tanda < stok_min) |
| `Stock.vue` (real) | rapikan | existing | C (+export + FilterPanel) |
| `BarangHistori.vue` (real) | rapikan | existing | S (**tambah `ExportButton`** — belum ada) |

### Analitik — PRD §7.5

| Halaman / File | Sumber | Isi |
|---|---|---|
| `FmiPenjualan.vue` | agg `t_penjualan_detail` per barang/periode | ranking fast/medium/slow (qty & nilai); filter periode, divisi, kategori |
| `FmiStok.vue` | FMI penjualan ⋈ stok akhir | rasio jual vs stok → overstock/sehat/kritis (badge warna) |

### Promo & Voucher — PRD §7.6 (client-side, dataset kecil)

| Halaman / File | Sumber |
|---|---|
| `Promo.vue` | `m_barang_promo(_detail)` + `m_barang_divisi_diskon` (status dari rentang tanggal+jam) |
| `Voucher.vue` | `m_voucher` + pemakaian dari `t_penjualan.kd_voucher` |

### Kas & Shift — PRD §7.7

| Halaman / File | Sumber | Pg |
|---|---|---|
| `Kas.vue` | `t_mutasi_kas`, `t_penambahan_kas`, `t_biaya_operasional`, `t_pendapatan` + saldo `m_kas` | S (buku kas per `kd_kas`, saldo berjalan; filter kas, tanggal, jenis) |
| `Shift.vue` | `t_pegawai_ganti_shift(_detail)⋈m_pegawai` | S (filter tanggal, pegawai, divisi) |

### Master & Dashboard & Admin

| Halaman / File | Aksi |
|---|---|
| `Products.vue` | +export, +filter merk/model/warna/status, pagination server bila > cap |
| `Customers.vue` | +export, +filter kota/status |
| **`MasterData/Supplier.vue` (baru)** | `m_supplier⋈m_kota`, pola sama pelanggan |
| `Dashboard.vue` | rapikan KPI real; `StatCard`/`SummaryStrip` seragam |
| `ActivityLogs.vue` | +filter aksi/user/tanggal + export |

---

## A4. Fitur Write (frontend)

### A4.1 `UpdateBarang.vue` (existing, diperbaiki)
- Pertahankan alur harga + status (service `update_harga`/`update_status`).
- **Tambah konfirmasi diff**: sebelum simpan, `Modal` menampilkan **nilai lama → baru** per satuan (harga & margin live untuk retail). Toast sukses via `ui.pushToast`.

### A4.2 `SyncHarga.vue` + **Riwayat Sync (baru)**
- Alur compare → pilih item → apply dipertahankan (mode gudang→grosir tanpa margin; retail→retail dengan margin).
- **Halaman baru `MasterData/SyncHistory.vue`** (section Master): daftar `SyncRun` (waktu, user, src→dst, mode, jml baris, status) dengan FilterPanel (tanggal, user, src/dst, status) + search + export; klik baris → drill-down `SyncRunItem` (kd_barang, nama, harga lama dst → harga baru, with_margin) dalam `Modal`/panel.
- Data dari SQLite (model `SyncRun`/`SyncRunItem`, PRD §8) via props deferred.

---

## A5. IA & Navigasi

- Update `composables/useNav.js`: `SECTION_LABELS`/`NAV_GROUPS` — tambah item **Riwayat Sync** & **Master Supplier** di section `master` (sinkron dengan `apps/core/menus.py`).
- Breadcrumb ringan per halaman (section → halaman) di `AdminLayout`.
- Active state: `isActive(href)` existing dipertahankan; pastikan halaman baru punya menu key.
- **Akhir proyek:** hapus `frontend/mock/*.js` setelah semua halaman real (kriteria selesai FF8).

---

# BAGIAN B — KENYAMANAN PENGGUNAAN (prioritas 2)

> Diterapkan setelah fungsi jalan; sebagian menyertai tiap halaman, finalisasi menyeluruh di FF8.

### B1. State filter persisten
- **URL query params** sebagai sumber kebenaran filter (shareable, tombol back/forward jalan, cocok `router.get`); form di-restore dari `props.filters` (echo backend).
- Opsi: ingat filter terakhir per halaman via `localStorage` (kunci `sct.filter.<page>`) untuk kembali ke halaman tanpa mengetik ulang.

### B2. Interaksi cepat
- **Enter** di field filter → submit; tombol **Reset** kembali ke default (bulan berjalan).
- Shortcut **`/`** fokus ke kotak search.
- **Sticky**: FilterPanel/toolbar dan header tabel `sticky` saat scroll panjang.
- Loading **non-blocking**: `TableSkeleton` menggantikan spinner penuh untuk re-fetch (halaman tidak melompat); `preserveScroll` di semua `router.get`.

### B3. Umpan balik
- **Toast** sukses simpan/sync/export (`ui.pushToast`); error koneksi via `Banner` (`conn_error`).
- **EmptyState** membedakan "Gunakan filter untuk menampilkan data" vs "Tidak ada hasil untuk filter ini".
- **Badge** status berwarna (aktif/non-aktif, fast/slow, overstock/kritis) pakai token semantic.

### B4. Tabel nyaman
- **Mobile**: horizontal scroll + tandai kolom prioritas (sembunyikan kolom sekunder di layar kecil).
- Angka **rata kanan** + format `id-ID`/Rupiah (`format` kolom existing).
- **Zebra/hover** baris; **kolom pertama sticky** untuk tabel lebar.
- **Page-size selector** (25/50/100) di mode server.
- **Baris total** di footer tabel untuk kolom nilai (dari `summary` bundle).

### B5. Responsif & tema
- **Dark mode paritas**: semua komponen baru pakai token `surface/ink/border/*-bg/*-fg` — dilarang warna hardcode.
- `prefers-reduced-motion` dihormati (`page-enter` sudah punya guard).
- Mobile drawer nav existing tetap.

### B6. Aksesibilitas ringan
- Semua input berlabel; focus ring jelas; `aria-label` pada tombol ikon (theme/collapse/close/export); kontras cukup lewat token.

---

## Fase Implementasi Frontend (selaras PRD §12)

| Fase | Isi | Kriteria selesai |
|------|-----|------------------|
| **FF1 — Fondasi** | `DataTable` server-mode, `FilterPanel`, `ExportButton`, `ReportView` v2, `DateRangeField`/`SelectSearch`/`StatusSelect`, `SummaryStrip`/`EmptyState`/`TableSkeleton` + halaman **pilot Penjualan Detail** end-to-end | pilot lulus standar §6 penuh; komponen dipakai ulang |
| **FF2 — Penjualan** | 6 halaman penjualan real | `@/mock/penjualan` tak dipakai |
| **FF3 — Pembelian** | 2 halaman real | `@/mock/pembelian` tak dipakai |
| **FF4 — Stok & Opname** | Opname/StokAkhir/StokDivisi real; Stock/Histori rapikan + export | `@/mock/inventory` tak dipakai |
| **FF5 — Kas & Shift** | 2 halaman real | `@/mock/kas` tak dipakai |
| **FF6 — Promo/Voucher/Analitik** | 4 halaman real | `@/mock/promo`, `@/mock/analitik` tak dipakai |
| **FF7 — Riwayat Sync + write** | halaman `SyncHistory.vue` + konfirmasi diff UpdateBarang | riwayat tampil dengan diff per item |
| **FF8 — Polish** | IA final, `Master Supplier`, Log filter, **hapus `frontend/mock/`**, terapkan Bagian B menyeluruh | 0 impor mock; checklist B tuntas; smoke test semua menu |

---

## Verifikasi

Per halaman (Mode B: `npm run build` + `runserver`):
1. **Deferred** — fallback (`TableSkeleton`/`LoadingCard`) tampil dulu, lalu data terisi.
2. **Filter** — submit `FilterPanel` memicu `router.get`; URL berisi query; back/forward memulihkan state.
3. **Pagination server** — ganti halaman/urut memicu request baru; Network tab menampilkan param `page/sort` (backend OFFSET/FETCH).
4. **Export** — client (unduh langsung) & server (anchor membawa filter aktif) menghasilkan XLSX benar.
5. **Kenyamanan** — Enter submit, `/` fokus search, sticky header, toast muncul, empty state benar.
6. **Tema/responsif** — dark mode paritas; layout mobile (drawer + tabel scroll) rapi.
7. **Akhir** — `grep -r "@/mock" frontend/pages` = 0; folder `frontend/mock/` terhapus.

---

## Lampiran — Kontrak Komponen (ringkas)

```
DataTable (server mode)
  props:  serverSide:Boolean, total:Number, page:Number, perPage:Number,
          sortKey:String, sortDir:String  (+ columns/rows/rowKey/loading/emptyMessage existing)
  emits:  page-change(page:Number), sort-change({key:String, dir:'asc'|'desc'})

FilterPanel
  props:  modelValue:Object, loading:Boolean, collapsible:Boolean=true
  emits:  update:modelValue, submit(params:Object), reset
  slots:  default (fields)

ExportButton
  props:  mode:'client'|'server'='client',
          (client) filename:String, columns:Array, rows:Array, sheetName:String
          (server) href:String, disabled:Boolean, loading:Boolean

ReportView v2
  props:  + serverSide:Boolean, total:Number, page:Number, sortKey:String, sortDir:String,
            loading:Boolean, summary:Object
  emits:  page-change, sort-change
  slots:  filters, summary, export, cell-*  (existing dipertahankan)

DateRangeField
  props:  from:String, to:String, preset:String
  emits:  update:from, update:to, update:preset

SelectSearch
  props:  modelValue, options:[{value,label}], label:String, placeholder:String, searchable:Boolean=true
  emits:  update:modelValue
```
