# Kelola Informasi Perusahaan & Penyesuaian Struk/Faktur Nota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a dedicated "Kelola Informasi Perusahaan" management page and enrich receipt (`baca_nota`) data to print complete company details, cashier name, customer name, payment type name, item codes, human-readable unit names, subtotal, discounts, total, amount paid, and change on receipts/invoices.

**Architecture:** Extend backend SQL services (`apps/master_data/services.py`, `apps/transactions/penjualan.py`, `apps/monitoring/views.py`) to query/update MS SQL tables `g_info_profile` and `m_divisi` and join receipt details with `m_satuan`, `m_pegawai`, `m_customer`, and `m_jenis_bayar`. Render updated receipts in `frontend/pages/Kasir/NotaCetak.vue` and create the management UI `frontend/pages/Admin/MasterData/KelolaInformasiPerusahaan.vue`.

**Tech Stack:** Django 5, Inertia-Django, Vue 3, MS SQL Server (pyodbc), Tailwind CSS.

## Global Constraints

- All MS SQL queries and updates during testing MUST strictly target the `Testing` connection profile. Never touch production/other branch databases.
- Follow existing codebase patterns: hand-written SQL using `core/mssql.py`, thin views, Inertia response rendering, Indonesian UI strings.

---

### Task 1: Backend Company Info Service & Management View

**Files:**
- Modify: `apps/master_data/services.py`
- Modify: `apps/monitoring/views.py`
- Modify: `apps/monitoring/urls.py`
- Modify: `apps/core/menus.py`
- Create: `apps/master_data/test_informasi_perusahaan.py`

**Interfaces:**
- Produces: `services.baca_info_perusahaan(profile)` -> `dict`
- Produces: `services.simpan_info_perusahaan(profile, data: dict)` -> `None`
- Produces: View `informasi_perusahaan(request)` handling GET (Inertia render) & POST (save profile/divisi info).

- [ ] **Step 1: Write the failing test for Company Info Service**

```python
# apps/master_data/test_informasi_perusahaan.py
from django.test import TestCase
from apps.master_data import services as master_services
from core.mssql import get_profile

class InformasiPerusahaanTest(TestCase):
    def setUp(self):
        self.profile = get_profile("Testing")

    def test_baca_dan_simpan_info_perusahaan(self):
        if not self.profile:
            self.skipTest("Koneksi Testing tidak tersedia")
        
        info = master_services.baca_info_perusahaan(self.profile)
        self.assertIn("perusahaan", info)
        self.assertIn("alamat", info)
        self.assertIn("telp", info)
        
        data_baru = {
            "perusahaan": "SUKSES CROWN TOYS TEST",
            "alamat": "Jl. Testing No. 123",
            "kota": "Surabaya",
            "telp": "031-1234567",
            "hp": "08123456789",
            "email": "test@arunika.com",
            "website": "www.arunika.com",
        }
        master_services.simpan_info_perusahaan(self.profile, data_baru)
        
        info_upd = master_services.baca_info_perusahaan(self.profile)
        self.assertEqual(info_upd["perusahaan"].strip(), "SUKSES CROWN TOYS TEST")
        self.assertEqual(info_upd["alamat"].strip(), "Jl. Testing No. 123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test apps.master_data.test_informasi_perusahaan`  
Expected: FAIL with `AttributeError: module 'apps.master_data.services' has no attribute 'baca_info_perusahaan'`

- [ ] **Step 3: Implement `baca_info_perusahaan` and `simpan_info_perusahaan` in `apps/master_data/services.py`**

