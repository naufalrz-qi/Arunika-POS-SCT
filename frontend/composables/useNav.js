import { computed } from "vue";
import { usePage } from "@inertiajs/vue3";
import { storeToRefs } from "pinia";
import { useUserStore } from "@/stores/user";

// Display labels per section group. Keep in sync with apps/core/menus.py.
const SECTION_LABELS = {
  pos_jual: "Penjualan (Kasir)",
  pos_beli: "Pembelian (Kasir)",
  pos_lain: "Lainnya",
  ringkasan: "Ringkasan",
  penjualan: "Penjualan",
  pembelian: "Pembelian",
  akuntansi: "Akuntansi",
  stok: "Inventori & Stok",
  analitik: "Analitik",
  promo: "Promo & Voucher",
  kas: "Kas & Shift",
  master: "Master Data",
  master_harga: "Harga & Update Barang",
  master_sync: "Sinkronisasi",
  admin: "Administrasi",
};

// Sidebar groups: backend sections consolidated into 6 groups; the original
// sections become sub-headers inside each group. `icon` is what the collapsed
// sidebar shows in place of the group label.
const NAV_GROUPS = [
  // Tetap SATU tab "Kasir"; pemecahannya terjadi di sidebar sebagai tiga
  // sub-judul, sama seperti Master Data. Menjadikannya tiga tab akan memaksa
  // kasir berpindah tab untuk pekerjaan yang ia lakukan berselang-seling.
  { key: "pos", label: "Kasir", icon: "cart", sections: ["pos_jual", "pos_beli", "pos_lain"] },
  { key: "ringkasan", label: "Ringkasan", icon: "dashboard", sections: ["ringkasan"] },
  { key: "laporan", label: "Laporan", icon: "chart", sections: ["penjualan", "pembelian", "akuntansi", "analitik"] },
  { key: "operasional", label: "Operasional", icon: "box", sections: ["stok", "promo", "kas"] },
  { key: "master", label: "Master Data", icon: "list", sections: ["master", "master_harga", "master_sync"] },
  { key: "admin", label: "Administrasi", icon: "key", sections: ["admin"] },
];

// Lipatan sidebar. Menu yang sebenarnya satu layar dengan sudut pandang berbeda
// (Penjualan per Nota/Customer/User/Periode) dilipat jadi SATU entri sidebar,
// dan halamannya menampilkan anggota yang lain sebagai tab (AdminLayout).
// Sebelumnya superadmin melihat 71 entri. `hub` tak memakai tab: entrinya
// menuju halaman kartu sendiri, dan anggotanya pindah ke section `section`.
//
// Hanya tampilan. URL, kunci menu, dan izin per menu tak berubah; tab dan
// kartu hanya memuat anggota yang diberikan, dan lipatan yang anggotanya
// diberikan < 2 tampil sebagai menu biasa. Ctrl+K tetap mendaftar setiap menu.
// Anggota lipatan non-hub harus satu section — dijaga
// apps/core/test_lipatan_menu.py, begitu pula keberadaan setiap kuncinya.
const LIPATAN = [
  {
    key: "lipat_penjualan",
    label: "Penjualan",
    anggota: {
      penjualan_all: "Detail",
      penjualan_nota: "per Nota",
      penjualan_customer: "per Customer",
      penjualan_user: "per User",
      penjualan_periode: "per Periode",
    },
  },
  {
    key: "lipat_pembelian",
    label: "Pembelian",
    anggota: { pembelian: "Detail", pembelian_supplier: "per Supplier", pembelian_periode: "per Periode" },
  },
  { key: "lipat_stok", label: "Stok", anggota: { stock: "Stok Akhir", stok_divisi: "per Divisi" } },
  { key: "lipat_opname", label: "Opname & Koreksi", anggota: { opname: "Opname Stok", koreksi_stok: "Koreksi Stok" } },
  { key: "lipat_fmi", label: "FMI", anggota: { fmi_penjualan: "Penjualan", fmi_stok: "Stok" } },
  { key: "lipat_promo", label: "Promo & Voucher", anggota: { promo: "Promo & Diskon", voucher: "Voucher" } },
  { key: "lipat_biaya", label: "Biaya", anggota: { biaya_operasional: "Biaya Operasional", biaya_kategori: "per Kategori" } },
  {
    key: "lipat_input_kas",
    label: "Input Kas",
    anggota: {
      kas_biaya_input: "Biaya Operasional",
      kas_pendapatan: "Pendapatan Lain-Lain",
      kas_penambahan: "Penambahan Kas",
      kas_mutasi: "Mutasi Kas",
    },
  },
  {
    key: "lipat_sync",
    label: "Sinkronisasi",
    anggota: { sync_harga: "Harga", sync_master: "Master Data", sync_history: "Riwayat Operasi", sync_health: "Kesehatan" },
  },
  {
    // Dibuka seminggu sekali atau lebih jarang — tak perlu memakan tempat di
    // sidebar setiap hari. Nilai anggota = keterangan satu baris di kartunya.
    key: "pengaturan",
    label: "Pengaturan",
    icon: "key",
    href: "/admin-panel/pengaturan",
    section: "admin",
    hub: true,
    anggota: {
      connections: "Alamat tiap server MS SQL dan server acuan harga pokok.",
      menus: "Menu dan kolom rupiah yang boleh dibuka tiap akun.",
      tautan_user: "Pasangan akun aplikasi dengan user legacy, per koneksi.",
      kode_nota: "Awalan nomor nota tiap divisi.",
      transfer_arunika: "Salin data legacy ke database Arunika untuk pengujian.",
      cadangan: "Cadangan database aplikasi dan pemulihannya.",
      migrasi: "Terapkan perubahan skema sesudah rilis, tanpa terminal.",
      informasi_perusahaan: "Nama, alamat, dan kontak perusahaan.",
      kelola_referensi: "Kategori, merk, jenis biaya, dan tabel referensi lain.",
    },
  },
];
const LIPATAN_PER_KEY = Object.fromEntries(
  LIPATAN.flatMap((l) => Object.keys(l.anggota).map((k) => [k, l])),
);
const urutanDi = (l, key) => Object.keys(l.anggota).indexOf(key);

