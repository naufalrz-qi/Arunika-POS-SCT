"""Kolom tanggal transaksi harus menampilkan jamnya.

Dua kolom yang paling sering dibandingkan orang — `tanggal` (bisa diubah
operator di aplikasi POS lama) dan `tanggal_server` (tidak bisa) — dulu
diformat oleh dua potong kode berbeda, dan keduanya membuang jam yang sudah
dikirim server. Kesalahan seperti itu tak pernah melempar galat: angkanya benar,
hanya kurang teliti, dan halaman berikutnya akan menyalin polanya.

Dipindai dari berkas Vue, bukan dari daftar tangan — pola yang sama dengan
`test_hidden_data.KolomRupiahTerdaftar`. Daftar tangan akan basi persis seperti
yang dijaganya.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

HALAMAN = Path(settings.BASE_DIR) / "frontend" / "pages" / "Admin"

# Kolom yang namanya tanggal-transaksi. `jatuh_tempo`/`tanggal_terima` SENGAJA
# tak masuk: keduanya memang menyimpan jam di legacy, tapi jamnya jam
# pencatatan yang tersebar acak (diukur di grosirPusat: jatuh tempo menumpuk di
# sore hari, dan hanya 30% barisnya berjam sama dengan jam notanya), bukan janji
# waktu. Menampilkannya menjanjikan ketelitian yang tak dimiliki datanya.
KUNCI = ("tanggal", "tanggal_server", "created_at")

# Objek kolom satu baris: `{ key: "...", ... }`.
KOLOM = re.compile(r'\{\s*key:\s*"(?P<key>[a-z_]+)"(?P<sisa>[^}]*)\}')

# Berkas: alasan. Kosong hari ini — ditulis supaya pengecualian berikutnya harus
# menyebutkan alasannya di sini, bukan diselipkan diam-diam.
DIKECUALIKAN: dict[str, str] = {}


class KolomTanggalBerjam(SimpleTestCase):
    def test_setiap_kolom_tanggal_memakai_datetime(self):
        pelanggar = []
        diperiksa = 0
        for berkas in sorted(HALAMAN.rglob("*.vue")):
            rel = berkas.relative_to(HALAMAN).as_posix()
            if rel in DIKECUALIKAN:
                continue
            for m in KOLOM.finditer(berkas.read_text(encoding="utf-8")):
                if m.group("key") not in KUNCI:
                    continue
                sisa = m.group("sisa")
                # `type:` menandai definisi FILTER (utils/reportFilters.js), bukan
                # kolom tabel — ia tak pernah dirender lewat `fmt()`.
                if "type:" in sisa:
                    continue
                diperiksa += 1
                if 'format: "datetime"' not in sisa:
                    pelanggar.append(f"{rel}: {m.group(0).strip()}")
        self.assertGreaterEqual(
            diperiksa, 25, "pemindai nyaris tak menemukan kolom — polanya berubah?")
        self.assertEqual(
            pelanggar, [],
            'kolom tanggal transaksi harus format: "datetime" '
            "(atau masuk DIKECUALIKAN beserta alasannya)")

    def test_helper_tanggal_dipakai_bukan_toLocaleDateString(self):
        """Satu formatter, bukan satu per komponen.

        Ini yang menyebabkan bug-nya: dua komponen memformat sendiri-sendiri,
        dan yang satu tak pernah tahu yang lain sudah berubah.
        """
        akar = Path(settings.BASE_DIR) / "frontend"
        sendiri = [
            p.relative_to(akar).as_posix()
            for p in list((akar / "components").rglob("*.vue")) + list(HALAMAN.rglob("*.vue"))
            if "toLocaleDateString" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(
            sendiri, [],
            "pakai `tanggal`/`tanggalJam` dari frontend/utils/tanggal.js")