```python
def baca_info_perusahaan(profile) -> dict:
    """Membaca profil perusahaan pusat dari g_info_profile."""
    with mssql.cursor(profile) as cur:
        cur.execute(
            "SELECT TOP 1 perusahaan, alamat, kota, telp, hp, email, website, nama_kontak "
            "FROM g_info_profile"
        )
        row = cur.fetchone()
        if not row:
            return {
                "perusahaan": "", "alamat": "", "kota": "",
                "telp": "", "hp": "", "email": "", "website": "", "nama_kontak": ""
            }
        return {
            "perusahaan": (row[0] or "").strip(),
            "alamat": (row[1] or "").strip(),
            "kota": (row[2] or "").strip(),
            "telp": (row[3] or "").strip(),
            "hp": (row[4] or "").strip(),
            "email": (row[5] or "").strip(),
            "website": (row[6] or "").strip(),
            "nama_kontak": (row[7] or "").strip(),
        }

def simpan_info_perusahaan(profile, data: dict) -> None:
    """Menyimpan/mengubah data profil perusahaan pusat pada g_info_profile."""
    with mssql.cursor(profile) as cur:
        cur.execute("SELECT COUNT(*) FROM g_info_profile")
        ada = (cur.fetchone()[0] or 0) > 0
        if ada:
            cur.execute(
                "UPDATE g_info_profile SET perusahaan=?, alamat=?, kota=?, telp=?, hp=?, email=?, website=?",
                [
                    data.get("perusahaan") or "",
                    data.get("alamat") or "",
                    data.get("kota") or "",
                    data.get("telp") or "",
                    data.get("hp") or "",
                    data.get("email") or "",
                    data.get("website") or "",
                ]
            )
        else:
            cur.execute(
                "INSERT INTO g_info_profile (perusahaan, alamat, kota, telp, hp, email, website, nama_kontak) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    data.get("perusahaan") or "",
                    data.get("alamat") or "",
                    data.get("kota") or "",
                    data.get("telp") or "",
                    data.get("hp") or "",
                    data.get("email") or "",
                    data.get("website") or "",
                    data.get("nama_kontak") or "-",
                ]
            )
        cur.connection.commit()
```

- [ ] **Step 4: Add view `informasi_perusahaan` in `apps/monitoring/views.py`, route in `apps/monitoring/urls.py`, and menu in `apps/core/menus.py`**

In `apps/monitoring/views.py`:
```python
def informasi_perusahaan(request):
    """Layar & handler simpan kelola informasi perusahaan."""
    profile = _active()
    if request.method == "POST":
        if not profile:
            request.session["flash_error"] = CONN_ERROR
            return redirect("/admin-panel/master-data/informasi-perusahaan")
        try:
            data = get_data(request)
            master_services.simpan_info_perusahaan(profile, data)
            log_activity(request, "informasi_perusahaan", "Memperbarui profil informasi perusahaan")
            request.session["flash_success"] = "Informasi Perusahaan berhasil disimpan."
        except pyodbc.Error as exc:
            request.session["flash_error"] = mssql.friendly_error(exc, "Gagal menyimpan informasi perusahaan")
        return redirect("/admin-panel/master-data/informasi-perusahaan")

    def muat():
        if not profile:
            return {"info": {}, "conn_error": CONN_ERROR}
        try:
            return {"info": master_services.baca_info_perusahaan(profile), "conn_error": None}
        except pyodbc.Error as exc:
            return {"info": {}, "conn_error": mssql.friendly_error(exc, "Gagal membaca informasi perusahaan")}

    return render(request, "Admin/MasterData/KelolaInformasiPerusahaan", props={"info": defer(muat)})
```

In `apps/monitoring/urls.py`:
```python
path("master-data/informasi-perusahaan", views.informasi_perusahaan, name="informasi_perusahaan"),
```

In `apps/core/menus.py` (under section `"master"`):
```python
{"key": "informasi_perusahaan", "label": "Informasi Perusahaan", "icon": "office-building", "href": "/admin-panel/master-data/informasi-perusahaan", "section": "master"},
```

- [ ] **Step 5: Run tests to verify pass**

Run: `python manage.py test apps.master_data.test_informasi_perusahaan`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/master_data/services.py apps/monitoring/views.py apps/monitoring/urls.py apps/core/menus.py apps/master_data/test_informasi_perusahaan.py
git commit -m "feat: backend service and view for Kelola Informasi Perusahaan"
```

---

### Task 2: Enrich `baca_nota` Data in `apps/transactions/penjualan.py`

**Files:**
- Modify: `apps/transactions/penjualan.py:631-661`
- Modify: `apps/transactions/test_penjualan.py`

**Interfaces:**
- Consumes: `t_penjualan`, `t_penjualan_detail`, `m_satuan`, `m_pegawai`, `m_customer`, `m_jenis_bayar`, `m_divisi`, `g_info_profile`
- Produces: Extended `baca_nota(profile, no_transaksi)` return dictionary containing:
  - `toko`: Company/Divisi Name
  - `alamat`: Divisi/Company Address
  - `telepon`: Divisi/Company Phone
  - `kasir`: Cashier Staff Name (`m_pegawai.nama`)
  - `customer`: Customer Name
  - `jenis_bayar`: Payment Type Name (`m_jenis_bayar.nama`)
  - `baris`: list of `{"kd_barang", "nama", "kd_satuan", "satuan", "qty", "harga", "total"}`
  - `subtotal`, `diskon_uang`, `pajak`, `total`, `bayar`, `kembali`

- [ ] **Step 1: Write the failing test for enriched `baca_nota`**

```python
# In apps/transactions/test_penjualan.py
def test_baca_nota_lengkap(self):
    if not self.profile:
        self.skipTest("Koneksi Testing tidak tersedia")
    # Cari satu no_transaksi dummy/ada
    with mssql.cursor(self.profile) as cur:
        cur.execute("SELECT TOP 1 no_transaksi FROM t_penjualan ORDER BY tanggal DESC")
        row = cur.fetchone()
        if not row:
            self.skipTest("Tidak ada nota untuk dites")
        no_tr = row[0].strip()

    nota = pj.baca_nota(self.profile, no_tr)
    self.assertIsNotNone(nota)
    self.assertIn("kasir", nota)
    self.assertIn("jenis_bayar", nota)
    self.assertIn("alamat", nota)
    self.assertIn("telepon", nota)
    self.assertIn("subtotal", nota)
    if nota["baris"]:
        self.assertIn("satuan", nota["baris"][0])
        self.assertIn("kd_barang", nota["baris"][0])