// Single source for nav logic: section grouping + active-state matching.
export function useNav() {
  const page = usePage();
  const { allowedMenus } = storeToRefs(useUserStore());

  const currentPath = computed(() =>
    page.url.split(/[?#]/)[0].replace(/\/+$/, ""),
  );

  // Segment-boundary match so /laporan/penjualan doesn't stay active on
  // /laporan/penjualan-periode.
  function isActive(href) {
    const h = href.replace(/\/+$/, "");
    return currentPath.value === h || currentPath.value.startsWith(h + "/");
  }

  // Group the (already RBAC-filtered) menus by section, preserving arrival
  // order. Items without a section fall back to "ringkasan". Anggota hub pindah
  // ke section hub-nya, supaya sidebar, jejak header, dan grup yang terbuka
  // sepakat soal di mana mereka tinggal.
  const sections = computed(() => {
    const groups = [];
    const byKey = {};
    for (const item of allowedMenus.value) {
      const l = LIPATAN_PER_KEY[item.key];
      const key = (l?.hub && l.section) || item.section || "ringkasan";
      if (!byKey[key]) {
        byKey[key] = { key, label: SECTION_LABELS[key] || key, items: [] };
        groups.push(byKey[key]);
      }
      byKey[key].items.push(item);
    }
    return groups;
  });

  // Section containing the current page; falls back to the first section so
  // the sidebar is never empty on unknown routes (e.g. /admin-panel/profile).
  const activeSection = computed(() => {
    const hub = LIPATAN.find((l) => l.hub && isActive(l.href));
    return (
      sections.value.find((s) => s.items.some((it) => isActive(it.href))) ??
      (hub && sections.value.find((s) => s.key === hub.section)) ??
      sections.value[0] ??
      null
    );
  });

  // Anggota lipatan `key` yang diberikan ke akun ini, urut seperti di LIPATAN.
  // `keterangan` = nilai anggota (label tab, atau teks kartu untuk hub).
  function anggotaDari(key) {
    const l = LIPATAN.find((x) => x.key === key);
    if (!l) return [];
    return allowedMenus.value
      .filter((m) => m.key in l.anggota)
      .sort((a, b) => urutanDi(l, a.key) - urutanDi(l, b.key))
      .map((m) => ({ ...m, keterangan: l.anggota[m.key], aktif: isActive(m.href) }));
  }

  // Lipatan yang memuat halaman ini, kalau anggotanya yang diberikan ≥ 2.
  // Dasar baris tab di AdminLayout dan jejak "Pengaturan" di header.
  const lipatanAktif = computed(() => {
    const l = LIPATAN.find(
      (x) => (x.href && isActive(x.href)) || allowedMenus.value.some((m) => m.key in x.anggota && isActive(m.href)),
    );
    const anggota = l ? anggotaDari(l.key) : [];
    return anggota.length >= 2 ? { key: l.key, label: l.label, href: l.href, hub: !!l.hub, anggota } : null;
  });

  // Satu daftar item sidebar setelah dilipat. Lipatan menempati posisi anggota
  // pertamanya dan menuju anggota pertama (urutan LIPATAN); hub selalu di ujung.
  function lipat(items) {
    const out = [];
    const hubs = [];
    const selesai = new Set();
    for (const it of items) {
      const l = LIPATAN_PER_KEY[it.key];
      if (!l) {
        out.push(it);
        continue;
      }
      if (selesai.has(l.key)) continue;
      const anggota = items
        .filter((x) => LIPATAN_PER_KEY[x.key] === l)
        .sort((a, b) => urutanDi(l, a.key) - urutanDi(l, b.key));
      if (anggota.length < 2) {
        out.push(it);
        continue;
      }
      selesai.add(l.key);
      (l.hub ? hubs : out).push({
        key: l.key,
        label: l.label,
        icon: l.icon || anggota[0].icon,
        href: l.href || anggota[0].href,
        hrefs: [...anggota.map((a) => a.href), ...(l.href ? [l.href] : [])],
      });
    }
    return [...out, ...hubs];
  }

  const itemAktif = (item) => (item.hrefs || [item.href]).some(isActive);

  // Sidebar groups: NAV_GROUPS with only the (RBAC-visible) sections present;
  // sections outside NAV_GROUPS get their own tab so nothing silently vanishes.
  const tabs = computed(() => {
    const byKey = Object.fromEntries(sections.value.map((s) => [s.key, s]));
    const grouped = new Set(NAV_GROUPS.flatMap((g) => g.sections));
    const out = NAV_GROUPS.map((g) => {
      const subsections = g.sections.map((k) => byKey[k]).filter(Boolean);
      return {
        key: g.key,
        label: g.label,
        icon: g.icon,
        subsections,
        items: subsections.flatMap((s) => s.items),
      };
    }).filter((t) => t.items.length);
    for (const s of sections.value) {
      if (!grouped.has(s.key)) {
        out.push({ key: s.key, label: s.label, icon: s.items[0].icon, subsections: [s], items: s.items });
      }
    }
    return out;
  });

  const activeTab = computed(
    () =>
      tabs.value.find((t) => t.subsections.includes(activeSection.value)) ??
      tabs.value[0] ??
      null,
  );

  return { sections, tabs, activeSection, activeTab, isActive, lipat, itemAktif, lipatanAktif, anggotaDari };
}
