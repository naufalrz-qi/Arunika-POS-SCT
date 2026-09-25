"""Payload sync legacy tak boleh jadi NULL karena kolom yang tak ditulis Arunika.

Trigger feed merangkai setiap kolom baris dengan `+`; satu kolom NULL membuat
`tbl_tmp_post.query` dan `tbl_log_transaksi.formatted_data` NULL seluruhnya.
Dokumennya tetap tersimpan — hanya tak pernah sampai ke pusat, ke `feed_sync`,
maupun ke Nota Tanggal Mundur. Tak ada galat di mana pun.

Diperiksa terhadap dump KEDUA server acuan (`docs/skema/`), karena trigger
keduanya berbeda: testGudang misalnya tak punya `delete_temp` untuk nota.
Dump tak memuat bound default gaya lama, jadi test ini lebih ketat dari server
sungguhan — dan itu yang diinginkan: jalur tulis menulis nilainya sendiri alih-
alih bergantung pada DEFAULT yang keberadaannya tak bisa dibuktikan dari repo.
Kebenaran di server hidup diperiksa `manage.py cek_payload_sync`.

Test ini lahir dari temuan nyata: `buat_nota` tak menulis `tanggal_setor`, dan
di tiruan legacy dengan trigger asli setiap nota buatan layar kasir Arunika
tercatat dengan payload NULL.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.transactions import payload_sync as ps

DUMP = ("skema-grosirPusat.txt", "skema-testGudang.txt")


def _baca_dump(nama: str):
    """(kolom, trigger) dari satu dump skema.

    kolom   = {tabel: {kolom: {"nullable", "default", "computed"}}}
    trigger = {tabel: [(nama_trigger, teks)]}
    """
    teks = (Path(settings.BASE_DIR) / "docs" / "skema" / nama).read_text(
        encoding="utf-8", errors="replace").replace("\r", "")

    default = set()
    # `## BOUND DEFAULT` baru ada di dump yang dibuat sesudah skrip dump ikut
    # membaca bound default; dump lama cukup punya `## DEFAULT CONSTRAINT`.
    for judul in ("## DEFAULT CONSTRAINT", "## BOUND DEFAULT"):
        if judul not in teks:
            continue
        bagian = teks.split(judul, 1)[1].split("\n## ", 1)[0]
        for ln in bagian.splitlines()[1:]:
            m = re.match(r"^\s+(\w+)\s+(\w+)\s+\S", ln)
            if m:
                default.add((m.group(1).lower(), m.group(2).lower()))

    kolom, tabel = {}, None
    bagian = teks.split("## KOLOM PER TABEL", 1)[1].split("## DEFINISI TRIGGER", 1)[0]
    for ln in bagian.splitlines():
        m = re.match(r"^  \[(\w+)\]$", ln)
        if m:
            tabel = m.group(1).lower()
            kolom[tabel] = {}
            continue
        m = re.match(r"^\s+\d+\s+(\w+)\s+\S+(?:\s+IDENTITY)?\s+(.*)$", ln)
        if m and tabel:
            sisa = m.group(2)
            kolom[tabel][m.group(1).lower()] = {
                "nullable": "NOT NULL" not in sisa,
                "computed": "COMPUTED" in sisa,
                "default": "dump" if (tabel, m.group(1).lower()) in default else None,
            }

    trigger = {}
    for m in re.finditer(r"^----- (\w+) -----\n(.*?)(?=^----- |\Z)", teks, re.S | re.M):
        # `on t_x`, `on dbo.t_x`, dan `on [dbo].[t_x]` — ketiganya ada di dump.
        on = re.search(r"CREATE\s+TRIGGER\s+\S+\s+on\s+(?:\[?dbo\]?\.)?\[?(\w+)\]?",
                       m.group(2), re.I)
        if on:
            trigger.setdefault(on.group(1).lower(), []).append((m.group(1), m.group(2)))
    return kolom, trigger


class PengurainyaMasihBekerja(SimpleTestCase):
    """Penjaga bagi penjaganya: kalau format dump berubah dan regexnya berhenti
    cocok, test di bawah akan hijau tanpa memeriksa apa pun."""

    def test_trigger_nota_ditemukan_di_kedua_dump(self):
        for nama in DUMP:
            kolom, trigger = _baca_dump(nama)
            ins = [t for n, t in trigger.get("t_penjualan", []) if n.startswith("insert_temp_m_")]
            self.assertTrue(ins, f"{nama}: trigger insert t_penjualan tak ditemukan")
            self.assertGreater(len(ps.kolom_payload(ins[0])), 10, nama)
            self.assertIn("tanggal_setor", kolom["t_penjualan"], nama)

    def test_setiap_trigger_feed_terpetakan_ke_tabelnya(self):
        """`insert_temp_m_<tabel>` harus tercatat di bawah <tabel>. Versi pertama
        pengurai ini membaca `on [dbo].[t_penjualan_order]` sebagai tabel "dbo",
        dan trigger order testGudang lolos dari pemeriksaan tanpa tanda apa pun."""
        for nama in DUMP:
            _, trigger = _baca_dump(nama)
            for tabel, daftar in trigger.items():
                for n, _ in daftar:
                    for awalan in ps.AWALAN_TRIGGER + ("delete_temp_m_",):
                        if n.startswith(awalan):
                            self.assertEqual(tabel, n[len(awalan):].lower(), f"{nama}: {n}")

    def test_kolom_payload(self):
        teks = ("SELECT 'val__no_transaksi__'+convert(varchar,no_transaksi)"
                "+';val__tanggal_setor__'+cast(YEAR(tanggal_setor) AS VARCHAR(4))"
                "+';val__divisi_id__'+convert(varchar,dbo.getDivisionID())")
        self.assertEqual(ps.kolom_payload(teks), {"no_transaksi", "tanggal_setor"})

    def test_berisiko(self):
        kolom = {
            "a": {"nullable": True, "default": None, "computed": False},
            "b": {"nullable": False, "default": None, "computed": False},
            "c": {"nullable": True, "default": "(getdate())", "computed": False},
            "d": {"nullable": True, "default": None, "computed": True},
            "e": {"nullable": True, "default": None, "computed": False},
        }
        self.assertEqual(ps.berisiko({"a", "b", "c", "d", "e", "hilang"}, kolom, {"e"}), ["a"])


class TakAdaPayloadNull(SimpleTestCase):
    def test_setiap_kolom_payload_nullable_ditulis_arunika(self):
        """Kolom payload trigger feed yang boleh NULL dan tanpa DEFAULT harus
        ditulis oleh jalur tulis Arunika, di KEDUA server acuan."""
        ditulis = ps.kolom_ditulis()
        bolong = []
        for nama in DUMP:
            kolom, trigger = _baca_dump(nama)
            for tabel, isi in sorted(ditulis.items()):
                for n, teks in trigger.get(tabel, []):
                    if not n.startswith(ps.AWALAN_TRIGGER):
                        continue
                    for k in ps.berisiko(ps.kolom_payload(teks), kolom.get(tabel, {}), isi):
                        bolong.append(f"{nama}: {tabel}.{k} ({n})")
        self.assertEqual(
            sorted(set(bolong)), [],
            "kolom ini dirangkai trigger feed tapi tak ditulis Arunika — payload "
            "sync baris buatan Arunika akan NULL seluruhnya")

    def test_setiap_tabel_tulis_ada_di_dump(self):
        """Nama tabel yang salah eja di `kolom_ditulis()` membuat test di atas
        diam-diam tak memeriksa apa pun untuk tabel itu."""
        for nama in DUMP:
            kolom, _ = _baca_dump(nama)
            hilang = sorted(t for t in ps.kolom_ditulis() if t not in kolom)
            self.assertEqual(hilang, [], nama)