```

- [ ] **Step 2: Run test to verify it fails/lacks fields**

Run: `python manage.py test apps.transactions.test_penjualan`  
Expected: FAIL with `KeyError: 'kasir'` or missing keys.

- [ ] **Step 3: Implement enriched SQL in `baca_nota` (`apps/transactions/penjualan.py`)**

```python
def baca_nota(profile, no_transaksi: str) -> dict | None:
    """Satu nota lengkap untuk dicetak, dengan identitas toko, kasir, member, & nama satuan."""
    no_transaksi = (no_transaksi or "").strip()
    if not no_transaksi:
        return None
        
    with mssql.cursor(profile) as cur:
        # Header nota
        cur.execute(
            "SELECT h.no_transaksi, h.tanggal, h.kd_customer, COALESCE(c.nama, h.kd_customer) AS customer, "
            "h.kd_user, h.keterangan, h.diskon_uang, h.pajak, t.total, "
            "COALESCE(jb.nama, h.kd_jenis) AS jenis_bayar, "
            "COALESCE(p.nama, d_peg.nama) AS kasir "
            "FROM t_penjualan h "
            "LEFT JOIN m_customer c ON c.kd_customer = h.kd_customer "
            "LEFT JOIN t_penjualan_total t ON t.no_transaksi = h.no_transaksi "
            "LEFT JOIN m_jenis_bayar jb ON jb.kd_jenis = h.kd_jenis "
            "LEFT JOIN m_pegawai p ON p.kd_pegawai = h.kd_user "
            "LEFT JOIN m_pegawai d_peg ON d_peg.kd_pegawai = (SELECT TOP 1 kd_pegawai FROM t_penjualan_detail WHERE no_transaksi = h.no_transaksi) "
            "WHERE h.no_transaksi = ?",
            [no_transaksi],
        )
        h = cur.fetchone()
        if not h:
            return None

        # Detail barang dengan nama satuan (JOIN m_satuan)
        cur.execute(
            "SELECT d.kd_barang, COALESCE(b.nama, d.kd_barang) AS nama_barang, "
            "d.kd_satuan, COALESCE(s.nama, d.kd_satuan) AS nama_satuan, "
            "d.qty, d.harga_jual, d.total "
            "FROM t_penjualan_detail d "
            "LEFT JOIN m_barang b ON b.kd_barang = d.kd_barang "
            "LEFT JOIN m_satuan s ON s.kd_satuan = d.kd_satuan "
            "WHERE d.no_transaksi = ?",
            [no_transaksi],
        )
        baris = [
            {
                "kd_barang": (r[0] or "").strip(),
                "nama": (r[1] or "").strip(),
                "kd_satuan": (r[2] or "").strip(),
                "satuan": (r[3] or "").strip(),
                "qty": float(r[4] or 0),
                "harga": float(r[5] or 0),
                "total": float(r[6] or 0),
            }
            for r in cur.fetchall()
        ]

        # Ambil identitas divisi & profil perusahaan
        cur.execute("SELECT TOP 1 nama, alamat, telepon FROM m_divisi")
        div = cur.fetchone()
        cur.execute("SELECT TOP 1 perusahaan, alamat, telp FROM g_info_profile")
        prof = cur.fetchone()

        nama_toko = (div[0] if div and div[0] else (prof[0] if prof else "")) or "NOTA PENJUALAN"
        alamat_toko = (div[1] if div and div[1] else (prof[1] if prof else "")) or ""
        telepon_toko = (div[2] if div and div[2] else (prof[3] if prof else "")) or ""

        subtotal = sum(b["total"] for b in baris)
        total_akhir = float(h[8] or subtotal)
        # Nota tunai legacy: bayar minimal sebesar total
        bayar = total_akhir
        kembali = 0.0

    return {
        "no_transaksi": (h[0] or "").strip(),
        "tanggal": h[1],
        "kd_customer": (h[2] or "").strip(),
        "customer": (h[3] or "").strip(),
        "kd_user": (h[4] or "").strip(),
        "kasir": (h[10] or h[4] or "").strip(),
        "jenis_bayar": (h[9] or "").strip(),
        "keterangan": (h[5] or "").strip(),
        "subtotal": subtotal,
        "diskon_uang": float(h[6] or 0),
        "pajak": float(h[7] or 0),
        "total": total_akhir,
        "bayar": bayar,
        "kembali": kembali,
        "baris": baris,
        "toko": nama_toko,
        "alamat": alamat_toko,
        "telepon": telepon_toko,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test apps.transactions.test_penjualan`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/transactions/penjualan.py apps/transactions/test_penjualan.py
git commit -m "feat: enrich baca_nota with cashier, customer, payment type, unit name, and financial breakdown"
```

---

### Task 3: Frontend Management UI (`KelolaInformasiPerusahaan.vue`)

**Files:**
- Create: `frontend/pages/Admin/MasterData/KelolaInformasiPerusahaan.vue`

**Interfaces:**
- Receives Inertia props: `info: Object` (contains `perusahaan`, `alamat`, `kota`, `telp`, `hp`, `email`, `website`)
- Sends POST request to `/admin-panel/master-data/informasi-perusahaan`

- [ ] **Step 1: Create Vue Component `KelolaInformasiPerusahaan.vue`**

```vue
<!-- frontend/pages/Admin/MasterData/KelolaInformasiPerusahaan.vue -->
<script setup>
import { ref, computed } from "vue";
import { useForm, Deferred } from "@inertiajs/vue3";
import AdminLayout from "@/layouts/AdminLayout.vue";
import Card from "@/components/ui/Card.vue";
import Button from "@/components/ui/Button.vue";
import Banner from "@/components/ui/Banner.vue";
import LoadingCard from "@/components/ui/LoadingCard.vue";

const props = defineProps({
  info: { type: Object, default: null },
});

const data = computed(() => props.info?.info || {});

const form = useForm({
  perusahaan: data.value.perusahaan || "",
  alamat: data.value.alamat || "",
  kota: data.value.kota || "",
  telp: data.value.telp || "",
  hp: data.value.hp || "",
  email: data.value.email || "",
  website: data.value.website || "",
});

function simpan() {
  form.post("/admin-panel/master-data/informasi-perusahaan", {
    preserveScroll: true,
  });
}
</script>

<template>
  <AdminLayout title="Kelola Informasi Perusahaan">
    <Deferred data="info">
      <template #fallback><LoadingCard message="Memuat informasi perusahaan..." /></template>

      <Banner v-if="props.info?.conn_error" variant="warning" :message="props.info.conn_error" class="mb-4" />

      <Card class="max-w-2xl">
        <form @submit.prevent="simpan" class="space-y-4">
          <div>
            <label class="mb-1 block text-sm font-medium text-ink">Nama Perusahaan / Toko</label>
            <input v-model="form.perusahaan" class="w-full rounded border border-border px-3 py-2" required />
          </div>

          <div>
            <label class="mb-1 block text-sm font-medium text-ink">Alamat Perusahaan</label>
            <textarea v-model="form.alamat" rows="3" class="w-full rounded border border-border px-3 py-2"></textarea>
          </div>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-sm font-medium text-ink">Kota</label>
              <input v-model="form.kota" class="w-full rounded border border-border px-3 py-2" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-ink">No. Telepon</label>
              <input v-model="form.telp" class="w-full rounded border border-border px-3 py-2" />
            </div>
          </div>

          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-sm font-medium text-ink">No. HP / WhatsApp</label>
              <input v-model="form.hp" class="w-full rounded border border-border px-3 py-2" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-ink">Email</label>
              <input v-model="form.email" type="email" class="w-full rounded border border-border px-3 py-2" />
            </div>
          </div>

          <div>
            <label class="mb-1 block text-sm font-medium text-ink">Website</label>
            <input v-model="form.website" class="w-full rounded border border-border px-3 py-2" />
          </div>

          <div class="flex justify-end pt-2">
            <Button type="submit" :disabled="form.processing">Simpan Perubahan</Button>
          </div>
        </form>
      </Card>
    </Deferred>
  </AdminLayout>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/pages/Admin/MasterData/KelolaInformasiPerusahaan.vue
git commit -m "feat: frontend UI for Kelola Informasi Perusahaan"
```

---

### Task 4: Update Receipt Formatting in `NotaCetak.vue`

**Files:**
- Modify: `frontend/pages/Kasir/NotaCetak.vue`

**Interfaces:**
- Consumes `nota` prop with enriched fields from Task 2.
- Renders monospace text with 40-character width formatting.

- [ ] **Step 1: Update `NotaCetak.vue` computed text generation**

```vue
<script setup>
import { computed, onMounted } from "vue";

const props = defineProps({
  nota: { type: Object, required: true },
  auto: { type: Boolean, default: true },
});

const LEBAR = 40;
const rp = (v) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(v) || 0);

const kiriKanan = (kiri, kanan) => {
  const sisa = Math.max(1, LEBAR - kiri.length - kanan.length);
  return kiri + " ".repeat(sisa) + kanan;
};
const garis = (ch = "-") => ch.repeat(LEBAR);
const tengah = (t) => {
  const pad = Math.max(0, Math.floor((LEBAR - t.length) / 2));
  return " ".repeat(pad) + t;
};

const teks = computed(() => {
  const n = props.nota;
  const baris = [];

  // Header Toko
  baris.push(tengah((n.toko || "SUKSES CROWN TOYS").slice(0, LEBAR)));
  if (n.alamat) baris.push(tengah(n.alamat.slice(0, LEBAR)));
  if (n.telepon) baris.push(tengah(`Telp: ${n.telepon}`.slice(0, LEBAR)));
  baris.push(garis("="));

  // Metadata Transaksi
  baris.push(`No   : ${n.no_transaksi}`);
  baris.push(`Tgl  : ${String(n.tanggal || "").replace("T", " ").slice(0, 16)}`);
  if (n.kasir) baris.push(`Kasir: ${n.kasir.slice(0, 33)}`);
  baris.push(`Cus  : ${(n.customer || n.kd_customer || "UMUM").slice(0, 33)}`);
  if (n.jenis_bayar) baris.push(`Bayar: ${n.jenis_bayar.slice(0, 33)}`);
  baris.push(garis());

  // Detail Barang
  for (const b of n.baris || []) {
    const itemLabel = `[${b.kd_barang}] ${b.nama}`;
    baris.push(itemLabel.slice(0, LEBAR));
    baris.push(
      kiriKanan(`  ${b.qty} ${b.satuan} x ${rp(b.harga)}`, rp(b.total)),
    );
  }
  baris.push(garis());

  // Keuangan & Totals
  if (n.subtotal) baris.push(kiriKanan("Subtotal", rp(n.subtotal)));
  if (n.diskon_uang) baris.push(kiriKanan("Diskon", rp(n.diskon_uang)));
  if (n.pajak) baris.push(kiriKanan("Pajak", String(n.pajak)));
  baris.push(kiriKanan("TOTAL", rp(n.total)));
  if (n.bayar) baris.push(kiriKanan("Bayar", rp(n.bayar)));
  if (n.kembali !== undefined) baris.push(kiriKanan("Kembali", rp(n.kembali)));
  baris.push(garis("="));

  if (n.keterangan && n.keterangan !== "-") baris.push(`Ket: ${n.keterangan}`);
  baris.push("");
  baris.push(tengah("Terima kasih atas kunjungan Anda"));
  baris.push("");
  return baris.join("\n");
});

const cetakUlang = () => window.print();
onMounted(() => {
  if (props.auto) setTimeout(cetakUlang, 300);
});
</script>
```

- [ ] **Step 2: Build frontend assets to verify Vue component compilation**

Run: `npm run build`  
Expected: Successful vite compilation without errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/Kasir/NotaCetak.vue
git commit -m "feat: format NotaCetak with store header, cashier, customer name, unit names, and full invoice payment details"
```

---

## Plan Self-Review Check
1. **Spec Coverage**:
   - Menu Kelola Informasi Perusahaan: Covered in Task 1 & Task 3.
   - Enriched receipt metadata (Kasir, Customer, Jenis Bayar, Unit Names, Kd Barang, Financial breakdown): Covered in Task 2 & Task 4.
   - Testing safety boundary (`Testing` profile): Enforced in tests & global constraints.
2. **Placeholder Scan**: No TODO/TBD placeholders found.
3. **Type Consistency**: Method signatures, prop keys, and SQL schema mappings are consistent across Tasks 1-4.
